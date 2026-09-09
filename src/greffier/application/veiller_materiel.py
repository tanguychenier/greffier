"""Surveille le matériel audio pendant l'enregistrement, et réagit.

`greffier enregistrer` lance ffmpeg puis rend la main : plus rien de Greffier ne
tourne pendant la réunion. Personne n'est donc là pour voir un casque apparaître.
Cette veille est le processus qui manque : elle vit le temps de l'enregistrement,
et pas une seconde de plus.

Ce n'est pas le démon écarté de la feuille de route. Un démon tourne en
permanence, se surveille et se redémarre. Celle-ci naît avec l'enregistrement,
meurt avec lui, et son absence ne coûte que l'adaptation au matériel — la
capture, elle, continue.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from greffier.domaine.capture import SurveillanceDeCapture
from greffier.domaine.modeles import Phase
from greffier.domaine.niveau import SurveillanceDeNiveau
from greffier.domaine.peripheriques import Action, Materiel, Veille

#: Quatre secondes : assez court pour qu'un branchement ne coûte qu'un mot ou
#: deux, assez long pour que la lecture du matériel reste imperceptible.
INTERVALLE = 4.0


class Listeur(Protocol):
    """Ce qu'on attend de la lecture du matériel."""

    def lire(self) -> Materiel: ...  # pragma: no cover


class Machine(Protocol):
    """Ce qu'on attend de la machine à états d'enregistrement.

    Réduit au strict nécessaire : la veille n'a pas à connaître le démarrage,
    l'arrêt ni le recollage.
    """

    def lire(self) -> Any: ...  # pragma: no cover

    def reprendre(self, raison: str) -> Any: ...  # pragma: no cover

    def signaler(self, avertissement: str) -> Any: ...  # pragma: no cover


@dataclass
class VeilleMateriel:
    """Un tour de veille, isolé de l'horloge et du matériel pour être éprouvable."""

    machine: Machine
    listeur: Listeur
    veille: Veille
    #: Reconstruit le périphérique agrégé autour du micro donné. Vrai si réussi.
    reconstruire: Callable[[str], bool]
    #: Prévient l'utilisateur, quand le système sait afficher quelque chose.
    prevenir: Callable[[str], None] = lambda _: None
    #: Taille du morceau en cours d'écriture, en octets, ou None si on ne sait
    #: pas la lire. Facultatif : sans elle la veille garde son ancien office,
    #: ce dont les tests du matériel profitent.
    taille_captee: Callable[[], int | None] | None = None
    #: Niveau du micro sur les dernières fractions de seconde écrites, ou None
    #: si on ne sait pas le lire. Facultatif au même titre que la taille.
    niveau_capte: Callable[[], float | None] | None = None
    intervalle: float = INTERVALLE

    def __post_init__(self) -> None:
        self._precedent: Materiel | None = None
        self._capture = SurveillanceDeCapture()
        self._niveau = SurveillanceDeNiveau()

    def enregistre(self) -> bool:
        """Faux dès que l'enregistrement s'arrête : la veille n'a plus d'objet."""
        try:
            return self.machine.lire().phase is Phase.ENREGISTREMENT
        except (OSError, ValueError):
            return False

    def tour(self) -> None:
        """Un tour : voir si la capture avance et porte du son, puis le matériel."""
        self._verifier_la_capture()
        self._verifier_le_niveau()
        courant = self.listeur.lire()
        if not courant.peripheriques:
            # Lecture impossible : on ne conclut rien. Décider sur un matériel
            # vide reviendrait à croire que tout a été débranché.
            return
        if self._precedent is None:
            self._precedent = courant
            return

        decision = self.veille.examiner(self._precedent, courant)
        self._precedent = courant
        if decision.action is Action.RIEN:
            return

        if decision.action is Action.ALERTER:
            self.machine.signaler(decision.raison)
            self.prevenir(decision.raison)
            return

        # Reconstruire d'abord : rouvrir la capture sur un agrégé encore périmé
        # ne servirait à rien, et perdrait le morceau en cours pour rien.
        if not self.reconstruire(decision.micro):
            self.machine.signaler(
                f"{decision.raison} La reconstruction du périphérique a échoué : "
                "la capture continue sur l'ancien."
            )
            self.prevenir("Changement de matériel non pris en compte.")
            return
        self.machine.reprendre(decision.raison)
        self.prevenir(decision.raison)

    def _verifier_la_capture(self) -> None:
        """Dit tout de suite si plus rien ne s'écrit.

        Avant, une capture morte ne se voyait qu'au traitement, une fois la
        réunion finie : le contrôle de silence de la chaîne arrive trop tard
        pour qu'on puisse la refaire.
        """
        if self.taille_captee is None:
            return
        octets = self.taille_captee()
        if octets is None:
            return
        raison = self._capture.constater(octets)
        if not raison:
            return
        self.machine.signaler(raison)
        self.prevenir("L'enregistrement n'avance plus.")

    def _verifier_le_niveau(self) -> None:
        """Dit, une fois, que le son capté est trop faible pour transcrire.

        Distinct de la capture qui n'avance plus : ici le fichier grossit, mais
        il ne contient presque rien. Mesuré sur ce projet : à -43 dB, le modèle
        n'écrit pas moins bien, il **invente** — « Merci d'avoir regardé cette
        vidéo ! » pour « Test, test de réunion ». Le dire pendant la réunion
        laisse une chance de rapprocher le micro ; le découvrir au compte rendu
        n'en laisse aucune.
        """
        if self.niveau_capte is None:
            return
        db = self.niveau_capte()
        if db is None:
            return
        raison = self._niveau.constater(db)
        if not raison:
            return
        self.machine.signaler(raison)
        self.prevenir("Le son capté est trop faible.")

    def boucler(self, dormir: Callable[[float], None] = time.sleep) -> int:
        """Veille jusqu'à l'arrêt de l'enregistrement. Rend le nombre de tours."""
        tours = 0
        while self.enregistre():
            self.tour()
            tours += 1
            dormir(self.intervalle)
        return tours
