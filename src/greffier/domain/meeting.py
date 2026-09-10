"""Une réunion traitée, telle qu'on la garde.

C'est le fichier maître : ce que la chaîne a compris d'une réunion, et ce qu'on
relit pour nommer une voix après coup, régénérer un compte rendu ou répondre à
une question. Le format sur disque appartient à l'adaptateur ; l'objet, lui,
est du domaine.

Il vivait dans l'adaptateur de dépôt, si bien que trois cas d'usage —
`nommer`, `restituer`, `traiter` — importaient un adaptateur pour parler d'une
réunion. La dépendance allait à l'envers, et un test d'architecture le dit
maintenant à la première tentative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from greffier.domain.models import Span, SpeakerTurn, Utterance

HORODATAGE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:_(\d{2})h(\d{2}))?")

def held_on(identifier: str) -> tuple[int, int, int, int, int] | None:
    """Quand la réunion s'est tenue, d'après son identifiant. None s'il se taît.

    Sert à ordonner les réunions. Un identifiant sans date — une réunion
    importée, renommée à la main, fabriquée pour un essai — n'est pas une
    erreur, mais il ne permet pas de dire qu'elle est la dernière.
    """
    trouve = HORODATAGE.match(identifier)
    if trouve is None:
        return None
    annee, mois, jour, heure, minute = trouve.groups()
    return (int(annee), int(mois), int(jour), int(heure or 0), int(minute or 0))

@dataclass
class StoredMeeting:
    """Une réunion traitée, telle qu'elle est rangée sur le disque."""

    identifier: str
    audio: Path
    traitee_le: datetime
    duration: float
    utterances: list[Utterance]
    turns: list[SpeakerTurn]
    names: dict[str, str]
    propositions: dict[str, str]
    warnings: list[str]
    hardware_events: list[str] = field(default_factory=list)
    subject: str = ""
    commencee_le: datetime | None = None
    terminee_le: datetime | None = None

    def attendees(self, minimum: float = 10.0) -> list[str]:
        """Les voix qui ont porté la réunion, de la plus bavarde à la moins.

        La segmentation laisse une traîne de fragments d'une seconde. Les
        compter comme des participants faisait annoncer « Florent, Tanguy,
        Marcel, et 295 voix non nommées » en tête d'un compte rendu de trois
        personnes. Un fragment qui porte déjà un nom échappe au filtre : c'est
        quelqu'un qu'on a identifié, sa brièveté ne l'efface pas.
        """
        temps = self.speaking_time()
        return [
            voice for voice, duration in temps.items()
            if duration >= minimum or voice in self.names
        ]

    def voice_named(self, name: str) -> list[str]:
        """Les voix déjà nommées ainsi, dans cette réunion."""
        replie = name.casefold()
        return [v for v, porte in self.names.items() if porte.casefold() == replie]

    def join_into(self, absorbee: str, gardee: str) -> int:
        """Verse tous les tours et répliques d'une voix dans une autre.

        Nommer deux voix du même prénom ne les rapprochait pas : chacune gardait
        son identifiant, et le compte rendu annonçait deux participants du même
        nom. Sur une réunion réelle, trente-six voix ont dû être nommées à la
        main pour trois personnes, sans jamais les réunir.

        Rend le nombre de tours déplacés, pour que l'appelant puisse le dire.
        """
        if absorbee == gardee:
            return 0
        deplaces = sum(1 for t in self.turns if t.voice == absorbee)
        # `TourDeParole` est gelé : on reconstruit la liste plutôt que de la
        # muter. Le gel n'est pas un obstacle, c'est ce qui garantit qu'aucun
        # autre endroit du code ne déplace un tour sans passer par ici.
        self.turns = [
            replace(turn, voice=gardee) if turn.voice == absorbee else turn
            for turn in self.turns
        ]
        for utterance in self.utterances:
            if utterance.voice == absorbee:
                utterance.voice = gardee
        self.names.pop(absorbee, None)
        self.propositions.pop(absorbee, None)
        return deplaces

    @property
    def caption(self) -> str:
        """Ce qui nomme la réunion : le sujet choisi, sinon l'identifiant."""
        return self.subject or self.identifier

    @property
    def coverage(self) -> float:
        """Part de l'audio effectivement couverte par du texte.

        Un écart important révèle que le modèle a décroché ou bouclé sur un
        passage. Le compte rendu doit le signaler plutôt que de laisser croire à
        une transcription complète.
        """
        if self.duration <= 0:
            return 0.0
        return min(1.0, sum(r.span.duration for r in self.utterances) / self.duration)

    def gaps(self, minimum: float = 5.0) -> list[Span]:
        """Passages d'au moins `minimum` secondes sans une seule réplique.

        Un silence peut être un vrai silence — ou du texte perdu. On les liste
        sans trancher : c'est au compte rendu de le dire honnêtement.
        """
        if not self.utterances:
            return [Span(0.0, self.duration)] if self.duration > minimum else []
        manques: list[Span] = []
        ordonnees = sorted(self.utterances, key=lambda r: r.span.start)
        precedent = 0.0
        for utterance in ordonnees:
            if utterance.span.start - precedent >= minimum:
                manques.append(Span(precedent, utterance.span.start))
            precedent = max(precedent, utterance.span.end)
        if self.duration - precedent >= minimum:
            manques.append(Span(precedent, self.duration))
        return manques

    def nom_de(self, voice: str | None) -> str:
        if voice is None:
            return "Indéterminé"
        return self.names.get(voice, f"Personne {voice}")

    def spans_of(self, voice: str) -> list[Span]:
        return [t.span for t in self.turns if t.voice == voice]

    def speaking_time(self) -> dict[str, float]:
        cumul: dict[str, float] = {}
        for turn in self.turns:
            cumul[turn.voice] = cumul.get(turn.voice, 0.0) + turn.span.duration
        return dict(sorted(cumul.items(), key=lambda x: -x[1]))
