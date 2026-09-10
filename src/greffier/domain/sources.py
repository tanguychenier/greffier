"""Les sources extérieures que l'outil a le droit de consulter, et d'écrire.

Un assistant qui peut lire un dépôt et créer un ticket est utile. Le même
assistant avec un jeton d'écriture et une phrase mal comprise crée un ticket que
personne n'a demandé, sur un projet que personne n'a nommé. La question n'est
donc pas « peut-il écrire » mais « où, et après quelle confirmation ».

Trois décisions portent ce module.

**Rien n'est atteignable qui ne soit inscrit.** Une source absente du registre
n'existe pas pour l'outil, quelle que soit la phrase tapée. Découvrir un projet
et s'y mettre n'arrive jamais — c'est ce qui rend le risque borné à ce qu'on a
listé soi-même.

**L'écriture est un droit séparé, et il se donne source par source.** Pouvoir
lire les tickets d'un projet n'autorise pas à en créer. Le défaut est la lecture
seule, parce que c'est le cas qui rend service sans rien risquer.

**Le jeton ne vit jamais ici.** Le registre nomme la variable d'environnement ou
l'entrée de trousseau qui le porte ; un secret dans un fichier de configuration
finit dans une sauvegarde, puis dans un dépôt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    GITLAB = "gitlab"
    JIRA = "jira"

class Right(StrEnum):
    LECTURE = "lecture"
    ECRITURE = "écriture"

@dataclass(frozen=True, slots=True)
class Source:
    """Une source extérieure inscrite, et ce qu'on peut en faire."""

    name: str
    kind: Kind
    adresse: str
    projet: str
    droit: Right = Right.LECTURE
    token: str = ""

    def __post_init__(self) -> None:
        for champ, value in (
            ("nom", self.name), ("adresse", self.adresse), ("projet", self.projet)
        ):
            if not value.strip():
                raise ValueError(f"une source sans {champ} ne sert à rien")
        if not self.adresse.startswith(("http://", "https://")):
            raise ValueError(
                f"« {self.adresse} » n'est pas une adresse : il faut http(s)://"
            )

    @property
    def can_write(self) -> bool:
        return self.droit is Right.ECRITURE

    def say(self) -> str:
        """Une ligne pour l'écran, qui montre la portée réelle."""
        return f"{self.name} — {self.kind} {self.projet} sur {self.adresse} ({self.droit})"

@dataclass
class Registry:
    """Les sources inscrites. Ce qui n'y est pas n'existe pas."""

    sources: list[Source]

    def by_name(self, name: str) -> Source | None:
        nu = name.strip().casefold()
        return next((s for s in self.sources if s.name.casefold() == nu), None)

    def of_gender(self, kind: Kind) -> list[Source]:
        return [s for s in self.sources if s.kind is kind]

    def recorded(self, kind: Kind | None = None) -> list[str]:
        """Les noms disponibles, pour pouvoir les proposer plutôt que deviner."""
        choisies = self.sources if kind is None else self.of_gender(kind)
        return [s.name for s in choisies]

    def allowed(self, name: str, ecriture: bool) -> tuple[bool, str]:
        """Le geste est-il permis ? Sinon, pourquoi — en termes utilisables.

        Le refus dit ce qui manque, parce qu'un « non » sans raison laisse
        croire à une panne là où il s'agit d'un réglage.
        """
        source = self.by_name(name)
        if source is None:
            connues = ", ".join(self.recorded()) or "aucune"
            return (False, f"« {name} » n'est pas inscrite. Sources connues : {connues}")
        if ecriture and not source.can_write:
            return (
                False,
                f"« {name} » est en lecture seule. Passe son droit à « écriture » "
                "dans le registre des sources si c'est voulu.",
            )
        if not source.token:
            return (False, f"« {name} » n'indique pas où trouver son jeton")
        return (True, "")
