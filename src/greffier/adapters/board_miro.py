"""Writing a subject's board on a Miro board, as native objects.

**Not in a mindmap widget.** The widget is a third-party app whose nodes the
REST API can neither create nor modify, leaving only the mouse — tried once and
it produced mixed-up texts and stray objects. The board is therefore made of
sticky notes and connectors, which the API can write *and read back*, and
reading back is what allows a board to be completed rather than duplicated.

Three guardrails, in the code rather than in a note: a list of forbidden
boards, writing only to a board the tool created or a human registered, and
reading before writing.
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

from greffier.domain.board import Board, Node, Standing
from greffier.domain.layout import disposer

BASE = "https://api.miro.com/v2"

INTERDITS = frozenset({"uXjVH5WwzTI="})

PREFIXE = "Greffier"

COLOURS = {
    Standing.AGREED: "light_green",
    Standing.UNDER_DISCUSSION: "light_yellow",
    Standing.OVERTAKEN: "gray",
}

COULEUR_SUJET = "light_blue"

class MiroRefused(RuntimeError):
    """The call did not happen, and for a reason worth showing."""

@dataclass(frozen=True, slots=True)
class Written:
    """What a publication did. Nothing is ever deleted."""

    tableau: str
    poses: tuple[str, ...] = ()
    deja: tuple[str, ...] = ()
    adresse: str = ""
    liens: int = 0
    liens_manques: int = 0

def token() -> str:
    """The access token, from the environment or the keychain."""
    live = os.environ.get("GREFFIER_MIRO_JETON", "").strip()
    if live:
        return live
    file = os.environ.get("GREFFIER_MIRO_JETON_FICHIER", "").strip()
    if file:
        path = Path(file).expanduser()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    raise MiroRefused(
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
        raise MiroRefused(f"Miro a répondu {trouble.code} : {detail}") from trouble
    except (urllib.error.URLError, TimeoutError) as trouble:
        raise MiroRefused(f"Miro est injoignable : {trouble}") from trouble

def _keep(tableau: str) -> str:
    """Refuses a forbidden board at once."""
    if tableau in INTERDITS:
        raise MiroRefused(
            f"le tableau {tableau} est sur la liste des tableaux interdits : "
            "cet outil n'y écrit jamais"
        )
    return tableau

def creer_le_tableau(subject: str) -> tuple[str, str]:
    """Creates a subject's board. Returns its identifier."""
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
        raise MiroRefused("Miro n'a pas rendu d'identifiant de tableau")
    return (identifier, str(response.get("viewLink", "")))

@dataclass(frozen=True, slots=True)
class Placement:
    """A point already on the board, and what can be done with it."""

    identifier: str
    x: int
    y: int
    de_l_outil: bool = False

def objets_presents(tableau: str) -> dict[str, str]:
    """The points already on the board: label and identifier."""
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

def placements_present(tableau: str) -> dict[str, Placement]:
    """The points of the board, with their place and their size."""
    _keep(tableau)
    trouves: dict[str, Placement] = {}
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
            trouves[premiere] = Placement(
                identifier=str(objet.get("id", "")),
                x=int(position.get("x", 0) or 0),
                y=int(position.get("y", 0) or 0),
                de_l_outil=bool(_PROVENANCE.search(_sans_balises(content))),
            )
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return trouves

def contributions_of_others(tableau: str) -> list[str]:
    """What humans wrote on the board, and the tool did not."""
    return [
        label_text for label_text, pose in placements_present(tableau).items()
        if not pose.de_l_outil
    ]

def labels_present(tableau: str) -> list[str]:
    """The labels already on the board, in their own wording."""
    return list(placements_present(tableau))

MARQUE_ACTE = "acté"

DECALAGE_PASTILLE = (150, -60)

TOLERANCE_PASTILLE = 40

def _dots_placed(tableau: str) -> set[tuple[int, int]]:
    """The positions of every "settled" dot."""
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
        except MiroRefused:
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
    """Places a "settled" dot next to the points that are settled."""
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
        except MiroRefused:
            continue
    return tuple(marques)

def textes_presents(tableau: str) -> set[str]:
    """The comparison keys of the points already on the board."""
    from greffier.domain.board import key

    return {key(label_text) for label_text in labels_present(tableau)}

def _sans_balises(html: str) -> str:
    """Miro returns content as light HTML; only the text is compared."""
    import re

    return re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").strip()

def publish(board: Board, tableau: str, meeting: str = "") -> Written:
    """Places on the board the nodes that are not on it yet."""
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
        from greffier.domain.board import WITHOUT_STANDING

        colour = (
            COULEUR_SUJET if place.noeud.kind in WITHOUT_STANDING
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
    return Written(tableau, tuple(poses), tuple(known), liens=liens, liens_manques=manques)

def _as_html(noeud: Node, meeting: str) -> str:
    """The sticky note's text: the point, then where it comes from."""
    from greffier.domain.board import WITHOUT_STANDING

    lines = [f"<p>{_echapper(noeud.text)}</p>"]
    if noeud.kind not in WITHOUT_STANDING and noeud.state is not Standing.AGREED:
        lines.append(f"<p><i>{noeud.state}</i></p>")
    origin = meeting or (noeud.meetings[-1] if noeud.meetings else "")
    if origin:
        lines.append(f"<p><i>{_echapper(origin)}</i></p>")
    return "".join(lines)

def _liens_existants(tableau: str) -> set[tuple[str, str]]:
    """The pairs already connected, so as not to draw twice."""
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
        except MiroRefused:
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
    tableau: str, board: Board, identifiers: dict[str, str]
) -> tuple[int, int]:
    """Draws the links between the nodes just placed."""
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
        except (MiroRefused, ValueError):
            manques += 1
    return (traces, manques)
