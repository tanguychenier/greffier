"""Le vocabulaire d'une réunion.

Rien ici ne connaît whisper, sherpa, ffmpeg ni Outlook : ce sont des objets de
domaine, en dataclasses de la bibliothèque standard. C'est ce qui permet de
tester les règles métier — attribution des noms, reconnaissance des voix — sans
audio, sans modèle et sans réseau.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class Phase(StrEnum):
    """États traversés par une réunion, de l'enregistrement à l'envoi."""

    REPOS = "repos"
    ENREGISTREMENT = "enregistrement"
    #: Enregistrement suspendu. Ce qui a déjà été capté est conservé, et
    #: reprendre ouvre simplement un morceau de plus : le mécanisme existe déjà
    #: pour les changements de matériel.
    PAUSE = "pause"
    FINALISATION = "finalisation"
    TRANSCRIPTION = "transcription"
    LOCUTEURS = "locuteurs"
    REDACTION = "redaction"
    ENVOI = "envoi"
    TERMINE = "termine"
    INTERROMPU = "interrompu"
    ECHEC = "echec"

    @property
    def en_cours(self) -> bool:
        return self in {
            Phase.ENREGISTREMENT, Phase.FINALISATION, Phase.TRANSCRIPTION,
            Phase.LOCUTEURS, Phase.REDACTION, Phase.ENVOI,
        }


class Source(StrEnum):
    """D'où vient le son d'une réplique.

    En visio, le micro et l'audio système arrivent sur deux canaux distincts :
    c'est une certitude matérielle, pas une déduction acoustique. On la garde,
    parce qu'elle est plus fiable que n'importe quelle empreinte vocale.
    """

    MICRO = "micro"          # la personne qui tient le Mac
    SYSTEME = "systeme"      # les participants distants
    INCONNUE = "inconnue"    # présentiel : une seule source pour tout le monde


@dataclass(frozen=True, slots=True)
class Intervalle:
    debut: float   # secondes depuis le début de l'enregistrement
    fin: float

    def __post_init__(self) -> None:
        if self.fin < self.debut:
            raise ValueError(f"intervalle inversé : {self.debut} → {self.fin}")

    @property
    def duree(self) -> float:
        return self.fin - self.debut

    def recouvrement(self, autre: Intervalle) -> float:
        """Durée commune aux deux intervalles, 0 s'ils sont disjoints."""
        return max(0.0, min(self.fin, autre.fin) - max(self.debut, autre.debut))


@dataclass(frozen=True, slots=True)
class TourDeParole:
    """Un segment où une même voix parle, tel que le rend la diarisation."""

    intervalle: Intervalle
    voix: str          # identifiant acoustique, pas un nom : « v1 », « v2 »…
    source: Source = Source.INCONNUE


@dataclass(slots=True)
class Replique:
    """Une phrase transcrite, éventuellement rattachée à une voix.

    L'horodatage est conservé jusqu'au compte rendu : c'est ce qui permet de
    revenir à l'audio et de vérifier une citation. Rien ne doit se perdre entre
    la transcription et le document final.
    """

    intervalle: Intervalle
    texte: str
    voix: str | None = None
    source: Source = Source.INCONNUE


@dataclass(frozen=True, slots=True)
class Empreinte:
    """Signature vocale d'une personne, telle que la produit le modèle.

    Le vecteur est stocké normalisé : la comparaison se réduit alors à un
    produit scalaire, et deux enregistrements de volumes différents ne sont pas
    tenus pour deux personnes différentes.
    """

    vecteur: tuple[float, ...]
    duree_source: float = 0.0

    def __post_init__(self) -> None:
        if not self.vecteur:
            raise ValueError("empreinte vide")


@dataclass(slots=True)
class Personne:
    """Une personne connue de la banque de voix."""

    nom: str
    empreintes: list[Empreinte] = field(default_factory=list)
    vu_le: datetime | None = None
    reunions: int = 0


@dataclass(slots=True)
class Reunion:
    """L'objet central : ce qui a été enregistré et ce qu'on en sait."""

    identifiant: str
    titre: str
    debut: datetime
    audio: Path
    duree: float = 0.0
    phase: Phase = Phase.REPOS
    repliques: list[Replique] = field(default_factory=list)
    tours: list[TourDeParole] = field(default_factory=list)
    # voix acoustique → nom, une fois l'identification faite
    noms: dict[str, str] = field(default_factory=dict)
    personnes_en_salle: int | None = None

    def nom_de(self, voix: str | None) -> str:
        if voix is None:
            return "Indéterminé"
        return self.noms.get(voix, voix)

    @property
    def temps_de_parole(self) -> dict[str, float]:
        """Secondes parlées par voix, silences exclus."""
        cumul: dict[str, float] = {}
        for tour in self.tours:
            cumul[tour.voix] = cumul.get(tour.voix, 0.0) + tour.intervalle.duree
        return cumul

    def couverture(self) -> float:
        """Part de l'audio effectivement couverte par du texte transcrit.

        Un écart important révèle que whisper a décroché ou bouclé sur un
        passage. Le compte rendu doit le signaler plutôt que de laisser croire
        à une transcription complète.
        """
        if self.duree <= 0:
            return 0.0
        parlee = sum(r.intervalle.duree for r in self.repliques)
        return min(1.0, parlee / self.duree)
