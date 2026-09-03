"""La banque de voix : un fichier par personne, sur le disque.

C'est ce qui fait qu'une réunion sur deux n'a plus besoin d'être annotée. Une
fois qu'une voix porte un nom, elle est reconnue les fois suivantes.

Format volontairement lisible — du JSON, un fichier par personne — plutôt qu'une
base de données : on doit pouvoir supprimer quelqu'un de la banque en effaçant
un fichier, sans outil ni requête. Pour des données biométriques, savoir
exactement où elles sont et pouvoir les détruire d'un geste n'est pas un détail.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from greffier.domaine.empreintes import EMPREINTES_PAR_PERSONNE, enrichir
from greffier.domaine.modeles import Empreinte, Personne

FORMAT = 1


def _fichier_sur(nom: str) -> str:
    """Nom de fichier sûr, dérivé du nom de la personne.

    Sans accents ni espaces : les systèmes de fichiers ne les normalisent pas
    tous de la même façon, et « Josiane » retrouvée sous deux orthographes
    créerait deux personnes.
    """
    depouille = unicodedata.normalize("NFD", nom)
    sans_accent = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    reduit = re.sub(r"[^a-zA-Z0-9]+", "-", sans_accent).strip("-").lower()
    return reduit or "sans-nom"


class BanqueFichiers:
    def __init__(self, dossier: Path, maximum: int = EMPREINTES_PAR_PERSONNE) -> None:
        self.dossier = dossier
        self.maximum = maximum

    # ------------------------------------------------------------- lecture

    def personnes(self) -> list[Personne]:
        if not self.dossier.exists():
            return []
        connues = []
        for fichier in sorted(self.dossier.glob("*.json")):
            personne = self._lire(fichier)
            if personne is not None:
                connues.append(personne)
        return connues

    def _lire(self, fichier: Path) -> Personne | None:
        try:
            contenu = json.loads(fichier.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Un fichier abîmé ne doit pas empêcher de reconnaître les autres :
            # on l'ignore plutôt que de faire échouer toute la réunion.
            return None
        if contenu.get("format", 0) > FORMAT:
            return None
        return Personne(
            nom=contenu["nom"],
            empreintes=[
                Empreinte(vecteur=tuple(e["vecteur"]), duree_source=e.get("duree", 0.0))
                for e in contenu.get("empreintes", [])
            ],
            vu_le=(
                datetime.fromisoformat(contenu["vu_le"]) if contenu.get("vu_le") else None
            ),
            reunions=contenu.get("reunions", 0),
        )

    def trouver(self, nom: str) -> Personne | None:
        fichier = self.dossier / f"{_fichier_sur(nom)}.json"
        return self._lire(fichier) if fichier.exists() else None

    # ------------------------------------------------------------ écriture

    def enregistrer(self, nom: str, empreinte: Empreinte) -> Personne:
        """Ajoute une empreinte à quelqu'un, en le créant au besoin."""
        personne = self.trouver(nom) or Personne(nom=nom)
        enrichir(personne, empreinte, maximum=self.maximum)
        personne.vu_le = datetime.now(UTC)
        self._ecrire(personne)
        return personne

    def _ecrire(self, personne: Personne) -> Path:
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self.dossier / f"{_fichier_sur(personne.nom)}.json"
        contenu = {
            "format": FORMAT,
            "nom": personne.nom,
            "vu_le": personne.vu_le.isoformat() if personne.vu_le else None,
            "reunions": personne.reunions,
            "empreintes": [
                {"vecteur": list(e.vecteur), "duree": e.duree_source}
                for e in personne.empreintes
            ],
        }
        provisoire = chemin.with_suffix(".json.partiel")
        provisoire.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
        provisoire.replace(chemin)
        return chemin

    def renommer(self, ancien: str, nouveau: str) -> Personne:
        """Corrige un nom mal saisi, sans perdre les empreintes accumulées."""
        personne = self.trouver(ancien)
        if personne is None:
            raise KeyError(f"« {ancien} » n'est pas dans la banque de voix.")
        (self.dossier / f"{_fichier_sur(ancien)}.json").unlink()
        personne.nom = nouveau
        self._ecrire(personne)
        return personne

    def fusionner(self, garde: str, absorbe: str) -> Personne:
        """Réunit deux entrées qui désignaient la même personne."""
        principal = self.trouver(garde)
        secondaire = self.trouver(absorbe)
        if principal is None or secondaire is None:
            raise KeyError("les deux personnes doivent exister dans la banque")
        for empreinte in secondaire.empreintes:
            enrichir(principal, empreinte, maximum=self.maximum)
        principal.reunions = max(principal.reunions, secondaire.reunions)
        (self.dossier / f"{_fichier_sur(absorbe)}.json").unlink()
        self._ecrire(principal)
        return principal

    def oublier(self, nom: str) -> bool:
        """Efface une personne. Une empreinte vocale est une donnée biométrique :
        il doit être possible de la supprimer, simplement et complètement."""
        fichier = self.dossier / f"{_fichier_sur(nom)}.json"
        if not fichier.exists():
            return False
        fichier.unlink()
        return True
