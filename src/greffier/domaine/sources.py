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


class Genre(StrEnum):
    GITLAB = "gitlab"
    JIRA = "jira"


class Droit(StrEnum):
    #: Consulter seulement. Le défaut, et le cas qui rend service sans risque.
    LECTURE = "lecture"
    #: Consulter et modifier. Chaque écriture demande confirmation, quoi qu'il
    #: arrive : le droit ouvre la possibilité, il ne la rend pas automatique.
    ECRITURE = "écriture"


@dataclass(frozen=True, slots=True)
class Source:
    """Une source extérieure inscrite, et ce qu'on peut en faire."""

    nom: str
    genre: Genre
    #: L'adresse du service, sans chemin : « https://gitlab.example.fr ».
    adresse: str
    #: Le projet ou l'espace visé. Un registre qui autoriserait « tout GitLab »
    #: ne bornerait rien : c'est le projet nommé qui limite la portée.
    projet: str
    droit: Droit = Droit.LECTURE
    #: Où trouver le jeton : nom d'une variable d'environnement, ou entrée de
    #: trousseau préfixée « trousseau: ». Jamais le jeton lui-même.
    jeton: str = ""

    def __post_init__(self) -> None:
        for champ, valeur in (
            ("nom", self.nom), ("adresse", self.adresse), ("projet", self.projet)
        ):
            if not valeur.strip():
                raise ValueError(f"une source sans {champ} ne sert à rien")
        if not self.adresse.startswith(("http://", "https://")):
            raise ValueError(
                f"« {self.adresse} » n'est pas une adresse : il faut http(s)://"
            )

    @property
    def peut_ecrire(self) -> bool:
        return self.droit is Droit.ECRITURE

    def dire(self) -> str:
        """Une ligne pour l'écran, qui montre la portée réelle."""
        return f"{self.nom} — {self.genre} {self.projet} sur {self.adresse} ({self.droit})"


@dataclass
class Registre:
    """Les sources inscrites. Ce qui n'y est pas n'existe pas."""

    sources: list[Source]

    def par_nom(self, nom: str) -> Source | None:
        nu = nom.strip().casefold()
        return next((s for s in self.sources if s.nom.casefold() == nu), None)

    def du_genre(self, genre: Genre) -> list[Source]:
        return [s for s in self.sources if s.genre is genre]

    def inscrites(self, genre: Genre | None = None) -> list[str]:
        """Les noms disponibles, pour pouvoir les proposer plutôt que deviner."""
        choisies = self.sources if genre is None else self.du_genre(genre)
        return [s.nom for s in choisies]

    def autorise(self, nom: str, ecriture: bool) -> tuple[bool, str]:
        """Le geste est-il permis ? Sinon, pourquoi — en termes utilisables.

        Le refus dit ce qui manque, parce qu'un « non » sans raison laisse
        croire à une panne là où il s'agit d'un réglage.
        """
        source = self.par_nom(nom)
        if source is None:
            connues = ", ".join(self.inscrites()) or "aucune"
            return (False, f"« {nom} » n'est pas inscrite. Sources connues : {connues}")
        if ecriture and not source.peut_ecrire:
            return (
                False,
                f"« {nom} » est en lecture seule. Passe son droit à « écriture » "
                "dans le registre des sources si c'est voulu.",
            )
        if not source.jeton:
            return (False, f"« {nom} » n'indique pas où trouver son jeton")
        return (True, "")
