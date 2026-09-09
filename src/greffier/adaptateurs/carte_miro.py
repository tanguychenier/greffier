"""Écrire la carte d'un sujet sur un tableau Miro, en objets natifs.

**Pas dans un widget « Mindmap ».** C'est le piège de ce sujet, et il a déjà été
payé : le widget est une application tierce, ses nœuds ne sont ni créables ni
modifiables par l'API REST, et la seule voie qui reste est la souris. Cette voie
a été essayée le 2026-08-20 et a produit des textes mélangés et des objets
parasites, parce qu'elle n'est ni reproductible ni relisible. La carte est donc
faite de **pense-bêtes et de connecteurs**, que l'API sait écrire *et relire* —
et c'est la relecture qui permet de compléter une carte au lieu d'en créer une
seconde.

Trois garde-fous, dans le code et non dans une consigne :

1. **Une liste de tableaux interdits.** Un tableau documente un circuit de
   signature et n'appartient pas à cet outil ; écrire dessus a été explicitement
   défendu. Un identifiant y figurant fait échouer l'appel, pas un
   avertissement.
2. **On n'écrit que sur un tableau que Greffier a créé**, ou qu'un humain a
   inscrit dans le registre des sujets. Découvrir un tableau et s'y mettre
   n'arrive jamais.
3. **On lit avant d'écrire, et on n'écrit que ce qui manque.** Aucune
   suppression, aucune modification de texte existant : ce que quelqu'un a posé
   reste tel quel.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from greffier.domaine.carte import Carte, Etat, Noeud
from greffier.domaine.mise_en_page import disposer

BASE = "https://api.miro.com/v2"

#: Tableaux sur lesquels cet outil n'écrit jamais, quoi qu'on lui demande.
#: « Circuit Signature CASA » documente les étapes d'un circuit de signature et
#: appartient à quelqu'un d'autre : une écriture par erreur y serait grave, et
#: la question a déjà été posée une fois par son auteur.
INTERDITS = frozenset({"uXjVH5WwzTI="})

#: Ce qui préfixe les tableaux créés par l'outil, pour qu'on les distingue d'un
#: coup d'œil de ceux d'une équipe.
PREFIXE = "Greffier"

#: Couleurs des pense-bêtes selon l'état. Ce qui est en discussion ne doit pas
#: se lire comme une décision : la couleur le dit avant le texte.
COULEURS = {
    Etat.ACTE: "light_green",
    Etat.EN_DISCUSSION: "light_yellow",
    Etat.DEPASSE: "gray",
}

#: La racine se distingue de ses branches : c'est le sujet, pas un point.
COULEUR_SUJET = "light_blue"


class MiroRefuse(RuntimeError):
    """L'appel n'a pas eu lieu, et pour une raison présentable."""


@dataclass(frozen=True, slots=True)
class Ecrit:
    """Ce qu'une publication a fait. Rien n'est jamais supprimé."""

    tableau: str
    poses: tuple[str, ...] = ()
    deja: tuple[str, ...] = ()
    adresse: str = ""
    #: Liens tracés, et liens qui ont échoué. Les compter plutôt que d'avaler
    #: l'échec : une carte sans un seul trait a été publiée ainsi, et rien ne
    #: l'a dit — l'API attendait des identifiants numériques, pas des chaînes.
    liens: int = 0
    liens_manques: int = 0


def jeton() -> str:
    """Le jeton d'accès, depuis l'environnement ou un fichier désigné par lui.

    Jamais un chemin en dur : le jeton d'un poste n'a pas à être deviné par le
    code, et un outil public ne doit pas aller chercher dans le dossier de
    travail d'un projet.
    """
    direct = os.environ.get("GREFFIER_MIRO_JETON", "").strip()
    if direct:
        return direct
    fichier = os.environ.get("GREFFIER_MIRO_JETON_FICHIER", "").strip()
    if fichier:
        chemin = Path(fichier).expanduser()
        if chemin.exists():
            return chemin.read_text(encoding="utf-8").strip()
    raise MiroRefuse(
        "aucun jeton Miro : pose « GREFFIER_MIRO_JETON », ou "
        "« GREFFIER_MIRO_JETON_FICHIER » vers le fichier qui le contient"
    )


def _appeler(chemin: str, methode: str = "GET",
             corps: dict[str, Any] | None = None) -> dict[str, Any]:
    requete = urllib.request.Request(
        f"{BASE}{chemin}",
        method=methode,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": f"Bearer {jeton()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            brut = reponse.read().decode("utf-8")
            return json.loads(brut) if brut.strip() else {}
    except urllib.error.HTTPError as souci:
        detail = souci.read().decode("utf-8", "replace")[:200]
        raise MiroRefuse(f"Miro a répondu {souci.code} : {detail}") from souci
    except (urllib.error.URLError, TimeoutError) as souci:
        raise MiroRefuse(f"Miro est injoignable : {souci}") from souci


def _garder(tableau: str) -> str:
    """Refuse tout de suite un tableau interdit."""
    if tableau in INTERDITS:
        raise MiroRefuse(
            f"le tableau {tableau} est sur la liste des tableaux interdits : "
            "cet outil n'y écrit jamais"
        )
    return tableau


def creer_le_tableau(sujet: str) -> tuple[str, str]:
    """Crée le tableau d'un sujet. Rend son identifiant et son adresse."""
    reponse = _appeler("/boards", "POST", {
        "name": f"{PREFIXE} — {sujet}",
        "description": (
            f"Carte du sujet « {sujet} », tenue par Greffier au fil des réunions. "
            "Jaune : en discussion. Vert : acté. Gris : dépassé. "
            "Ce qui est ajouté à la main est conservé."
        ),
    })
    identifiant = str(reponse.get("id", ""))
    if not identifiant:
        raise MiroRefuse("Miro n'a pas rendu d'identifiant de tableau")
    return (identifiant, str(reponse.get("viewLink", "")))


@dataclass(frozen=True, slots=True)
class Pose:
    """Un point déjà sur le tableau, et ce qu'on en sait."""

    identifiant: str
    x: int
    y: int
    #: Vrai si le contenu porte la mention d'une réunion, donc si c'est l'outil
    #: qui l'a posé. Sinon, un humain l'a écrit à la main — et c'est ce qui
    #: mérite de revenir dans la réunion suivante.
    de_l_outil: bool = False


def objets_presents(tableau: str) -> dict[str, str]:
    """Les points déjà sur le tableau : libellé en clair → identifiant d'objet.

    L'identifiant sert à **rattacher** un point ajouté plus tard à un parent qui
    existait déjà. Sans lui, les branches des publications suivantes flottaient
    sans lien : la première passe traçait douze traits, la seconde aucun, et la
    carte se dégradait à mesure qu'on la complétait — exactement ce qu'elle est
    censée éviter.
    """
    _garder(tableau)
    trouves: dict[str, str] = {}
    curseur = ""
    while True:
        parametres = {"limit": "50"}
        if curseur:
            parametres["cursor"] = curseur
        reponse = _appeler(
            f"/boards/{urllib.parse.quote(tableau, safe='')}/items"
            f"?{urllib.parse.urlencode(parametres)}"
        )
        for objet in reponse.get("data", []):
            contenu = (objet.get("data") or {}).get("content", "")
            if not contenu:
                continue
            # La première ligne porte le point ; les suivantes son état et sa
            # provenance, qui ne font pas partie du libellé.
            premiere = _sans_balises(contenu.split("</p>")[0])
            if premiere:
                trouves.setdefault(premiere, str(objet.get("id", "")))
        curseur = str(reponse.get("cursor", ""))
        if not curseur:
            return trouves


#: Ce qui trahit un point posé par l'outil : la ligne de provenance qu'il
#: ajoute sous le libellé, « 2026-09-09_10h05_reunion ».
_PROVENANCE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}h\d{2}")


def poses_presentes(tableau: str) -> dict[str, Pose]:
    """Les points du tableau, avec leur place et leur origine.

    L'origine sert à deux choses : poser une pastille à côté d'un point sans le
    modifier, et savoir ce qu'un humain a ajouté depuis la dernière réunion —
    c'est tout l'intérêt d'une carte partagée, et cela n'était jamais relu.
    """
    _garder(tableau)
    trouves: dict[str, Pose] = {}
    curseur = ""
    while True:
        parametres = {"limit": "50"}
        if curseur:
            parametres["cursor"] = curseur
        reponse = _appeler(
            f"/boards/{urllib.parse.quote(tableau, safe='')}/items"
            f"?{urllib.parse.urlencode(parametres)}"
        )
        for objet in reponse.get("data", []):
            contenu = (objet.get("data") or {}).get("content", "")
            if not contenu:
                continue
            premiere = _sans_balises(contenu.split("</p>")[0])
            if not premiere or premiere in trouves:
                continue
            position = objet.get("position") or {}
            trouves[premiere] = Pose(
                identifiant=str(objet.get("id", "")),
                x=int(position.get("x", 0) or 0),
                y=int(position.get("y", 0) or 0),
                de_l_outil=bool(_PROVENANCE.search(_sans_balises(contenu))),
            )
        curseur = str(reponse.get("cursor", ""))
        if not curseur:
            return trouves


def apports_des_autres(tableau: str) -> list[str]:
    """Ce que des humains ont écrit sur la carte, et que l'outil n'a pas posé.

    À donner au rédacteur au début de la réunion suivante : c'est le moment où
    cette information vaut le plus, et c'est ce qui fait qu'une carte partagée
    sert à quelque chose plutôt que d'être un affichage.
    """
    return [
        libelle for libelle, pose in poses_presentes(tableau).items()
        if not pose.de_l_outil
    ]


def libelles_presents(tableau: str) -> list[str]:
    """Les libellés déjà sur le tableau, dans leur forme d'origine.

    Donnés au rédacteur pour qu'il les reprenne mot pour mot au lieu de
    reformuler — une reformulation ouvre une branche de plus.
    """
    return list(poses_presentes(tableau))


#: Ce qu'on pose à côté d'un point pour dire qu'il est acté, sans y toucher.
MARQUE_ACTE = "acté"

#: Où la pastille se place par rapport au point qu'elle marque. Constant, parce
#: que c'est cette constance qui permet de reconnaître une pastille déjà posée :
#: elle ne porte pas le texte de son point, seule sa place le désigne.
DECALAGE_PASTILLE = (150, -60)

#: Écart toléré en retrouvant une pastille. Quelqu'un peut l'avoir déplacée de
#: quelques pixels sans vouloir la détacher de son point.
TOLERANCE_PASTILLE = 40


def _pastilles_posees(tableau: str) -> set[tuple[int, int]]:
    """Les positions de toutes les pastilles « acté » du tableau."""
    positions: set[tuple[int, int]] = set()
    curseur = ""
    while True:
        parametres = {"limit": "50"}
        if curseur:
            parametres["cursor"] = curseur
        try:
            reponse = _appeler(
                f"/boards/{urllib.parse.quote(tableau, safe='')}/shapes"
                f"?{urllib.parse.urlencode(parametres)}"
            )
        except MiroRefuse:
            return positions
        for forme in reponse.get("data", []):
            contenu = _sans_balises((forme.get("data") or {}).get("content", ""))
            if contenu.strip().casefold() != MARQUE_ACTE:
                continue
            position = forme.get("position") or {}
            positions.add((
                int(position.get("x", 0) or 0), int(position.get("y", 0) or 0)
            ))
        curseur = str(reponse.get("cursor", ""))
        if not curseur:
            return positions


def marquer_actes(
    tableau: str, textes: list[str], reunion: str = ""
) -> tuple[str, ...]:
    """Pose une pastille « acté » à côté des points tranchés. Rend les marqués.

    À côté et non dessus : un point déjà sur la carte n'est jamais modifié,
    parce qu'un humain a peut-être déplacé ou réécrit cet objet et que l'API ne
    dit pas qui l'a touché. Mais sans cette pastille, la couleur devenait fausse
    avec le temps — une piste retenue restait jaune indéfiniment.
    """
    from greffier.domaine.carte import meme_point

    _garder(tableau)
    presents = poses_presentes(tableau)
    # Les pastilles déjà là, avec **toutes** leurs positions. Elles ne portent
    # pas le texte du point qu'elles marquent, donc seule leur place les
    # rattache — et `poses_presentes` ne pouvait pas servir : il indexe par
    # libellé, or toutes les pastilles s'appellent « acté », si bien qu'une
    # seule position était retenue et qu'une pastille de plus était posée à
    # chaque publication.
    deja_marques = _pastilles_posees(tableau)
    marques: list[str] = []
    for texte in textes:
        pose = next(
            (p for libelle, p in presents.items() if meme_point(libelle, texte)),
            None,
        )
        if pose is None:
            continue
        attendue = (pose.x + DECALAGE_PASTILLE[0], pose.y + DECALAGE_PASTILLE[1])
        if any(
            abs(x - attendue[0]) <= TOLERANCE_PASTILLE
            and abs(y - attendue[1]) <= TOLERANCE_PASTILLE
            for x, y in deja_marques
        ):
            continue
        try:
            _appeler(
                f"/boards/{urllib.parse.quote(tableau, safe='')}/shapes",
                "POST",
                {
                    "data": {"shape": "round_rectangle",
                             "content": f"<p>{_echapper(MARQUE_ACTE)}</p>"},
                    "style": {"fillColor": "#2e6b52", "color": "#ffffff",
                              "fontSize": "12"},
                    # À droite du point, hors de son emprise : la géométrie
                    # rendue par l'API n'est pas fiable, donc on s'écarte
                    # largement plutôt que de calculer au pixel.
                    "position": {"x": attendue[0], "y": attendue[1],
                                 "origin": "center"},
                    "geometry": {"width": 70, "height": 34},
                },
            )
            marques.append(texte)
        except MiroRefuse:
            continue
    return tuple(marques)


def textes_presents(tableau: str) -> set[str]:
    """Les clefs de comparaison des points déjà sur le tableau.

    Calculées sur le **seul libellé**, comme celles de la carte. La version
    précédente les calculait sur tout le contenu de l'objet — libellé, état et
    réunion d'origine — de sorte qu'elles portaient « discussion » et
    « 2026-09-09_10h05_reunion » et ne pouvaient jamais correspondre. Résultat :
    chaque publication reposait les treize mêmes points, la carte doublait à
    chaque passage, et le compte annonçait « 0 déjà présent ».

    Inclut ce qu'un humain a posé à la main : c'est voulu — un point déjà écrit
    par quelqu'un ne doit pas se voir doublé par l'outil.
    """
    from greffier.domaine.carte import clef

    return {clef(libelle) for libelle in libelles_presents(tableau)}


def _sans_balises(html: str) -> str:
    """Miro rend le contenu en HTML léger ; on ne compare que le texte."""
    import re

    return re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").strip()


def publier(carte: Carte, tableau: str, reunion: str = "") -> Ecrit:
    """Pose sur le tableau les nœuds qui n'y sont pas encore.

    Ne supprime rien, ne modifie rien. Un nœud déjà présent est laissé tel
    quel, même si son état a changé dans la carte : changer un objet qu'un
    humain a peut-être déplacé ou réécrit demanderait de savoir qui l'a touché,
    ce que l'API ne dit pas.
    """
    from greffier.domaine.carte import meme_point

    _garder(tableau)
    # Les objets déjà là, avec leur identifiant : ils servent à comparer **et**
    # à rattacher les points nouveaux à un parent qui existait avant.
    presents = poses_presentes(tableau)
    identifiants: dict[str, str] = {
        libelle: pose.identifiant for libelle, pose in presents.items()
        if pose.identifiant
    }
    poses: list[str] = []
    connus: list[str] = []

    for place in disposer(carte):
        # À la reformulation près : c'est ce qui empêche la carte de doubler.
        if any(meme_point(libelle, place.noeud.texte) for libelle in presents):
            connus.append(place.noeud.texte)
            continue
        from greffier.domaine.carte import SANS_ETAT

        couleur = (
            COULEUR_SUJET if place.noeud.genre in SANS_ETAT
            else COULEURS.get(place.noeud.etat, "light_yellow")
        )
        corps = {
            "data": {"content": _en_html(place.noeud, reunion),
                     "shape": "square"},
            "style": {"fillColor": couleur},
            "position": {"x": place.x, "y": place.y, "origin": "center"},
        }
        reponse = _appeler(
            f"/boards/{urllib.parse.quote(tableau, safe='')}/sticky_notes",
            "POST", corps,
        )
        identifiant = str(reponse.get("id", ""))
        if identifiant:
            identifiants[place.noeud.texte] = identifiant
            poses.append(place.noeud.texte)

    liens, manques = _relier(tableau, carte, identifiants)
    return Ecrit(tableau, tuple(poses), tuple(connus), liens=liens, liens_manques=manques)


def _en_html(noeud: Noeud, reunion: str) -> str:
    """Le texte du pense-bête : le point, puis d'où il vient.

    La provenance en petit dessous : « d'où vient cette branche » est la
    première question de qui découvre une carte, et y répondre dans l'objet
    évite d'avoir à ouvrir un compte rendu pour le savoir.
    """
    from greffier.domaine.carte import SANS_ETAT

    lignes = [f"<p>{_echapper(noeud.texte)}</p>"]
    # La racine ne porte pas d'état : « Oasis — en discussion » ferait dire à la
    # carte que le sujet lui-même est en débat.
    if noeud.genre not in SANS_ETAT and noeud.etat is not Etat.ACTE:
        lignes.append(f"<p><i>{noeud.etat}</i></p>")
    origine = reunion or (noeud.reunions[-1] if noeud.reunions else "")
    if origine:
        lignes.append(f"<p><i>{_echapper(origine)}</i></p>")
    return "".join(lignes)


def _liens_existants(tableau: str) -> set[tuple[str, str]]:
    """Les couples déjà reliés, pour ne pas superposer les traits."""
    couples: set[tuple[str, str]] = set()
    curseur = ""
    while True:
        parametres = {"limit": "50"}
        if curseur:
            parametres["cursor"] = curseur
        try:
            reponse = _appeler(
                f"/boards/{urllib.parse.quote(tableau, safe='')}/connectors"
                f"?{urllib.parse.urlencode(parametres)}"
            )
        except MiroRefuse:
            return couples
        for lien in reponse.get("data", []):
            depart = str((lien.get("startItem") or {}).get("id", ""))
            arrivee = str((lien.get("endItem") or {}).get("id", ""))
            if depart and arrivee:
                couples.add((depart, arrivee))
        curseur = str(reponse.get("cursor", ""))
        if not curseur:
            return couples


def _echapper(texte: str) -> str:
    return (texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _relier(
    tableau: str, carte: Carte, identifiants: dict[str, str]
) -> tuple[int, int]:
    """Trace les liens entre les nœuds qu'on vient de poser. Rend (tracés, échoués).

    Seulement ceux dont **les deux** extrémités viennent d'être créées : relier
    à un objet qu'on n'a pas posé supposerait de l'avoir retrouvé, et un lien
    tracé vers le mauvais objet est plus trompeur qu'un lien absent.

    Les identifiants partent en **nombres** et non en chaînes : l'API les refuse
    autrement (« expected of type [Number] »). Une première carte a été publiée
    sans un seul trait pour cette raison, et l'échec était avalé — d'où le
    compte rendu ici plutôt qu'un « continue » muet.
    """
    traces = 0
    manques = 0
    deja_reliees = _liens_existants(tableau)
    for place in disposer(carte):
        depart = identifiants.get(place.parent)
        arrivee = identifiants.get(place.noeud.texte)
        if not place.parent or depart is None or arrivee is None:
            continue
        # Un lien déjà tracé ne se retrace pas : republier une carte y
        # empilerait des traits superposés à chaque passage.
        if (depart, arrivee) in deja_reliees:
            continue
        try:
            _appeler(
                f"/boards/{urllib.parse.quote(tableau, safe='')}/connectors",
                "POST",
                {"startItem": {"id": int(depart)}, "endItem": {"id": int(arrivee)},
                 "style": {"strokeStyle": "normal", "strokeWidth": "2"}},
            )
            traces += 1
        except (MiroRefuse, ValueError):
            # Un lien manquant laisse la carte lisible ; interrompre la
            # publication à cause d'un trait la laisserait à moitié faite. Mais
            # on le compte, pour que l'appelant puisse le dire.
            manques += 1
    return (traces, manques)
