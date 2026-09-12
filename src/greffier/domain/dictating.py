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

#: Below this, on a microphone whose level the rest of the tool already reads,
#: nobody is speaking into it. Measured on the meters of the recording screen:
#: speech sits between -30 and -12 dB, a quiet room between -60 and -50.
SILENCE_DB = -42.0

#: How long that silence must last. Shorter cuts people off between two words --
#: French carries pauses of nearly a second inside a sentence. Longer makes them
#: wait, and they say « allô ? ».
SILENCE_S = 1.4

#: How much **speech** a take must carry before silence may end it. Counted on
#: what was said and not on how long the take lasted: a first word followed by a
#: breath would otherwise be a finished sentence, and what is transcribed is the
#: speech, never the silence around it.
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
