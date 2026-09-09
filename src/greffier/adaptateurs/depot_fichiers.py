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
from datetime import datetime
from pathlib import Path

from greffier.domaine.modeles import Intervalle, Replique, Source, TourDeParole
from greffier.domaine.reunion import ReunionEnregistree, tenue_le

FORMAT = 1


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
        """Les réunions, la plus récemment **tenue** d'abord.

        Trié sur l'horodatage que porte l'identifiant, et non par ordre
        alphabétique : « fausse-reunion » passait avant « 2026-09-09_10h05… »
        parce que « f » vient après « 2 », et devenait donc « la dernière
        réunion » pour toutes les commandes appelées sans argument — jusqu'à
        « greffier envoyer », qui expédiait le compte rendu d'une autre réunion
        que celle qui venait de se tenir. Constaté le 2026-09-09.

        Les identifiants sans date vont en fin de liste : ils ne peuvent pas
        prétendre être les derniers. Entre eux, du plus récemment écrit, faute
        de mieux.
        """
        if not self.dossier.exists():
            return []

        def recence(fichier: Path) -> tuple[int, tuple[int, ...], float]:
            tenue = tenue_le(fichier.stem)
            if tenue is None:
                return (0, (0, 0, 0, 0, 0), fichier.stat().st_mtime)
            return (1, tenue, 0.0)

        return [f.stem for f in sorted(self.dossier.glob("*.json"),
                                       key=recence, reverse=True)]

    def derniere(self) -> ReunionEnregistree | None:
        identifiants = self.lister()
        return self.lire(identifiants[0]) if identifiants else None
