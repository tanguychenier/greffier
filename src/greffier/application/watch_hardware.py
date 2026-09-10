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

from greffier.domain.capture import CaptureWatch
from greffier.domain.devices import Action, Hardware, WatchRules
from greffier.domain.level import LevelWatch
from greffier.domain.models import Phase

SPAN = 4.0

class Lister(Protocol):
    """Ce qu'on attend de la lecture du matériel."""

    def read(self) -> Hardware: ...  # pragma: no cover

class Recorder(Protocol):
    """Ce qu'on attend de la machine à états d'enregistrement.

    Réduit au strict nécessaire : la veille n'a pas à connaître le démarrage,
    l'arrêt ni le recollage.
    """

    def read(self) -> Any: ...  # pragma: no cover

    def reprendre(self, because: str) -> Any: ...  # pragma: no cover

    def report(self, warning: str) -> Any: ...  # pragma: no cover

@dataclass
class HardwareWatch:
    """Un tour de veille, isolé de l'horloge et du matériel pour être éprouvable."""

    recorder: Recorder
    lister: Lister
    watch_rules: WatchRules
    reconstruire: Callable[[str], bool]
    notify_user: Callable[[str], None] = lambda _: None
    captured_size: Callable[[], int | None] | None = None
    captured_level: Callable[[], float | None] | None = None
    span: float = SPAN

    def __post_init__(self) -> None:
        self._precedent: Hardware | None = None
        self._capture = CaptureWatch()
        self._level = LevelWatch()

    def recorded(self) -> bool:
        """Faux dès que l'enregistrement s'arrête : la veille n'a plus d'objet."""
        try:
            return self.recorder.read().phase is Phase.RECORDING
        except (OSError, ValueError):
            return False

    def turn(self) -> None:
        """Un tour : voir si la capture avance et porte du son, puis le matériel."""
        self._check_the_capture()
        self._check_the_level()
        current = self.lister.read()
        if not current.devices:
            return
        if self._precedent is None:
            self._precedent = current
            return

        decision = self.watch_rules.examine(self._precedent, current)
        self._precedent = current
        if decision.action is Action.RIEN:
            return

        if decision.action is Action.ALERTER:
            self.recorder.report(decision.because)
            self.notify_user(decision.because)
            return

        if not self.reconstruire(decision.mic):
            self.recorder.report(
                f"{decision.because} La reconstruction du périphérique a échoué : "
                "la capture continue sur l'ancien."
            )
            self.notify_user("Changement de matériel non pris en compte.")
            return
        self.recorder.reprendre(decision.because)
        self.notify_user(decision.because)

    def _check_the_capture(self) -> None:
        """Dit tout de suite si plus rien ne s'écrit.

        Avant, une capture morte ne se voyait qu'au traitement, une fois la
        réunion finie : le contrôle de silence de la chaîne arrive trop tard
        pour qu'on puisse la refaire.
        """
        if self.captured_size is None:
            return
        bytes_read = self.captured_size()
        if bytes_read is None:
            return
        because = self._capture.observe(bytes_read)
        if not because:
            return
        self.recorder.report(because)
        self.notify_user("L'enregistrement n'avance plus.")

    def _check_the_level(self) -> None:
        """Dit, une fois, que le son capté est trop faible pour transcrire.

        Distinct de la capture qui n'avance plus : ici le fichier grossit, mais
        il ne contient presque rien. Mesuré sur ce projet : à -43 dB, le modèle
        n'écrit pas moins bien, il **invente** — « Merci d'avoir regardé cette
        vidéo ! » pour « Test, test de réunion ». Le dire pendant la réunion
        laisse une chance de rapprocher le micro ; le découvrir au compte rendu
        n'en laisse aucune.
        """
        if self.captured_level is None:
            return
        db = self.captured_level()
        if db is None:
            return
        because = self._level.observe(db)
        if not because:
            return
        self.recorder.report(because)
        self.notify_user("Le son capté est trop faible.")

    def loop(self, dormir: Callable[[float], None] = time.sleep) -> int:
        """Veille jusqu'à l'arrêt de l'enregistrement. Rend le nombre de tours."""
        turns = 0
        while self.recorded():
            self.turn()
            turns += 1
            dormir(self.span)
        return turns
