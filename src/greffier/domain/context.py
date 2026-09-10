"""What the tool knows of the setting a meeting takes place in.

Acronyms, products, people: what no model can guess and what improves rare
proper nouns more than anything else.
"""

from __future__ import annotations

from dataclasses import dataclass

AMORCE_MAXIMUM = 850

_PREAMBULE = "Réunion de travail."

@dataclass(frozen=True, slots=True)
class Term:
    """A word the model cannot guess: acronym, product, proper noun."""

    ecriture: str
    sens: str = ""

    def __post_init__(self) -> None:
        if not self.ecriture.strip():
            raise ValueError("un terme sans écriture ne sert à rien")

    @property
    def gloss(self) -> str:
        """"OTP (one-time password)", or just "OTP" when the sense is unknown."""
        return f"{self.ecriture} ({self.sens})" if self.sens else self.ecriture

@dataclass(frozen=True, slots=True)
class Speaker_:
    """Someone whose name is spoken in meetings."""

    name: str
    role: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("un intervenant sans nom ne sert à rien")

    @property
    def gloss(self) -> str:
        return f"{self.name} ({self.role})" if self.role else self.name

@dataclass(frozen=True, slots=True)
class Context:
    """The glossary and the directory of a working setting."""

    termes: tuple[Term, ...] = ()
    intervenants: tuple[Speaker_, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.termes and not self.intervenants

    def join(self, autre: Context) -> Context:
        """This context, completed by another, which wins on equal names."""
        termes = {t.ecriture.casefold(): t for t in self.termes}
        termes.update({t.ecriture.casefold(): t for t in autre.termes})
        gens = {i.name.casefold(): i for i in self.intervenants}
        gens.update({i.name.casefold(): i for i in autre.intervenants})
        return Context(tuple(termes.values()), tuple(gens.values()))

    def prompt_seed(self) -> str:
        """The transcriber's seed: spellings, without their meaning."""
        words = [t.ecriture for t in self.termes] + [i.name for i in self.intervenants]
        retenus = _hold(words, AMORCE_MAXIMUM - len(_PREAMBULE) - len(" Vocabulaire : ."))
        if not retenus:
            return ""
        return f"{_PREAMBULE} Vocabulaire : " + ", ".join(retenus) + "."

    def ecartes(self) -> tuple[str, ...]:
        """The terms the seed could not carry, so that it can be said."""
        words = [t.ecriture for t in self.termes] + [i.name for i in self.intervenants]
        retenus = set(_hold(words, AMORCE_MAXIMUM - len(_PREAMBULE) - len(" Vocabulaire : .")))
        return tuple(m for m in words if m not in retenus)

    def header(self) -> str:
        """The glossary dictated to the writer, meanings included."""
        if self.empty:
            return ""
        lines = ["[Contexte du milieu de travail]"]
        if self.termes:
            lines.append(
                "Termes et sigles employés dans cette organisation, avec leur sens. "
                "Emploie ces écritures, y compris là où la transcription les a "
                "manifestement déformés. N'en cite que ceux dont il est question :"
            )
            lines += [f"- {t.gloss}" for t in self.termes]
        if self.intervenants:
            lines.append(
                "Personnes de cette organisation. N'attribue une position à "
                "quelqu'un que si la transcription le montre, jamais d'après son rôle :"
            )
            lines += [f"- {i.gloss}" for i in self.intervenants]
        return "\n".join(lines) + "\n\n"

def _hold(words: list[str], place: int) -> list[str]:
    """The first words that fit in the room available."""
    retenus: list[str] = []
    length = 0
    for mot in dict.fromkeys(m for m in words if m.strip()):
        ajout = len(mot) + (2 if retenus else 0)
        if length + ajout > place:
            continue
        retenus.append(mot)
        length += ajout
    return retenus
