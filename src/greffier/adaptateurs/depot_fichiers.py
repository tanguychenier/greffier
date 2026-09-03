"""Le fichier maître d'une réunion : tout ce qui a été dit, quand, et par qui.

Un seul fichier JSON par réunion, qui devient la source de vérité. Le compte
rendu en découle, mais on peut y revenir des semaines plus tard pour renommer
une voix, réécouter un passage ou refaire la synthèse autrement — sans
retranscrire l'heure d'audio.

Les horodatages sont conservés jusqu'au bout : ce sont eux qui permettent de
vérifier une citation, de découper un extrait, et de dire ce que la
transcription a perdu.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from greffier.domaine.modeles import Intervalle, Replique, Source, TourDeParole

FORMAT = 1


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


class DepotFichiers:
    """Range et relit les fichiers maîtres, un par réunion."""

    def __init__(self, dossier: Path) -> None:
        self.dossier = dossier

    def _chemin(self, identifiant: str) -> Path:
        return self.dossier / f"{identifiant}.json"

    def enregistrer(self, reunion: ReunionEnregistree) -> Path:
        self.dossier.mkdir(parents=True, exist_ok=True)
        contenu = {
            "format": FORMAT,
            "identifiant": reunion.identifiant,
            "audio": str(reunion.audio),
            "traitee_le": reunion.traitee_le.isoformat(),
            "duree": reunion.duree,
            "noms": reunion.noms,
            "propositions": reunion.propositions,
            "avertissements": reunion.avertissements,
            "evenements_materiel": reunion.evenements_materiel,
            "couverture": round(reunion.couverture, 4),
            "tours": [
                {"debut": t.intervalle.debut, "fin": t.intervalle.fin,
                 "voix": t.voix, "source": t.source.value}
                for t in reunion.tours
            ],
            "repliques": [
                {"debut": r.intervalle.debut, "fin": r.intervalle.fin,
                 "texte": r.texte, "voix": r.voix, "source": r.source.value}
                for r in reunion.repliques
            ],
        }
        chemin = self._chemin(reunion.identifiant)
        # Écriture puis renommage : une interruption ne doit pas laisser un
        # fichier maître à moitié écrit à la place de l'ancien, valide.
        provisoire = chemin.with_suffix(".json.partiel")
        provisoire.write_text(
            json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        provisoire.replace(chemin)
        return chemin

    def lire(self, identifiant: str) -> ReunionEnregistree:
        chemin = self._chemin(identifiant)
        if not chemin.exists():
            raise FileNotFoundError(
                f"Réunion « {identifiant} » inconnue. « greffier reunions » les liste."
            )
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        if contenu.get("format", 0) > FORMAT:
            raise ValueError(
                f"{chemin} vient d'une version plus récente de Greffier (format "
                f"{contenu['format']}, connu jusqu'à {FORMAT})."
            )
        return ReunionEnregistree(
            identifiant=contenu["identifiant"],
            audio=Path(contenu["audio"]),
            traitee_le=datetime.fromisoformat(contenu["traitee_le"]),
            duree=contenu["duree"],
            noms=contenu.get("noms", {}),
            propositions=contenu.get("propositions", {}),
            avertissements=contenu.get("avertissements", []),
            evenements_materiel=contenu.get("evenements_materiel", []),
            tours=[
                TourDeParole(Intervalle(t["debut"], t["fin"]), t["voix"],
                             Source(t.get("source", "inconnue")))
                for t in contenu.get("tours", [])
            ],
            repliques=[
                Replique(Intervalle(r["debut"], r["fin"]), r["texte"], r.get("voix"),
                         Source(r.get("source", "inconnue")))
                for r in contenu.get("repliques", [])
            ],
        )

    def lister(self) -> list[str]:
        if not self.dossier.exists():
            return []
        return sorted(
            (f.stem for f in self.dossier.glob("*.json")),
            reverse=True,  # les plus récentes d'abord : ce sont elles qu'on cherche
        )

    def derniere(self) -> ReunionEnregistree | None:
        identifiants = self.lister()
        return self.lire(identifiants[0]) if identifiants else None


class Traitee(Protocol):
    """Ce qu'un traitement rend, vu d'ici.

    Un `Protocol` évite que l'adaptateur importe le cas d'usage — la dépendance
    doit aller dans l'autre sens.
    """

    audio: Path
    repliques: list[Replique]
    tours: list[TourDeParole]
    noms: dict[str, str]
    propositions: dict[str, str]
    avertissements: list[str]
    evenements_materiel: list[str]


def depuis_resultat(resultat: Traitee, duree: float) -> ReunionEnregistree:
    """Convertit le résultat d'un traitement en fichier maître."""
    return ReunionEnregistree(
        identifiant=resultat.audio.stem,
        audio=resultat.audio,
        traitee_le=datetime.now(UTC),
        duree=duree,
        repliques=resultat.repliques,
        tours=resultat.tours,
        noms=dict(resultat.noms),
        propositions=dict(resultat.propositions),
        avertissements=list(resultat.avertissements),
        evenements_materiel=list(resultat.evenements_materiel),
    )
