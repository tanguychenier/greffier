"""Saying that a sentence is not sure, where it is not sure.

The complaint that started this was « les mots affichés n'étaient pas ceux dits
en séance ». Measured, the decoding settings change nothing on clean speech;
what changes is the speech itself -- somebody far from the microphone, two
people at once, an accent. The tool cannot fix that. What it can do, and never
did, is **say which sentences it is unsure of**, instead of handing all of them
over with the same straight face.

The model already knows. Whisper returns `avg_logprob` for every segment, and
its exponential is the average probability per token. The chain threw it away.

What counts as doubt is a threshold, and a threshold is a measurement. This one
comes from `tools/measure_confidence.py`, which transcribes a meeting whose
words are known and sorts the turns by that figure; see `docs/calibration.md`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from greffier.domain.models import Utterance

UNSURE_BELOW = 0.85
"""Below this, a turn is one to listen to again.

Measured, not guessed. `tools/measure_confidence.py` transcribes a synthesised
meeting whose 114 words are known, then the same recording with white noise
mixed in at four known signal-to-noise ratios:

| Prise | Confiance | Ce que vaut le texte |
|---|---|---|
| propre | 0,95 - 0,97 | fidèle, aux accords près |
| + 10 dB | 0,91 - 0,93 | fidèle, aux accords près |
| + 5 dB | 0,81 | le modèle invente des phrases entières |
| 0 dB | 0,65 - 0,76 | idem |
| - 5 dB | 0,61 - 0,81 | idem |

Two regimes, and nothing observed between 0.81 and 0.91: the threshold goes in
that gap. Above it, the only errors left were agreements -- « celle » for
« celles », « concernant » for « concernés ». Below it, « qui nous réplique
depuis le début de la semaine » for a sentence about a deployment.

What this does not measure: a real voice, a real room, an accent, two people at
once. The figure holds for the machine and the model it was taken on, and it is
a floor rather than a verdict -- above it a turn can still be wrong.
"""

MARK = "(?)"
"""What precedes a doubtful line in the readable transcript.

A mark, not a percentage: somebody reading a transcript wants to know where to
listen again, not to compare two decimals -- the figure itself goes to the
spreadsheet, through `greffier exporter`. Three plain characters rather than a
sign, so that it can be searched for, and not « ≈ », which the window already
uses for a name the tool is proposing.
"""


@dataclass(frozen=True, slots=True)
class Doubts:
    """What a meeting is unsure of, counted."""

    turns: int
    unsure: int
    judged: int

    @property
    def share(self) -> float:
        """Share of the judged turns that are doubtful, 0 when none were."""
        return self.unsure / self.judged if self.judged else 0.0

    @property
    def worth_saying(self) -> bool:
        """Whether this is worth a line on screen.

        One doubtful turn in a two-hour meeting is noise; a tenth of them is
        the difference between reading the minutes and listening again.
        """
        return self.unsure > 0 and self.share >= 0.05


def is_unsure(utterance: Utterance, below: float = UNSURE_BELOW) -> bool:
    """Whether this turn is one to listen to again.

    A turn the engine did not judge is not doubtful: no figure is not a low
    figure, and marking it would teach people to ignore the mark.
    """
    return is_a_low_figure(utterance.confidence, below)


def is_a_low_figure(confidence: float | None, below: float = UNSURE_BELOW) -> bool:
    """The same judgement on the bare figure, for a turn shown live."""
    return confidence is not None and confidence < below


def count(utterances: Iterable[Utterance], below: float = UNSURE_BELOW) -> Doubts:
    """How many turns are doubtful, out of how many the engine judged."""
    kept = list(utterances)
    judged = [u for u in kept if u.confidence is not None]
    return Doubts(
        turns=len(kept),
        unsure=sum(1 for u in judged if is_unsure(u, below)),
        judged=len(judged),
    )


def said_in_french(doubts: Doubts) -> str:
    """The one line the window shows, or nothing at all."""
    if not doubts.worth_saying:
        return ""
    return (
        f"{doubts.unsure} passage{'s' if doubts.unsure > 1 else ''} sur "
        f"{doubts.judged} mérite{'nt' if doubts.unsure > 1 else ''} une "
        f"réécoute : la transcription les marque « {MARK} »."
    )


def worth_listening_again(
    utterances: Sequence[Utterance], below: float = UNSURE_BELOW
) -> list[Utterance]:
    """The doubtful turns, earliest first, for somebody going back to the sound."""
    return sorted(
        (u for u in utterances if is_unsure(u, below)), key=lambda u: u.span.start
    )
