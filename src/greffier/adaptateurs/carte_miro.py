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


class MiroRefuse(RuntimeError):
    """L'appel n'a pas eu lieu, et pour une raison présentable."""


@dataclass(frozen=True, slots=True)
class Ecrit:
    """Ce qu'une publication a fait. Rien n'est jamais supprimé."""

    tableau: str
    poses: tuple[str, ...] = ()
    deja: tuple[str, ...] = ()
    adresse: str = ""


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


def textes_presents(tableau: str) -> set[str]:
    """Les libellés déjà sur le tableau, quelle que soit leur origine.

    Sert à n'écrire que ce qui manque. Inclut ce qu'un humain a posé à la main :
    c'est voulu — un point déjà écrit par quelqu'un ne doit pas se voir doublé
    par l'outil.
    """
    from greffier.domaine.carte import clef

    _garder(tableau)
    vus: set[str] = set()
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
            if contenu:
                vus.add(clef(_sans_balises(contenu)))
        curseur = str(reponse.get("cursor", ""))
        if not curseur:
            return vus


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
    _garder(tableau)
    deja = textes_presents(tableau)
    poses: list[str] = []
    connus: list[str] = []
    identifiants: dict[str, str] = {}

    for place in disposer(carte):
        from greffier.domaine.carte import clef

        if clef(place.noeud.texte) in deja:
            connus.append(place.noeud.texte)
            continue
        corps = {
            "data": {"content": _en_html(place.noeud, reunion),
                     "shape": "square"},
            "style": {"fillColor": COULEURS.get(place.noeud.etat, "light_yellow")},
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

    _relier(tableau, carte, identifiants)
    return Ecrit(tableau, tuple(poses), tuple(connus))


def _en_html(noeud: Noeud, reunion: str) -> str:
    """Le texte du pense-bête : le point, puis d'où il vient.

    La provenance en petit dessous : « d'où vient cette branche » est la
    première question de qui découvre une carte, et y répondre dans l'objet
    évite d'avoir à ouvrir un compte rendu pour le savoir.
    """
    lignes = [f"<p>{_echapper(noeud.texte)}</p>"]
    marque = str(noeud.etat)
    if noeud.etat is not Etat.ACTE:
        lignes.append(f"<p><i>{marque}</i></p>")
    origine = reunion or (noeud.reunions[-1] if noeud.reunions else "")
    if origine:
        lignes.append(f"<p><i>{_echapper(origine)}</i></p>")
    return "".join(lignes)


def _echapper(texte: str) -> str:
    return (texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _relier(tableau: str, carte: Carte, identifiants: dict[str, str]) -> None:
    """Trace les liens entre les nœuds qu'on vient de poser.

    Seulement ceux dont **les deux** extrémités viennent d'être créées : relier
    à un objet qu'on n'a pas posé supposerait de l'avoir retrouvé, et un lien
    tracé vers le mauvais objet est plus trompeur qu'un lien absent.
    """
    for place in disposer(carte):
        depart = identifiants.get(place.parent)
        arrivee = identifiants.get(place.noeud.texte)
        if not place.parent or depart is None or arrivee is None:
            continue
        try:
            _appeler(
                f"/boards/{urllib.parse.quote(tableau, safe='')}/connectors",
                "POST",
                {"startItem": {"id": depart}, "endItem": {"id": arrivee},
                 "style": {"strokeStyle": "normal", "strokeWidth": "2"}},
            )
        except MiroRefuse:
            # Un lien manquant laisse la carte lisible ; interrompre la
            # publication à cause d'un trait la laisserait à moitié faite.
            continue
