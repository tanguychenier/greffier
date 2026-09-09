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
    #: Le sujet, choisi à la main. Il l'emporte sur le titre du compte rendu à
    #: l'affichage. Un **libellé** et non un renommage de l'identifiant : celui-ci
    #: porte la date, qui ordonne les réunions et date le compte rendu, et sert
    #: de clé à l'audio, à la transcription et au fil du direct. Le remplacer par
    #: « point du lundi » perdrait tout cela d'un coup.
    sujet: str = ""
    #: Quand la réunion a commencé et quand elle a été arrêtée, à l'horloge.
    #: Absentes d'une réunion traitée depuis un fichier audio seul : on retombe
    #: alors sur l'horodatage de l'identifiant. `duree` ne suffit pas à déduire
    #: la fin — elle s'arrête au dernier mot prononcé, pas à l'arrêt.
    commencee_le: datetime | None = None
    terminee_le: datetime | None = None

    def participants(self, minimum: float = 10.0) -> list[str]:
        """Les voix qui ont porté la réunion, de la plus bavarde à la moins.

        La segmentation laisse une traîne de fragments d'une seconde. Les
        compter comme des participants faisait annoncer « Fantin, Tanguy,
        Michel, et 295 voix non nommées » en tête d'un compte rendu de trois
        personnes. Un fragment qui porte déjà un nom échappe au filtre : c'est
        quelqu'un qu'on a identifié, sa brièveté ne l'efface pas.
        """
        temps = self.temps_de_parole()
        return [
            voix for voix, duree in temps.items()
            if duree >= minimum or voix in self.noms
        ]

    def voix_portant(self, nom: str) -> list[str]:
        """Les voix déjà nommées ainsi, dans cette réunion."""
        replie = nom.casefold()
        return [v for v, porte in self.noms.items() if porte.casefold() == replie]

    def reunir(self, absorbee: str, gardee: str) -> int:
        """Verse tous les tours et répliques d'une voix dans une autre.

        Nommer deux voix du même prénom ne les rapprochait pas : chacune gardait
        son identifiant, et le compte rendu annonçait deux participants du même
        nom. Sur une réunion réelle, trente-six voix ont dû être nommées à la
        main pour trois personnes, sans jamais les réunir.

        Rend le nombre de tours déplacés, pour que l'appelant puisse le dire.
        """
        if absorbee == gardee:
            return 0
        deplaces = sum(1 for t in self.tours if t.voix == absorbee)
        # `TourDeParole` est gelé : on reconstruit la liste plutôt que de la
        # muter. Le gel n'est pas un obstacle, c'est ce qui garantit qu'aucun
        # autre endroit du code ne déplace un tour sans passer par ici.
        self.tours = [
            replace(tour, voix=gardee) if tour.voix == absorbee else tour
            for tour in self.tours
        ]
        for replique in self.repliques:
            if replique.voix == absorbee:
                replique.voix = gardee
        self.noms.pop(absorbee, None)
        self.propositions.pop(absorbee, None)
        return deplaces

    @property
    def intitule(self) -> str:
        """Ce qui nomme la réunion : le sujet choisi, sinon l'identifiant."""
        return self.sujet or self.identifiant

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
