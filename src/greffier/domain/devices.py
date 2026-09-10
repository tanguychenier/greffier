"""What to do when the audio hardware changes mid-recording.

Plugging in a headset means rebuilding the capture device, so opening a new
file. Doing that blindly loses the meeting; refusing it records silence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Device:
    """An audio input or output, as the system presents it."""

    name: str
    uid: str
    entrees: int = 0
    sorties: int = 0

    @property
    def captured(self) -> bool:
        return self.entrees > 0

@dataclass(frozen=True)
class Hardware:
    """The state of the audio hardware at one instant."""

    devices: tuple[Device, ...] = ()

    def by_name(self, name: str) -> Device | None:
        return next((p for p in self.devices if p.name == name), None)

    def present(self, name: str) -> bool:
        return self.by_name(name) is not None

    @property
    def mics(self) -> tuple[Device, ...]:
        return tuple(p for p in self.devices if p.captured)

class Action(Enum):
    """What the recording should do about the change observed."""

    NOTHING = "rien"
    RECONSTRUIRE = "reconstruire"
    ALERTER = "alerter"

@dataclass(frozen=True)
class Decision:
    action: Action
    because: str = ""
    mic: str = ""
    audio_suspect: bool = False

def _headset_usable(materiel: Hardware, prefere: str) -> Device | None:
    expected = materiel.by_name(prefere)
    if expected is not None and expected.captured:
        return expected
    return None

def _fallback_mic(materiel: Hardware, excluded: tuple[str, ...]) -> Device | None:
    """The best mic available, excluding those to be avoided."""
    candidats = [
        p for p in materiel.mics
        if p.name not in excluded and not _is_loopback(p.name) and not _is_aggregated(p)
    ]
    if not candidats:
        return None
    casques = [p for p in candidats if not _is_built_in(p.name) and p.entrees == 1]
    integres = [p for p in candidats if _is_built_in(p.name)]
    return (casques or integres or candidats)[0]

def _is_aggregated(peripherique: Device) -> bool:
    """The devices the tool builds itself."""
    return peripherique.uid.startswith("com.reunions.")

def _is_loopback(name: str) -> bool:
    return any(marque in name.lower() for marque in ("blackhole", "loopback", "soundflower"))

def _is_built_in(name: str) -> bool:
    return any(marque in name.lower() for marque in ("macbook", "built-in", "intégré", "integre"))

@dataclass
class WatchRules:
    """Follows the hardware during a recording and says when to react."""

    wanted_mic: str
    agrege: str = "Reunion Entree"
    events: list[str] = field(default_factory=list)

    def examine(self, avant: Hardware, apres: Hardware) -> Decision:
        """Compares two hardware states and decides."""
        if avant.devices == apres.devices:
            return Decision(Action.NOTHING)

        voulu_avant = avant.present(self.wanted_mic)
        voulu_apres = apres.present(self.wanted_mic)

        if voulu_apres and not voulu_avant:
            self.events.append(f"{self.wanted_mic} branché en cours de réunion")
            return Decision(
                Action.RECONSTRUIRE,
                f"« {self.wanted_mic} » vient d'être branché : "
                "la capture reprend dessus, le début de la réunion ne l'a pas eu.",
                mic=self.wanted_mic,
                audio_suspect=True,
            )

        if voulu_avant and not voulu_apres:
            self.events.append(f"{self.wanted_mic} débranché en cours de réunion")
            repli = _fallback_mic(apres, excluded=(self.wanted_mic, self.agrege))
            if repli is None:
                return Decision(
                    Action.ALERTER,
                    f"« {self.wanted_mic} » a été débranché et aucun autre micro "
                    "n'est disponible : ta voix n'est plus enregistrée.",
                    audio_suspect=True,
                )
            return Decision(
                Action.RECONSTRUIRE,
                f"« {self.wanted_mic} » a été débranché : la capture reprend sur "
                f"« {repli.name} ».",
                mic=repli.name,
                audio_suspect=True,
            )

        if not voulu_apres:
            repli = _fallback_mic(apres, excluded=(self.wanted_mic, self.agrege))
            avant_repli = _fallback_mic(avant, excluded=(self.wanted_mic, self.agrege))
            if repli is not None and (avant_repli is None or repli.name != avant_repli.name):
                self.events.append(f"{repli.name} branché en cours de réunion")
                return Decision(
                    Action.RECONSTRUIRE,
                    f"« {repli.name} » vient d'être branché : la capture reprend dessus.",
                    mic=repli.name,
                    audio_suspect=True,
                )

        return Decision(Action.NOTHING)

PLANCHER_MUET_DB = -68.0

@dataclass(frozen=True)
class MicChoice:
    """The mic kept after listening, and what needs saying about it."""

    name: str
    level_db: float
    ecartes: tuple[tuple[str, float], ...] = ()
    all_silent: bool = False
    preferred_headset: bool = False

def choose_by_listening(
    essais: dict[str, float], casques: frozenset[str] = frozenset()
) -> MicChoice | None:
    """Keeps the mic that will best capture **the meeting**, after listening.

    A mic can be plugged in, recognised, turned up, and still mute: USB headsets
    have a mute button on the cable. Choosing without listening yields a whole
    meeting of silence.
    """
    if not essais:
        return None
    ranking = sorted(essais.items(), key=lambda x: -x[1])
    name, level = ranking[0]
    if casques:
        vivants = [
            (other, db) for other, db in ranking
            if other in casques and db >= PLANCHER_MUET_DB
        ]
        if vivants and vivants[0][0] != name:
            name, level = vivants[0]
            ranking = [(name, level)] + [
                pair for pair in ranking if pair[0] != name
            ]
    return MicChoice(
        name=name,
        level_db=level,
        ecartes=tuple(ranking[1:]),
        all_silent=max(essais.values()) < PLANCHER_MUET_DB,
        preferred_headset=bool(casques) and name in casques,
    )

def candidates_to_listen_to(materiel: Hardware, prefere: str) -> list[str]:
    """The mics worth a listen, the preferred one first."""
    utiles = [
        p.name for p in materiel.mics
        if not _is_loopback(p.name) and not _is_aggregated(p)
    ]
    if prefere and prefere in utiles:
        utiles.remove(prefere)
        utiles.insert(0, prefere)
    return sorted(
        utiles,
        key=lambda name: (
            name != prefere,
            _is_built_in(name),
            name not in {p.name for p in materiel.mics if p.entrees == 1},
        ),
    )

def headset_present(materiel: Hardware, name: str) -> bool:
    """Readable shortcut for the pre-recording checks."""
    return _headset_usable(materiel, name) is not None

def headsets_among(materiel: Hardware) -> frozenset[str]:
    """The mics that are, in all likelihood, headset mics."""
    sorties = {
        p.name for p in materiel.devices
        if p.sorties > 0 and not _is_loopback(p.name) and not _is_aggregated(p)
    }
    return frozenset(
        p.name for p in materiel.mics
        if p.name in sorties
        and p.entrees == 1
        and not _is_loopback(p.name) and not _is_aggregated(p)
        and not _is_built_in(p.name)
    )

def advised_mic(materiel: Hardware, prefere: str) -> str:
    """Mic to put in the aggregate now, given what is plugged in."""
    if headset_present(materiel, prefere):
        return prefere
    repli = _fallback_mic(materiel, excluded=(prefere,))
    return repli.name if repli else ""
