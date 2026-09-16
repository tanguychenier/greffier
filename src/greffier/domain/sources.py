"""The outside sources the tool may consult, and what it may do there.

What is not registered does not exist. Discovering a source and writing to it
never happens.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    GITLAB = "gitlab"
    JIRA = "jira"

class Right(StrEnum):
    READING = "lecture"
    WRITING = "écriture"

@dataclass(frozen=True, slots=True)
class Source:
    """A registered outside source, and what may be done with it."""

    name: str
    kind: Kind
    address: str
    project: str
    right: Right = Right.READING
    token: str = ""

    def __post_init__(self) -> None:
        for field, value in (
            ("nom", self.name), ("adresse", self.address), ("projet", self.project)
        ):
            if not value.strip():
                raise ValueError(f"une source sans {field} ne sert à rien")
        if not self.address.startswith(("http://", "https://")):
            raise ValueError(
                f"« {self.address} » n'est pas une adresse : il faut http(s)://"
            )

    @property
    def can_write(self) -> bool:
        return self.right is Right.WRITING

    def say(self) -> str:
        """One line for the screen, showing the real scope."""
        return f"{self.name}, {self.kind} {self.project} sur {self.address} ({self.right})"

@dataclass
class Registry:
    """The registered sources. What is not in here does not exist."""

    sources: list[Source]

    def by_name(self, name: str) -> Source | None:
        nu = name.strip().casefold()
        return next((s for s in self.sources if s.name.casefold() == nu), None)

    def of_gender(self, kind: Kind) -> list[Source]:
        return [s for s in self.sources if s.kind is kind]

    def recorded(self, kind: Kind | None = None) -> list[str]:
        """The names available, so they can be offered rather than guessed."""
        chosen_ones = self.sources if kind is None else self.of_gender(kind)
        return [s.name for s in chosen_ones]

    def allowed(self, name: str, spelling: bool) -> tuple[bool, str]:
        """Is the gesture permitted? If not, why, in the user's terms."""
        source = self.by_name(name)
        if source is None:
            known = ", ".join(self.recorded()) or "aucune"
            return (False, f"« {name} » n'est pas inscrite. Sources connues : {known}")
        if spelling and not source.can_write:
            return (
                False,
                f"« {name} » est en lecture seule. Passe son droit à « écriture » "
                "dans le registre des sources si c'est voulu.",
            )
        if not source.token:
            return (False, f"« {name} » n'indique pas où trouver son jeton")
        return (True, "")
