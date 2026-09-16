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
    entries: int = 0
    sorties: int = 0

    @property
    def captured(self) -> bool:
        return self.entries > 0

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
    REBUILD = "reconstruire"
    ALERT = "alerter"

@dataclass(frozen=True)
class Decision:
    action: Action
    because: str = ""
    mic: str = ""
    audio_suspect: bool = False

def _headset_usable(hardware: Hardware, preferred: str) -> Device | None:
    expected = hardware.by_name(preferred)
    if expected is not None and expected.captured:
        return expected
    return None

def _fallback_mic(hardware: Hardware, excluded: tuple[str, ...]) -> Device | None:
    """The best mic available, excluding those to be avoided."""
    candidates_ = [
        p for p in hardware.mics
        if p.name not in excluded and not _is_loopback(p.name) and not _is_aggregated(p)
    ]
    if not candidates_:
        return None
    headsets = [p for p in candidates_ if not _is_built_in(p.name) and p.entries == 1]
    built_in = [p for p in candidates_ if _is_built_in(p.name)]
    return (headsets or built_in or candidates_)[0]

def _is_aggregated(device: Device) -> bool:
    """The devices the tool builds itself."""
    return device.uid.startswith("com.reunions.")

def _is_loopback(name: str) -> bool:
    return any(mark in name.lower() for mark in ("blackhole", "loopback", "soundflower"))

def _is_built_in(name: str) -> bool:
    return any(mark in name.lower() for mark in ("macbook", "built-in", "intégré", "integre"))

@dataclass
class WatchRules:
    """Follows the hardware during a recording and says when to react."""

    wanted_mic: str
    aggregated: str = "Reunion Entree"
    events: list[str] = field(default_factory=list)

    def examine(self, earlier: Hardware, later: Hardware) -> Decision:
        """Compares two hardware states and decides."""
        if earlier.devices == later.devices:
            return Decision(Action.NOTHING)

        wanted_before = earlier.present(self.wanted_mic)
        wanted_after = later.present(self.wanted_mic)

        if wanted_after and not wanted_before:
            self.events.append(f"{self.wanted_mic} branché en cours de réunion")
            return Decision(
                Action.REBUILD,
                f"« {self.wanted_mic} » vient d'être branché : "
                "la capture reprend dessus, le début de la réunion ne l'a pas eu.",
                mic=self.wanted_mic,
                audio_suspect=True,
            )

        if wanted_before and not wanted_after:
            self.events.append(f"{self.wanted_mic} débranché en cours de réunion")
            fallback = _fallback_mic(later, excluded=(self.wanted_mic, self.aggregated))
            if fallback is None:
                return Decision(
                    Action.ALERT,
                    f"« {self.wanted_mic} » a été débranché et aucun autre micro "
                    "n'est disponible : ta voix n'est plus enregistrée.",
                    audio_suspect=True,
                )
            return Decision(
                Action.REBUILD,
                f"« {self.wanted_mic} » a été débranché : la capture reprend sur "
                f"« {fallback.name} ».",
                mic=fallback.name,
                audio_suspect=True,
            )

        if not wanted_after:
            fallback = _fallback_mic(later, excluded=(self.wanted_mic, self.aggregated))
            before_fallback = _fallback_mic(earlier, excluded=(self.wanted_mic, self.aggregated))
            if fallback is not None and (
                before_fallback is None or fallback.name != before_fallback.name
            ):
                self.events.append(f"{fallback.name} branché en cours de réunion")
                return Decision(
                    Action.REBUILD,
                    f"« {fallback.name} » vient d'être branché : la capture reprend dessus.",
                    mic=fallback.name,
                    audio_suspect=True,
                )

        return Decision(Action.NOTHING)

SILENT_FLOOR_DB = -68.0

@dataclass(frozen=True)
class MicChoice:
    """The mic kept after listening, and what needs saying about it."""

    name: str
    level_db: float
    set_aside: tuple[tuple[str, float], ...] = ()
    all_silent: bool = False
    preferred_headset: bool = False

def choose_by_listening(
    trials: dict[str, float], headsets: frozenset[str] = frozenset()
) -> MicChoice | None:
    """Keeps the mic that will best capture **the meeting**, after listening.

    A mic can be plugged in, recognised, turned up, and still mute: USB headsets
    have a mute button on the cable. Choosing without listening yields a whole
    meeting of silence.
    """
    if not trials:
        return None
    ranking = sorted(trials.items(), key=lambda x: -x[1])
    name, level = ranking[0]
    if headsets:
        alive_ones = [
            (other, db) for other, db in ranking
            if other in headsets and db >= SILENT_FLOOR_DB
        ]
        if alive_ones and alive_ones[0][0] != name:
            name, level = alive_ones[0]
            ranking = [(name, level)] + [
                pair for pair in ranking if pair[0] != name
            ]
    return MicChoice(
        name=name,
        level_db=level,
        set_aside=tuple(ranking[1:]),
        all_silent=max(trials.values()) < SILENT_FLOOR_DB,
        preferred_headset=bool(headsets) and name in headsets,
    )

def candidates_to_listen_to(hardware: Hardware, preferred: str) -> list[str]:
    """The mics worth a listen, the preferred one first."""
    useful_ones = [
        p.name for p in hardware.mics
        if not _is_loopback(p.name) and not _is_aggregated(p)
    ]
    if preferred and preferred in useful_ones:
        useful_ones.remove(preferred)
        useful_ones.insert(0, preferred)
    return sorted(
        useful_ones,
        key=lambda name: (
            name != preferred,
            _is_built_in(name),
            name not in {p.name for p in hardware.mics if p.entries == 1},
        ),
    )

def headset_present(hardware: Hardware, name: str) -> bool:
    """Readable shortcut for the pre-recording checks."""
    return _headset_usable(hardware, name) is not None

def headsets_among(hardware: Hardware) -> frozenset[str]:
    """The mics that are, in all likelihood, headset mics."""
    sorties = {
        p.name for p in hardware.devices
        if p.sorties > 0 and not _is_loopback(p.name) and not _is_aggregated(p)
    }
    return frozenset(
        p.name for p in hardware.mics
        if p.name in sorties
        and p.entries == 1
        and not _is_loopback(p.name) and not _is_aggregated(p)
        and not _is_built_in(p.name)
    )

def advised_mic(hardware: Hardware, preferred: str) -> str:
    """Mic to put in the aggregate now, given what is plugged in."""
    if headset_present(hardware, preferred):
        return preferred
    fallback = _fallback_mic(hardware, excluded=(preferred,))
    return fallback.name if fallback else ""
