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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from greffier.domaine.modeles import Intervalle, Replique, TourDeParole

#: Les enregistrements sont nommés « 2026-08-25_14h33_sujet » : la date de la
#: réunion est donc dans son identifiant, et c'est la seule source sûre — la
#: date d'écriture du fichier est celle du traitement, qui peut être rejoué des
#: semaines plus tard.
HORODATAGE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:_(\d{2})h(\d{2}))?")


def tenue_le(identifiant: str) -> tuple[int, int, int, int, int] | None:
    """Quand la réunion s'est tenue, d'après son identifiant. None s'il se taît.

    Sert à ordonner les réunions. Un identifiant sans date — une réunion
    importée, renommée à la main, fabriquée pour un essai — n'est pas une
    erreur, mais il ne permet pas de dire qu'elle est la dernière.
    """
    trouve = HORODATAGE.match(identifiant)
    if trouve is None:
        return None
    annee, mois, jour, heure, minute = trouve.groups()
    return (int(annee), int(mois), int(jour), int(heure or 0), int(minute or 0))


@dataclass
class ReunionEnregistree:
    """Une réunion traitée, telle qu'elle est rangée sur le disque."""

    identifiant: str
    audio: Path
    traitee_le: datetime
    duree: float
    repliques: list[Replique]
    tours: list[TourDeParole]
    noms: dict[str, str]
    propositions: dict[str, str]
    avertissements: list[str]
    #: Constats de la veille sur le matériel, pour que régénérer la rédaction
    #: plus tard n'y perde pas ce que la première rédaction savait.
    evenements_materiel: list[str] = field(default_factory=list)

    @property
    def couverture(self) -> float:
        """Part de l'audio effectivement couverte par du texte.

        Un écart important révèle que le modèle a décroché ou bouclé sur un
        passage. Le compte rendu doit le signaler plutôt que de laisser croire à
        une transcription complète.
        """
        if self.duree <= 0:
            return 0.0
        return min(1.0, sum(r.intervalle.duree for r in self.repliques) / self.duree)

    def trous(self, minimum: float = 5.0) -> list[Intervalle]:
        """Passages d'au moins `minimum` secondes sans une seule réplique.

        Un silence peut être un vrai silence — ou du texte perdu. On les liste
        sans trancher : c'est au compte rendu de le dire honnêtement.
        """
        if not self.repliques:
            return [Intervalle(0.0, self.duree)] if self.duree > minimum else []
        manques: list[Intervalle] = []
        ordonnees = sorted(self.repliques, key=lambda r: r.intervalle.debut)
        precedent = 0.0
        for replique in ordonnees:
            if replique.intervalle.debut - precedent >= minimum:
                manques.append(Intervalle(precedent, replique.intervalle.debut))
            precedent = max(precedent, replique.intervalle.fin)
        if self.duree - precedent >= minimum:
            manques.append(Intervalle(precedent, self.duree))
        return manques

    def nom_de(self, voix: str | None) -> str:
        if voix is None:
            return "Indéterminé"
        return self.noms.get(voix, f"Personne {voix}")

    def intervalles_de(self, voix: str) -> list[Intervalle]:
        return [t.intervalle for t in self.tours if t.voix == voix]

    def temps_de_parole(self) -> dict[str, float]:
        cumul: dict[str, float] = {}
        for tour in self.tours:
            cumul[tour.voix] = cumul.get(tour.voix, 0.0) + tour.intervalle.duree
        return dict(sorted(cumul.items(), key=lambda x: -x[1]))
