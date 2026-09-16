"""Writing a subject's board on a Miro board, as native objects.

**Not in a mindmap widget.** The widget is a third-party app whose nodes the
REST API can neither create nor modify, leaving only the mouse, tried once and
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
from greffier.domain.layout import lay_out

BASE = "https://api.miro.com/v2"

FORBIDDEN = frozenset({"uXjVH5WwzTI="})

PREFIX = "Greffier"

COLOURS = {
    Standing.AGREED: "light_green",
    Standing.UNDER_DISCUSSION: "light_yellow",
    Standing.OVERTAKEN: "gray",
}

SUBJECT_COLOUR = "light_blue"

class MiroRefused(RuntimeError):
    """The call did not happen, and for a reason worth showing."""

@dataclass(frozen=True, slots=True)
class Written:
    """What a publication did. Nothing is ever deleted."""

    board_id: str
    poses: tuple[str, ...] = ()
    already: tuple[str, ...] = ()
    address: str = ""
    liens: int = 0
    links_missed: int = 0

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

def _call(path: str, http_method: str = "GET",
             corps: dict[str, Any] | None = None) -> dict[str, Any]:
    the_request = urllib.request.Request(
        f"{BASE}{path}",
        method=http_method,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(the_request, timeout=20) as response:
            brut = response.read().decode("utf-8")
            return json.loads(brut) if brut.strip() else {}
    except urllib.error.HTTPError as trouble:
        detail = trouble.read().decode("utf-8", "replace")[:200]
        raise MiroRefused(f"Miro a répondu {trouble.code} : {detail}") from trouble
    except (urllib.error.URLError, TimeoutError) as trouble:
        raise MiroRefused(f"Miro est injoignable : {trouble}") from trouble

def _keep(board_id: str) -> str:
    """Refuses a forbidden board at once."""
    if board_id in FORBIDDEN:
        raise MiroRefused(
            f"le tableau {board_id} est sur la liste des tableaux interdits : "
            "cet outil n'y écrit jamais"
        )
    return board_id

def create_the_board(subject: str) -> tuple[str, str]:
    """Creates a subject's board. Returns its identifier."""
    response = _call("/boards", "POST", {
        "name": f"{PREFIX} : {subject}",
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
    of_the_tool: bool = False

def objects_present(board_id: str) -> dict[str, str]:
    """The points already on the board: label and identifier."""
    _keep(board_id)
    found: dict[str, str] = {}
    cursor = ""
    while True:
        parameters = {"limit": "50"}
        if cursor:
            parameters["cursor"] = cursor
        response = _call(
            f"/boards/{urllib.parse.quote(board_id, safe='')}/items"
            f"?{urllib.parse.urlencode(parameters)}"
        )
        for subject_line in response.get("data", []):
            content = (subject_line.get("data") or {}).get("content", "")
            if not content:
                continue
            first_one = _without_markup(content.split("</p>")[0])
            if first_one:
                found.setdefault(first_one, str(subject_line.get("id", "")))
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return found

_PROVENANCE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}h\d{2}")

def placements_present(board_id: str) -> dict[str, Placement]:
    """The points of the board, with their place and their size."""
    _keep(board_id)
    found: dict[str, Placement] = {}
    cursor = ""
    while True:
        parameters = {"limit": "50"}
        if cursor:
            parameters["cursor"] = cursor
        response = _call(
            f"/boards/{urllib.parse.quote(board_id, safe='')}/items"
            f"?{urllib.parse.urlencode(parameters)}"
        )
        for subject_line in response.get("data", []):
            content = (subject_line.get("data") or {}).get("content", "")
            if not content:
                continue
            first_one = _without_markup(content.split("</p>")[0])
            if not first_one or first_one in found:
                continue
            position = subject_line.get("position") or {}
            found[first_one] = Placement(
                identifier=str(subject_line.get("id", "")),
                x=int(position.get("x", 0) or 0),
                y=int(position.get("y", 0) or 0),
                of_the_tool=bool(_PROVENANCE.search(_without_markup(content))),
            )
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return found

def contributions_of_others(board_id: str) -> list[str]:
    """What humans wrote on the board, and the tool did not."""
    return [
        label_text for label_text, pose in placements_present(board_id).items()
        if not pose.of_the_tool
    ]

def labels_present(board_id: str) -> list[str]:
    """The labels already on the board, in their own wording."""
    return list(placements_present(board_id))

SETTLED_MARK = "acté"

BADGE_OFFSET = (150, -60)

BADGE_TOLERANCE = 40

def _dots_placed(board_id: str) -> set[tuple[int, int]]:
    """The positions of every "settled" dot."""
    positions: set[tuple[int, int]] = set()
    cursor = ""
    while True:
        parameters = {"limit": "50"}
        if cursor:
            parameters["cursor"] = cursor
        try:
            response = _call(
                f"/boards/{urllib.parse.quote(board_id, safe='')}/shapes"
                f"?{urllib.parse.urlencode(parameters)}"
            )
        except MiroRefused:
            return positions
        for shape in response.get("data", []):
            content = _without_markup((shape.get("data") or {}).get("content", ""))
            if content.strip().casefold() != SETTLED_MARK:
                continue
            position = shape.get("position") or {}
            positions.add((
                int(position.get("x", 0) or 0), int(position.get("y", 0) or 0)
            ))
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return positions

def mark_actions(
    board_id: str, texts: list[str], meeting: str = ""
) -> tuple[str, ...]:
    """Places a "settled" dot next to the points that are settled."""
    from greffier.domain.board import same_point

    _keep(board_id)
    present_line = placements_present(board_id)
    already_marked = _dots_placed(board_id)
    marks: list[str] = []
    for text in texts:
        pose = next(
            (p for label_text, p in present_line.items() if same_point(label_text, text)),
            None,
        )
        if pose is None:
            continue
        expected = (pose.x + BADGE_OFFSET[0], pose.y + BADGE_OFFSET[1])
        if any(
            abs(x - expected[0]) <= BADGE_TOLERANCE
            and abs(y - expected[1]) <= BADGE_TOLERANCE
            for x, y in already_marked
        ):
            continue
        try:
            _call(
                f"/boards/{urllib.parse.quote(board_id, safe='')}/shapes",
                "POST",
                {
                    "data": {"shape": "round_rectangle",
                             "content": f"<p>{_escape(SETTLED_MARK)}</p>"},
                    "style": {"fillColor": "#2e6b52", "color": "#ffffff",
                              "fontSize": "12"},
                    "position": {"x": expected[0], "y": expected[1],
                                 "origin": "center"},
                    "geometry": {"width": 70, "height": 34},
                },
            )
            marks.append(text)
        except MiroRefused:
            continue
    return tuple(marks)

def texts_present(board_id: str) -> set[str]:
    """The comparison keys of the points already on the board."""
    from greffier.domain.board import key

    return {key(label_text) for label_text in labels_present(board_id)}

def _without_markup(html: str) -> str:
    """Miro returns content as light HTML; only the text is compared."""
    import re

    return re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").strip()

def publish(board: Board, board_id: str, meeting: str = "") -> Written:
    """Places on the board the nodes that are not on it yet."""
    from greffier.domain.board import same_point

    _keep(board_id)
    present_line = placements_present(board_id)
    identifiers: dict[str, str] = {
        label_text: pose.identifier for label_text, pose in present_line.items()
        if pose.identifier
    }
    poses: list[str] = []
    known: list[str] = []

    for place in lay_out(board):
        if any(same_point(label_text, place.node.text) for label_text in present_line):
            known.append(place.node.text)
            continue
        from greffier.domain.board import WITHOUT_STANDING

        colour = (
            SUBJECT_COLOUR if place.node.kind in WITHOUT_STANDING
            else COLOURS.get(place.node.state, "light_yellow")
        )
        corps = {
            "data": {"content": _as_html(place.node, meeting),
                     "shape": "square"},
            "style": {"fillColor": colour},
            "position": {"x": place.x, "y": place.y, "origin": "center"},
        }
        response = _call(
            f"/boards/{urllib.parse.quote(board_id, safe='')}/sticky_notes",
            "POST", corps,
        )
        identifier = str(response.get("id", ""))
        if identifier:
            identifiers[place.node.text] = identifier
            poses.append(place.node.text)

    liens, missing_ones = _link(board_id, board, identifiers)
    return Written(board_id, tuple(poses), tuple(known), liens=liens, links_missed=missing_ones)

def _as_html(node: Node, meeting: str) -> str:
    """The sticky note's text: the point, then where it comes from."""
    from greffier.domain.board import WITHOUT_STANDING

    lines = [f"<p>{_escape(node.text)}</p>"]
    if node.kind not in WITHOUT_STANDING and node.state is not Standing.AGREED:
        lines.append(f"<p><i>{node.state}</i></p>")
    origin = meeting or (node.meetings[-1] if node.meetings else "")
    if origin:
        lines.append(f"<p><i>{_escape(origin)}</i></p>")
    return "".join(lines)

def _existing_links(board_id: str) -> set[tuple[str, str]]:
    """The pairs already connected, so as not to draw twice."""
    couples: set[tuple[str, str]] = set()
    cursor = ""
    while True:
        parameters = {"limit": "50"}
        if cursor:
            parameters["cursor"] = cursor
        try:
            response = _call(
                f"/boards/{urllib.parse.quote(board_id, safe='')}/connectors"
                f"?{urllib.parse.urlencode(parameters)}"
            )
        except MiroRefused:
            return couples
        for lien in response.get("data", []):
            depart = str((lien.get("startItem") or {}).get("id", ""))
            arrival = str((lien.get("endItem") or {}).get("id", ""))
            if depart and arrival:
                couples.add((depart, arrival))
        cursor = str(response.get("cursor", ""))
        if not cursor:
            return couples

def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def _link(
    board_id: str, board: Board, identifiers: dict[str, str]
) -> tuple[int, int]:
    """Draws the links between the nodes just placed."""
    traces = 0
    missing_ones = 0
    already_linked = _existing_links(board_id)
    for place in lay_out(board):
        depart = identifiers.get(place.parent)
        arrival = identifiers.get(place.node.text)
        if not place.parent or depart is None or arrival is None:
            continue
        if (depart, arrival) in already_linked:
            continue
        try:
            _call(
                f"/boards/{urllib.parse.quote(board_id, safe='')}/connectors",
                "POST",
                {"startItem": {"id": int(depart)}, "endItem": {"id": int(arrival)},
                 "style": {"strokeStyle": "normal", "strokeWidth": "2"}},
            )
            traces += 1
        except (MiroRefused, ValueError):
            missing_ones += 1
    return (traces, missing_ones)
