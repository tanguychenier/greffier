"""What the machine allows, and what follows from it."""

from __future__ import annotations

from dataclasses import dataclass, field

LARGE_MODEL_MEMORY_GB = 8.0
DISK_NEEDED_GB = 3.0

@dataclass
class Reading:
    """A checked point, and what to do when it is missing."""

    name: str
    present: bool
    detail: str = ""
    remedy: str = ""
    is_blocking: bool = False

@dataclass
class Recorder:
    """What a machine offers. Filled by the adapter, never guessed."""

    system: str = ""
    architecture: str = ""
    memory_gb: float = 0.0
    free_disk_gb: float = 0.0
    speedup: str = "processeur"   # metal | cuda | processeur

    @property
    def supports_large_model(self) -> bool:
        return self.memory_gb >= LARGE_MODEL_MEMORY_GB

    @property
    def advised_model(self) -> str:
        """The best model this machine runs without trouble."""
        if self.supports_large_model:
            return "large-v3-turbo" if self.system == "Darwin" else "large-v3"
        if self.memory_gb >= 4:
            return "medium"
        return "small"

@dataclass
class Diagnostic:
    """The overall verdict: what is missing, and whether it can be fixed."""

    recorder: Recorder
    readings: list[Reading] = field(default_factory=list)

    @property
    def blocking(self) -> list[Reading]:
        return [c for c in self.readings if c.is_blocking and not c.present]

    @property
    def missing(self) -> list[Reading]:
        return [c for c in self.readings if not c.present]

    @property
    def ready(self) -> bool:
        return not self.blocking
