"""Checks the source evidence behind the local writer's Markdown tables.

These checks catch extra participants, asserted roles without evidence and
named owners on collective statements. They do not validate every sentence
of a summary. A failed check must never turn into publishable minutes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from rapidfuzz.fuzz import token_set_ratio

_SPOKEN = re.compile(
    r"^\[([^\]\n]+)\]\s*\n\d{2,}:\d{2}(?::\d{2})?\s+"
    r"(.+?)(?=\n\[[^\]\n]+\]\s*\n\d{2,}:\d{2}|\Z)",
    re.MULTILINE | re.DOTALL,
)
_STOP = frozenset((
    "a", "an", "and", "au", "aux", "de", "des", "du", "en", "et", "la", "le", "les",
    "nous", "of", "on", "our", "the", "to", "un", "une", "we",
))
_UNCERTAIN = ("non precise", "a confirmer", "not specified", "unconfirmed", "unknown")
_PEOPLE = frozenset(("nom", "prenom", "intervenant", "participant", "name", "speaker"))
_ROLES = frozenset(("role", "fonction", "function"))
_OWNERS = frozenset(("qui", "responsable", "who", "owner"))
_GENERIC_OWNERS = ("collectif", "tous", "equipe", "team", "non attribue", "a definir", "unassigned")


def _fold(text: str) -> str:
    text = re.sub(r"[*_`]", "", text)
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    ).strip()


def _rows(text: str) -> Iterator[tuple[list[str], list[str]]]:
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            header = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(cell and set(cell) <= set("-: ") for cell in cells):
            continue
        if header is None:
            header = [_fold(cell) for cell in cells]
        elif len(cells) == len(header):
            yield header, cells


def _column(header: list[str], names: frozenset[str]) -> int | None:
    return next((index for index, label in enumerate(header) if label in names), None)


def _collective(source: str) -> list[str]:
    subjects = re.compile(r"\bon\s+\w+|\bnous\s+(?:ne\s+|n['’])?\w+ons\b|\bwe\s+\w+")
    return [
        folded[subject.start():]
        for sentence in re.split(r"(?<=[.!?])\s+", source)
        for folded in [_fold(sentence)]
        for subject in subjects.finditer(folded)
    ]


def _matches_collective(row: str, sentence: str) -> bool:
    shared = (set(re.findall(r"\w+", row)) & set(re.findall(r"\w+", sentence))) - _STOP
    return len(shared) >= 2 and token_set_ratio(row, sentence) >= 70


def _explicit_role(person: str, role: str, spoken: list[tuple[str, str]]) -> bool:
    article = r"(?:(?:le|la|un|une|the|a|an)\s+)?"
    position = article + re.escape(role) + r"\b"
    for speaker, body in spoken:
        folded = _fold(body)
        if speaker == person and re.search(r"\b(?:je suis|i am)\s+" + position, folded):
            return True
        subject = re.escape(person) + r"\s+(?:est|is)\s+" + position
        if re.search(r"\b" + subject, folded):
            return True
    return False


def violations(source: str, minutes: str) -> list[str]:
    spoken = [(_fold(name), text) for name, text in _SPOKEN.findall(source)]
    if not spoken:
        return []
    people = {name for name, _ in spoken}
    bodies = _fold(" ".join(text for _, text in spoken))
    collectives = [sentence for _, text in spoken for sentence in _collective(text)]
    issues: list[str] = []
    participants_seen = False
    for header, cells in _rows(minutes):
        person = _column(header, _PEOPLE)
        role = _column(header, _ROLES)
        owner = _column(header, _OWNERS)
        if person is not None:
            participants_seen = True
            named = _fold(cells[person])
            if named not in people:
                issues.append("Un participant est ajouté sans passage de parole dans la source.")
            if role is not None:
                described = _fold(cells[role])
                if (
                    described and not any(mark in described for mark in _UNCERTAIN)
                    and not _explicit_role(named, described, spoken)
                ):
                    issues.append("Un rôle déduit est présenté comme établi sans preuve.")
        if owner is not None:
            assigned = _fold(cells[owner])
            if assigned in people:
                row = _fold(" ".join(cells))
                if any(_matches_collective(row, sentence) for sentence in collectives):
                    issues.append("Une action collective est attribuée à une seule personne.")
            elif assigned and assigned not in bodies and assigned not in ("-", "?"):
                if not any(mark in assigned for mark in (*_UNCERTAIN, *_GENERIC_OWNERS)):
                    issues.append("Un responsable est ajouté sans mention dans la source.")
    if not participants_seen:
        issues.append("Le tableau des intervenants manque dans le compte rendu.")
    return list(dict.fromkeys(issues))
