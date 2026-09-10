"""Spotting, during the meeting, what calls for an action."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from greffier.domain.language import LanguageProfile
from greffier.domain.models import Utterance
from greffier.domain.profiles.neutral import NEUTRAL


class Origin(StrEnum):
    SPEECH = "parole"
    CLIPBOARD = "presse_papier"

class Kind(StrEnum):
    INSTRUCTION = "instruction"   # « Greffier, ouvre le ticket… »
    LINK = "lien"                 # une adresse collée
    DECISION = "decision"         # « on décide de… », « il faut que… »

_LINK = re.compile(r"https?://[^\s<>\"'()\[\]]{4,}")

@dataclass(frozen=True, slots=True)
class Suggestion:
    """Something to do, subject to approval."""

    kind: Kind
    text: str
    at_instant: float
    origin: Origin
    context: str = ""

    @property
    def key(self) -> str:
        """What identifies a duplicate."""
        return f"{self.kind}:{self.text.strip().lower()}"

def links_in(text: str) -> list[str]:
    """Addresses present in a text, deduplicated and in order."""
    vus: list[str] = []
    for trouve in _LINK.finditer(text):
        lien = trouve.group(0).rstrip(".,;:!?")
        if lien not in vus:
            vus.append(lien)
    return vus

def instruction_after(text: str, keyword: str) -> str | None:
    """What follows the wake word, when it is spoken."""
    motif = re.compile(rf"(?i:\b{re.escape(keyword)}\b)[\s,:—-]*(?P<suite>[^.?!]{{3,240}})")
    trouve = motif.search(text)
    if not trouve:
        return None
    suite = trouve.group("suite").strip()
    return suite or None

def decisions_in(text: str, profil: LanguageProfile) -> bool:
    """Does the passage announce a decision or a follow-up?"""
    return any(motif.search(text) for motif in profil.redaction.motifs_de_decision)

@dataclass
class WatchRules:
    """Gathers a meeting's suggestions, never acting on its own."""

    keyword: str = "greffier"
    profil: LanguageProfile = NEUTRAL
    propositions: list[Suggestion] = field(default_factory=list)
    _vues: set[str] = field(default_factory=set)

    def _add(self, proposition: Suggestion) -> bool:
        if proposition.key in self._vues:
            return False
        self._vues.add(proposition.key)
        self.propositions.append(proposition)
        return True

    def listen(self, utterances: list[Utterance]) -> list[Suggestion]:
        """Picks up what, in the speech, calls for an action."""
        nouvelles: list[Suggestion] = []
        for utterance in utterances:
            at_instant = utterance.span.start
            instruction = instruction_after(utterance.text, self.keyword)
            if instruction:
                candidate = Suggestion(
                    kind=Kind.INSTRUCTION, text=instruction, at_instant=at_instant,
                    origin=Origin.SPEECH, context=utterance.text.strip(),
                )
                if self._add(candidate):
                    nouvelles.append(candidate)
                continue
            if decisions_in(utterance.text, self.profil):
                candidate = Suggestion(
                    kind=Kind.DECISION, text=utterance.text.strip(), at_instant=at_instant,
                    origin=Origin.SPEECH, context="",
                )
                if self._add(candidate):
                    nouvelles.append(candidate)
        return nouvelles

    def paste(self, content: str, at_instant: float) -> list[Suggestion]:
        """Picks up the links passed through the clipboard."""
        nouvelles: list[Suggestion] = []
        for lien in links_in(content):
            candidate = Suggestion(
                kind=Kind.LINK, text=lien, at_instant=at_instant,
                origin=Origin.CLIPBOARD,
            )
            if self._add(candidate):
                nouvelles.append(candidate)
        return nouvelles

    def by_gender(self, kind: Kind) -> list[Suggestion]:
        return [p for p in self.propositions if p.kind is kind]
