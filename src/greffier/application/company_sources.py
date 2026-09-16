"""What the registered outside sources hand the assistant during a meeting.

Read only, and only what is registered: the open tickets of a GitLab
project, the open requests of a Jira project, one line each, the way the
documents handed over for the meeting already are. A source whose token is
not there is named as such, with where the token goes, so that the assistant
can say it has no access and ask for it rather than guess a ticket.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from greffier.domain.sources import Kind, Registry, Source

#: Characters of material handed over in all, and per source.
AT_MOST = 6000
PER_SOURCE = 2500

#: The sources are read again this many seconds after the last reading: a
#: question every minute must not call GitLab every minute.
FRESH_FOR_S = 120.0

HEADER = "--- Sources d'entreprise inscrites ---"

#: What to say when the token is missing: where it goes, in the words of the
#: registry file, so that the assistant asks for the right gesture.
NO_TOKEN = (
    "aucun jeton disponible, l'accès n'est pas possible. Pour le donner : "
    "« jeton » dans le fichier des sources nomme une variable d'environnement "
    "ou une entrée du trousseau (« greffier sources » vérifie)."
)


@dataclass(frozen=True)
class Reading:
    """One source, read or not, and what it gave."""

    source: Source
    lines: tuple[str, ...] = ()
    trouble: str = ""

    @property
    def readable(self) -> bool:
        return not self.trouble

    def say(self) -> str:
        head = (f"Source « {self.source.name} » ({self.source.kind}, "
                f"projet {self.source.project})")
        if self.trouble:
            return f"{head} : {self.trouble}"
        if not self.lines:
            return f"{head} : rien d'ouvert."
        listed = "\n".join(f"- {line}" for line in self.lines)
        return f"{head}, {len(self.lines)} ouvert(s) :\n{listed}"


Lines = Callable[[Source, str], list[str]]


def read_all(
    registry: Registry,
    token_for: Callable[[Source], str],
    gitlab: Lines,
    jira: Lines,
) -> list[Reading]:
    """Every registered source, read where a token is there, named where not."""
    readings: list[Reading] = []
    for source in registry.sources:
        token = token_for(source)
        if not token:
            readings.append(Reading(source, trouble=NO_TOKEN))
            continue
        reader = gitlab if source.kind is Kind.GITLAB else jira
        try:
            readings.append(Reading(source, lines=tuple(reader(source, token))))
        except RuntimeError as refused:
            readings.append(Reading(source, trouble=f"lecture refusée : {refused}"))
    return readings


def material(readings: list[Reading], at_most: int = AT_MOST) -> str:
    """The text handed to the assistant, or nothing when no source is registered."""
    if not readings:
        return ""
    chunks: list[str] = []
    remaining = at_most
    for reading in readings:
        said = reading.say()[:PER_SOURCE]
        if remaining <= 0:
            break
        chunks.append(said[:remaining])
        remaining -= len(said)
    return f"{HEADER}\n" + "\n\n".join(chunks)


class Sources:
    """The sources' material, read again only once it has gone stale."""

    def __init__(self, read: Callable[[], list[Reading]], fresh_for: float = FRESH_FOR_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._read = read
        self._fresh_for = fresh_for
        self._clock = clock
        self._material = ""
        self._read_at: float | None = None

    def material(self) -> str:
        now = self._clock()
        if self._read_at is None or now - self._read_at >= self._fresh_for:
            try:
                self._material = material(self._read())
            except Exception:  # noqa: BLE001 -- a source that fails costs no answer
                self._material = ""
            self._read_at = now
        return self._material
