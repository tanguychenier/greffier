"""Ce que la machine permet, et ce qu'on en déduit — sans rien lui demander.

La règle qui choisit le modèle de transcription est du métier : elle décide de
la qualité du compte rendu et du confort pendant la réunion. Elle vivait au
milieu de `sysctl`, `wmic`, `system_profiler` et `/proc/meminfo`, si bien qu'on
ne pouvait pas l'éprouver sans débrancher une machine — alors que le fichier
d'origine promettait le contraire dans sa propre docstring : « séparer le
constat de la décision permet de tester les deux ».

Ici, le constat entre en paramètre et la décision en sort. Rien n'est lu du
système : `Machine.systeme` doit être renseigné par l'appelant, faute de quoi
la valeur par défaut serait une lecture du monde figée au chargement du module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# En dessous, faire tourner le grand modèle de transcription revient à faire
# ramer la machine pendant toute la réunion.
MEMOIRE_GRAND_MODELE_GO = 8.0
# Modèles, VAD, empreintes, segmentation : 1,7 Go, plus la marge d'extraction.
DISQUE_NECESSAIRE_GO = 3.0


@dataclass
class Constat:
    """Un point vérifié, et quoi faire s'il manque."""

    nom: str
    present: bool
    detail: str = ""
    remede: str = ""
    bloquant: bool = False


@dataclass
class Machine:
    """Ce qu'un poste offre. Rempli par l'adaptateur, jamais deviné ici."""

    systeme: str = ""
    architecture: str = ""
    memoire_go: float = 0.0
    disque_libre_go: float = 0.0
    acceleration: str = "processeur"   # metal | cuda | processeur

    @property
    def supporte_grand_modele(self) -> bool:
        return self.memoire_go >= MEMOIRE_GRAND_MODELE_GO

    @property
    def modele_conseille(self) -> str:
        """Le meilleur modèle que cette machine fasse tourner sans souffrir."""
        if self.supporte_grand_modele:
            return "large-v3-turbo" if self.systeme == "Darwin" else "large-v3"
        if self.memoire_go >= 4:
            return "medium"
        return "small"


@dataclass
class Diagnostic:
    """Le verdict d'ensemble : ce qui manque, et si l'on peut tout de même y aller."""

    machine: Machine
    constats: list[Constat] = field(default_factory=list)

    @property
    def bloquants(self) -> list[Constat]:
        return [c for c in self.constats if c.bloquant and not c.present]

    @property
    def manquants(self) -> list[Constat]:
        return [c for c in self.constats if not c.present]

    @property
    def pret(self) -> bool:
        return not self.bloquants
