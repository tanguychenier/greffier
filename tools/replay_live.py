#!/usr/bin/env python3
"""Replays the live thread on a labelled meeting, with no audio and no model.

The voiceprints are already computed; what is replayed is the only thing that
decides during a sitting: **the order of time**. Live only knows the past,
where the post-meeting stitching sees everything. Comparing the two says
where the room for progress is, and on the meeting of 2026-09-10 the answer
contradicted intuition: no start-up gradient, the dip is in the middle.

The chronology comes from the meeting's turns and not from the order of the
cache: without it the figure measures nothing.

    python3 tools/replay_live.py 2026-09-10_10h10_reunion

The voiceprints come from the cache of `replay_stitching.py`: run it first.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domain.live import Block, LiveThread  # noqa: E402
from greffier.domain.models import Span, Utterance, Voiceprint  # noqa: E402
from greffier.domain.names import join_namesakes  # noqa: E402
from greffier.locations import data_folder  # noqa: E402

#: Every how many sentences the thread stitches its voices, as in a sitting.
STITCH_EVERY = 40

#: How many slices of time to look for a gradient in.
SLICES = 6


def in_time_order(
    meeting: dict, per_voice: dict[str, list[Voiceprint]], named: set[str]
) -> list[tuple[float, float, str, Voiceprint]]:
    """The turns in the order of time, with their voiceprint and their true voice.

    The Nth voiceprint of a voice matches the Nth turn of that voice: it is the
    order the cache was built in, and what makes the chronology recoverable
    without listening to the audio again.
    """
    ranks: Counter = Counter()
    sequence = []
    for turn in sorted(meeting["tours"], key=lambda t: float(t["debut"])):
        voice = str(turn["voix"])
        rank = ranks[voice]
        ranks[voice] += 1
        voiceprints = per_voice.get(voice, [])
        if voice not in named or rank >= len(voiceprints):
            continue
        sequence.append(
            (float(turn["debut"]), float(turn["fin"]), voice, voiceprints[rank])
        )
    return sequence


def named_truth(meeting: dict) -> set[str]:
    """The named voices, one per person.

    Goes through the joining of namesakes: on the meeting of 2026-09-10 the
    file carries sixteen named voices, **nine of them "Lise"**. Counting them
    as nine people would distort the ground truth as much as the minutes.
    """
    names = {str(v): name for v, name in (meeting.get("noms") or {}).items()}
    weight: Counter = Counter()
    for turn in meeting["tours"]:
        weight[str(turn["voix"])] += float(turn["fin"]) - float(turn["debut"])
    membership = join_namesakes(names, dict(weight))
    return {voice for voice, kept in membership.items() if voice == kept}


def replay(sequence: list) -> tuple[LiveThread, list[tuple[str, int]], list[bool]]:
    """Redoes the thread sentence by sentence, and says which ones are right.

    A voice of the thread stands for the majority person it holds: the thread
    knows no names, and judging it on its identifiers would make no sense.
    """
    thread = LiveThread()
    attributed: list[tuple[str, int]] = []
    for start, end, true_voice, voiceprint in sequence:
        voice = thread.attach(voiceprint=voiceprint, local=False)
        thread.record_turn(
            Block(
                utterances=(Utterance(span=Span(start, end), text="x"),),
                local=False,
            ),
            voice,
        )
        attributed.append((true_voice, len(thread.turns)))
        if len(attributed) % STITCH_EVERY == 0:
            thread.stitch()
    thread.stitch()
    final = {t.number: t.voice for t in thread.turns}
    groups: dict[str, Counter] = {}
    for true_voice, number in attributed:
        groups.setdefault(final.get(number, "?"), Counter())[true_voice] += 1
    majority = {v: c.most_common(1)[0][0] for v, c in groups.items()}
    right = [majority.get(final.get(n)) == true_voice for true_voice, n in attributed]
    return thread, attributed, right


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting")
    arguments = parser.parse_args()

    path = data_folder() / "reunions" / f"{arguments.meeting}.json"
    cache = Path("/tmp/greffier-empreintes") / f"{arguments.meeting}.pickle"
    if not cache.exists():
        print("The voiceprints are missing: run tools/replay_stitching.py on this "
              "meeting first.", file=sys.stderr)
        return 1
    meeting = json.loads(path.read_text())
    try:
        per_voice = pickle.loads(cache.read_bytes())
    except (pickle.UnpicklingError, ModuleNotFoundError, AttributeError, EOFError):
        print("Unreadable cache: run tools/replay_stitching.py on this meeting "
              "again, it will rebuild it.", file=sys.stderr)
        return 1
    named = named_truth(meeting)
    if not named:
        print("No named voice: there is no ground truth to compare with.",
              file=sys.stderr)
        return 1

    sequence = in_time_order(meeting, per_voice, named)
    if not sequence:
        print("No labelled turn.", file=sys.stderr)
        return 1
    thread, attributed, right = replay(sequence)

    print(f"{len(sequence)} labelled turns, from {sequence[0][0] / 60:.0f} "
          f"to {sequence[-1][1] / 60:.0f} min")
    print(f"voices created: {len(thread.voice) - 1} for {len(named)} named people")
    print(f"live accuracy: {sum(right)}/{len(right)} = {sum(right) / len(right):.1%}")

    size = len(right) // SLICES
    print(f"\n{'slice':>10} {'minutes':>16} {'sentences':>9} {'accuracy':>9}")
    for i in range(SLICES):
        a = i * size
        b = (i + 1) * size if i < SLICES - 1 else len(right)
        part = right[a:b]
        print(f"{i + 1:>5}/{SLICES:<4} {sequence[a][0] / 60:>7.0f} → "
              f"{sequence[b - 1][1] / 60:<6.0f} {len(part):>9} "
              f"{sum(part) / len(part):>8.1%}")

    print("\n== what the voices of the thread weigh ==")
    final = {t.number: t.voice for t in thread.turns}
    weight: Counter = Counter()
    turns: Counter = Counter()
    content: dict[str, Counter] = {}
    for true_voice, number in attributed:
        voice = final.get(number, "?")
        turns[voice] += 1
        content.setdefault(voice, Counter())[true_voice] += 1
    for turn in thread.turns:
        weight[final.get(turn.number, "?")] += turn.span.duration
    print(f"{'voice':>6} {'turns':>6} {'seconds':>9}  who it holds")
    for voice, seconds in weight.most_common():
        held = ", ".join(f"{n} × {q}" for n, q in content.get(voice, Counter()).most_common())
        print(f"{voice:>6} {turns[voice]:>6} {seconds:>9.0f}  {held}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
