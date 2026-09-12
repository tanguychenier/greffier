"""When a spoken sentence is over.

Somebody dictating stops talking; nothing tells the machine that the sentence
has ended. Holding a button down says it -- and makes the person hold a mouse
while they read the document they are asking about, which is what they are doing
when they prepare a meeting.

So it is silence that ends the take. Silence is not the absence of sound: a room
has a floor, a fan, a street. What counts is how long it has been quiet, and how
much quieter than what was being said.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SILENCE_DB = -42.0

SILENCE_S = 1.4

MINIMUM_S = 1.0

@dataclass(slots=True)
class Take:
    """A dictation in progress, deciding when it has ended."""

    quiet_needed: float = SILENCE_S
    floor_db: float = SILENCE_DB
    minimum: float = MINIMUM_S
    elapsed: float = 0.0
    quiet: float = 0.0
    talked: float = field(default=0.0)

    def heard(self, level_db: float, since: float) -> None:
        """One reading of the microphone, and how long since the last one."""
        self.elapsed += since
        if level_db > self.floor_db:
            self.talked += since
            self.quiet = 0.0
        else:
            self.quiet += since

    @property
    def over(self) -> bool:
        """Whether the sentence can be taken as finished.

        Somebody who has not said anything at all is not finished: they are
        thinking, or the microphone is the wrong one. That case ends by the
        ceiling on the recording, or by a second click, and never by this.
        """
        return self.talked >= self.minimum and self.quiet >= self.quiet_needed
