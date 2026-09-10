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

from greffier.domain.board import Carte, Noeud, RecorderState
from greffier.domain.layout import disposer

BASE = "https://api.miro.com/v2"

INTERDITS = frozenset({"uXjVH5WwzTI="})

PREFIXE = "Greffier"

COLOURS = {
    RecorderState.ACTE: "light_green",
    RecorderState.EN_DISCUSSION: "light_yellow",
    RecorderState.DEPASSE: "gray",
}

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
    liens: int = 0
    liens_manques: int = 0

def token() -> str:
    """Le jeton d'accès, depuis l'environnement ou un fichier désigné par lui.

    Jamais un chemin en dur : le jeton d'un poste n'a pas à être deviné par le
    code, et un outil public ne doit pas aller chercher dans le dossier de
    travail d'un projet.
    """
    live = os.environ.get("GREFFIER_MIRO_JETON", "").strip()
    if live:
        return live
    file = os.environ.get("GREFFIER_MIRO_JETON_FICHIER", "").strip()
    if file:
        path = Path(file).expanduser()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    raise MiroRefuse(
        "aucun jeton Miro : pose « GREFFIER_MIRO_JETON », ou "
        "« GREFFIER_MIRO_JETON_FICHIER » vers le fichier qui le contient"
    )

def _appeler(path: str, methode: str = "GET",
             corps: dict[str, Any] | None = None) -> dict[str, Any]:
    requete = urllib.request.Request(
        f"{BASE}{path}",
        method=methode,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=20) as response:
            brut = response.read().decode("utf-8")
            return json.loads(brut) if brut.strip() else {}
    except urllib.error.HTTPError as trouble:
        detail = trouble.read().decode("utf-8", "replace")[:200]
        raise MiroRefuse(f"Miro a répondu {trouble.code} : {detail}") from trouble
    except (urllib.error.URLError, TimeoutError) as trouble:
        raise MiroRefuse(f"Miro est injoignable : {trouble}") from trouble

def _keep(tableau: str) -> str:
    """Refuse tout de suite un tableau interdit."""
    if tableau in INTERDITS:
        raise MiroRefuse(
            f"le tableau {tableau} est sur la liste des tableaux interdits : "
            "cet outil n'y écrit jamais"
        )
    return tableau

def creer_le_tableau(subject: str) -> tuple[str, str]:
    """Crée le tableau d'un sujet. Rend son identifiant et son adresse."""
    response = _appeler("/boards", "POST", {
        "name": f"{PREFIXE} — {subject}",
        "description": (
            f"Carte du sujet « {subject} », tenue par Greffier au fil des réunions. "
            "Jaune : en discussion. Vert : acté. Gris : dépassé. "
            "Ce qui est ajouté à la main est conservé."
        ),
    })
    identifier = str(response.get("id", ""))
    if not identifier:
        raise MiroRefuse("Miro n'a pas rendu d'identifiant de tableau")
    return (identifier, str(response.get("viewLink", "")))

@dataclass(frozen=True, slots=True)
class Pose:
    """Un point déjà sur le tableau, et ce qu'on en sait."""

    identifier: str
    x: int
    y: int
    de_l_outil: bool = False

def objets_presents(tableau: str) -> dict[str, str]:
    """Les points déjà sur le tableau : libellé en clair → identifiant d'objet.

    L'identifiant sert à **rattacher** un point ajouté plus tard à un parent qui
    existait déjà. Sans lui, les branches des publications suivantes flottaient
    sans lien : la première passe traçait douze traits, la seconde aucun, et la
    carte se dégradait à mesure qu'on la complétait — exactement ce qu'elle est
    censée éviter.
    """
    _keep(tableau)
    trouves: dict[str, str] = {}
    cursor = ""
    while True:
        parametres = {"limit": "50"}
        if cursor:
            parametres["cursor"] = cursor
        response = _appeler(
            f"/boards/{urllib.parse.quote(tableau, safe='')}/items"
            f"?{urllib.parse.urlencode(parametres)}"
        )
        for objet in response.get("data", []):
            content = (objet.get("data") or {}).get("content", "")
            if not content:
                continue
            premiere = _sans_balises(content.split("</p>")[0])
            if premiere:
                trouves.setdefault(premiere, str(objet.get("id", "")))
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return trouves

_PROVENANCE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}h\d{2}")

def placements_present(tableau: str) -> dict[str, Pose]:
    """Les points du tableau, avec leur place et leur origine.

    L'origine sert à deux choses : poser une pastille à côté d'un point sans le
    modifier, et savoir ce qu'un humain a ajouté depuis la dernière réunion —
    c'est tout l'intérêt d'une carte partagée, et cela n'était jamais relu.
    """
    _keep(tableau)
    trouves: dict[str, Pose] = {}
    cursor = ""
    while True:
        parametres = {"limit": "50"}
        if cursor:
            parametres["cursor"] = cursor
        response = _appeler(
            f"/boards/{urllib.parse.quote(tableau, safe='')}/items"
            f"?{urllib.parse.urlencode(parametres)}"
        )
        for objet in response.get("data", []):
            content = (objet.get("data") or {}).get("content", "")
            if not content:
                continue
            premiere = _sans_balises(content.split("</p>")[0])
            if not premiere or premiere in trouves:
                continue
            position = objet.get("position") or {}
            trouves[premiere] = Pose(
                identifier=str(objet.get("id", "")),
                x=int(position.get("x", 0) or 0),
                y=int(position.get("y", 0) or 0),
                de_l_outil=bool(_PROVENANCE.search(_sans_balises(content))),
            )
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return trouves

def contributions_of_others(tableau: str) -> list[str]:
    """Ce que des humains ont écrit sur la carte, et que l'outil n'a pas posé.

    À donner au rédacteur au début de la réunion suivante : c'est le moment où
    cette information vaut le plus, et c'est ce qui fait qu'une carte partagée
    sert à quelque chose plutôt que d'être un affichage.
    """
    return [
        label_text for label_text, pose in placements_present(tableau).items()
        if not pose.de_l_outil
    ]

def labels_present(tableau: str) -> list[str]:
    """Les libellés déjà sur le tableau, dans leur forme d'origine.

    Donnés au rédacteur pour qu'il les reprenne mot pour mot au lieu de
    reformuler — une reformulation ouvre une branche de plus.
    """
    return list(placements_present(tableau))

MARQUE_ACTE = "acté"

DECALAGE_PASTILLE = (150, -60)

TOLERANCE_PASTILLE = 40

def _dots_placed(tableau: str) -> set[tuple[int, int]]:
    """Les positions de toutes les pastilles « acté » du tableau."""
    positions: set[tuple[int, int]] = set()
    cursor = ""
    while True:
        parametres = {"limit": "50"}
        if cursor:
            parametres["cursor"] = cursor
        try:
            response = _appeler(
                f"/boards/{urllib.parse.quote(tableau, safe='')}/shapes"
                f"?{urllib.parse.urlencode(parametres)}"
            )
        except MiroRefuse:
            return positions
        for forme in response.get("data", []):
            content = _sans_balises((forme.get("data") or {}).get("content", ""))
            if content.strip().casefold() != MARQUE_ACTE:
                continue
            position = forme.get("position") or {}
            positions.add((
                int(position.get("x", 0) or 0), int(position.get("y", 0) or 0)
            ))
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return positions

def mark_actions(
    tableau: str, texts: list[str], meeting: str = ""
) -> tuple[str, ...]:
    """Pose une pastille « acté » à côté des points tranchés. Rend les marqués.

    À côté et non dessus : un point déjà sur la carte n'est jamais modifié,
    parce qu'un humain a peut-être déplacé ou réécrit cet objet et que l'API ne
    dit pas qui l'a touché. Mais sans cette pastille, la couleur devenait fausse
    avec le temps — une piste retenue restait jaune indéfiniment.
    """
    from greffier.domain.board import same_point

    _keep(tableau)
    present_line = placements_present(tableau)
    deja_marques = _dots_placed(tableau)
    marques: list[str] = []
    for text in texts:
        pose = next(
            (p for label_text, p in present_line.items() if same_point(label_text, text)),
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
                    "position": {"x": attendue[0], "y": attendue[1],
                                 "origin": "center"},
                    "geometry": {"width": 70, "height": 34},
                },
            )
            marques.append(text)
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
    from greffier.domain.board import key

    return {key(label_text) for label_text in labels_present(tableau)}

def _sans_balises(html: str) -> str:
    """Miro rend le contenu en HTML léger ; on ne compare que le texte."""
    import re

    return re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").strip()

def publish(board: Carte, tableau: str, meeting: str = "") -> Ecrit:
    """Pose sur le tableau les nœuds qui n'y sont pas encore.

    Ne supprime rien, ne modifie rien. Un nœud déjà présent est laissé tel
    quel, même si son état a changé dans la carte : changer un objet qu'un
    humain a peut-être déplacé ou réécrit demanderait de savoir qui l'a touché,
    ce que l'API ne dit pas.
    """
    from greffier.domain.board import same_point

    _keep(tableau)
    present_line = placements_present(tableau)
    identifiers: dict[str, str] = {
        label_text: pose.identifier for label_text, pose in present_line.items()
        if pose.identifier
    }
    poses: list[str] = []
    known: list[str] = []

    for place in disposer(board):
        if any(same_point(label_text, place.noeud.text) for label_text in present_line):
            known.append(place.noeud.text)
            continue
        from greffier.domain.board import SANS_ETAT

        colour = (
            COULEUR_SUJET if place.noeud.kind in SANS_ETAT
            else COLOURS.get(place.noeud.state, "light_yellow")
        )
        corps = {
            "data": {"content": _as_html(place.noeud, meeting),
                     "shape": "square"},
            "style": {"fillColor": colour},
            "position": {"x": place.x, "y": place.y, "origin": "center"},
        }
        response = _appeler(
            f"/boards/{urllib.parse.quote(tableau, safe='')}/sticky_notes",
            "POST", corps,
        )
        identifier = str(response.get("id", ""))
        if identifier:
            identifiers[place.noeud.text] = identifier
            poses.append(place.noeud.text)

    liens, manques = _relier(tableau, board, identifiers)
    return Ecrit(tableau, tuple(poses), tuple(known), liens=liens, liens_manques=manques)

def _as_html(noeud: Noeud, meeting: str) -> str:
    """Le texte du pense-bête : le point, puis d'où il vient.

    La provenance en petit dessous : « d'où vient cette branche » est la
    première question de qui découvre une carte, et y répondre dans l'objet
    évite d'avoir à ouvrir un compte rendu pour le savoir.
    """
    from greffier.domain.board import SANS_ETAT

    lines = [f"<p>{_echapper(noeud.text)}</p>"]
    if noeud.kind not in SANS_ETAT and noeud.state is not RecorderState.ACTE:
        lines.append(f"<p><i>{noeud.state}</i></p>")
    origine = meeting or (noeud.meetings[-1] if noeud.meetings else "")
    if origine:
        lines.append(f"<p><i>{_echapper(origine)}</i></p>")
    return "".join(lines)

def _liens_existants(tableau: str) -> set[tuple[str, str]]:
    """Les couples déjà reliés, pour ne pas superposer les traits."""
    couples: set[tuple[str, str]] = set()
    cursor = ""
    while True:
        parametres = {"limit": "50"}
        if cursor:
            parametres["cursor"] = cursor
        try:
            response = _appeler(
                f"/boards/{urllib.parse.quote(tableau, safe='')}/connectors"
                f"?{urllib.parse.urlencode(parametres)}"
            )
        except MiroRefuse:
            return couples
        for lien in response.get("data", []):
            depart = str((lien.get("startItem") or {}).get("id", ""))
            arrivee = str((lien.get("endItem") or {}).get("id", ""))
            if depart and arrivee:
                couples.add((depart, arrivee))
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return couples

def _echapper(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def _relier(
    tableau: str, board: Carte, identifiers: dict[str, str]
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
    for place in disposer(board):
        depart = identifiers.get(place.parent)
        arrivee = identifiers.get(place.noeud.text)
        if not place.parent or depart is None or arrivee is None:
            continue
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
            manques += 1
    return (traces, manques)
