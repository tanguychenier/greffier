"""Handing the transcript to the tools that are not this one.

Everything Greffier produces, it produces for itself: a master file in its own
shape, minutes in Markdown, a readable transcript with no timings. Somebody who
wants to put subtitles on the recording of the meeting, or to count who spoke
for how long in a spreadsheet, has nothing to open -- and asking them to parse
a JSON file of our own design is asking them to write a program.

Three formats, because three tools:

- **SRT**, which every video player and every editing suite reads;
- **WebVTT**, the same thing for a browser, and the one format that carries the
  speaker as a tag rather than as text glued to the line;
- **CSV**, for the spreadsheet: one line per turn, times in seconds, so that
  « who talked, when, for how long » is a sum somebody can do themselves.

The subtitle formats do what subtitles require and the transcript does not: a
turn of forty words is unreadable on screen, so it is cut into blocks of at
most two lines of forty-two characters, and its duration is shared between them
in proportion to what each one carries.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from greffier.domain.models import Utterance

FORMATS = ("srt", "vtt", "csv")

LINE_WIDTH = 42
"""Characters per subtitle line.

The figure every subtitling guide gives, and the one that keeps two lines
readable at a glance on a video. Longer lines are not refused by players; they
are read by nobody.
"""

LINES_PER_BLOCK = 2

SHORTEST_BLOCK = 0.7
"""Seconds a block stays on screen, at the very least.

Cutting a long turn into blocks divides its duration; three blocks over two
seconds would flash. Below this the blocks overrun, which a player handles and
a reader forgives.
"""


@dataclass(frozen=True, slots=True)
class Block:
    """One subtitle: when, who, and the lines to show."""

    start: float
    end: float
    who: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def wrap(text: str, width: int = LINE_WIDTH) -> list[str]:
    """The text cut into lines of at most `width`, on word boundaries.

    A word longer than the line -- a URL, a reference -- is left whole rather
    than broken: broken, it is no longer the word that was said.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def blocks_of(
    utterances: Sequence[Utterance],
    names: dict[str, str] | None = None,
    width: int = LINE_WIDTH,
    name_in_text: bool = False,
) -> list[Block]:
    """Every utterance cut into what a screen can hold, in order.

    `name_in_text` writes « Sophie : » at the head of the turn **before** the
    cutting rather than after it, which settles two things at once: the name is
    counted in the width of the line it sits on, and it is written once per
    turn instead of once per block. A speaker who holds the floor for thirty
    seconds was otherwise introduced five times.
    """
    named = names or {}
    out: list[Block] = []
    precedent: str | None = None
    for utterance in sorted(utterances, key=lambda u: u.span.start):
        who = named.get(utterance.voice or "", "")
        text = utterance.text.strip()
        if name_in_text and who and who != precedent:
            text = f"{who} : {text}"
        precedent = who
        lines = wrap(text, width)
        if not lines:
            continue
        packages = [
            tuple(lines[rank:rank + LINES_PER_BLOCK])
            for rank in range(0, len(lines), LINES_PER_BLOCK)
        ]
        out += _shared_out(utterance, packages, who)
    return out


def _shared_out(
    utterance: Utterance, packages: list[tuple[str, ...]], who: str
) -> list[Block]:
    """The turn's seconds shared between its blocks, by what each one carries."""
    total = sum(len(" ".join(package)) for package in packages) or 1
    length = max(utterance.span.duration, SHORTEST_BLOCK * len(packages))
    out: list[Block] = []
    start = utterance.span.start
    for package in packages:
        part = len(" ".join(package)) / total
        end = start + length * part
        out.append(Block(start=start, end=end, who=who, lines=package))
        start = end
    return out


def _clock(seconds: float, comma: bool) -> str:
    """`00:01:02,345`, the only shape both formats agree on but for one mark."""
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    milli = round((seconds - whole) * 1000)
    if milli == 1000:                       # 1.9996 s rounds to 2 s, not to 1,1000
        whole, milli = whole + 1, 0
    hours, rest = divmod(whole, 3600)
    minutes, total_seconds = divmod(rest, 60)
    mark = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{total_seconds:02d}{mark}{milli:03d}"


def srt(utterances: Sequence[Utterance], names: dict[str, str] | None = None) -> str:
    """Subtitles as every player reads them, the speaker in front of the line."""
    chunks = []
    blocks = blocks_of(utterances, names, name_in_text=True)
    for rank, block in enumerate(blocks, start=1):
        chunks.append(
            f"{rank}\n{_clock(block.start, True)} --> {_clock(block.end, True)}\n"
            f"{block.text}\n"
        )
    return "\n".join(chunks)


def vtt(utterances: Sequence[Utterance], names: dict[str, str] | None = None) -> str:
    """The same, for a browser, with the speaker as a tag rather than as text.

    `<v Sophie>` is what lets a page style or filter by speaker; written into
    the line as « Sophie : », the name is just more characters to read.
    """
    chunks = ["WEBVTT\n"]
    for block in blocks_of(utterances, names):
        text = f"<v {block.who}>{block.text}" if block.who else block.text
        chunks.append(
            f"{_clock(block.start, False)} --> {_clock(block.end, False)}\n{text}\n"
        )
    return "\n".join(chunks)


def sheet(utterances: Sequence[Utterance], names: dict[str, str] | None = None) -> str:
    """One line per turn, for a spreadsheet.

    Semicolons, which is what a French spreadsheet expects from a `.csv`: with
    commas it opens as a single column and the person has to know about import
    dialogues to see anything at all.
    """
    named = names or {}
    out = io.StringIO()
    burner = csv.writer(out, delimiter=";", lineterminator="\n")
    burner.writerow(
        ["debut", "fin", "duree", "voix", "nom", "confiance", "texte"]
    )
    for utterance in sorted(utterances, key=lambda u: u.span.start):
        burner.writerow([
            f"{utterance.span.start:.2f}",
            f"{utterance.span.end:.2f}",
            f"{utterance.span.duration:.2f}",
            utterance.voice or "",
            named.get(utterance.voice or "", ""),
            "" if utterance.confidence is None else f"{utterance.confidence:.2f}",
            utterance.text.strip(),
        ])
    return out.getvalue()


def rendered(
    shape: str,
    utterances: Iterable[Utterance],
    names: dict[str, str] | None = None,
) -> str:
    """The transcript in the asked-for shape."""
    kept = list(utterances)
    if shape == "srt":
        return srt(kept, names)
    if shape == "vtt":
        return vtt(kept, names)
    if shape == "csv":
        return sheet(kept, names)
    raise ValueError(f"format inconnu : {shape} (connus : {', '.join(FORMATS)})")
