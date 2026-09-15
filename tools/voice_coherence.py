#!/usr/bin/env python3
"""Is a large voice a single person?

The question came up on a real meeting where "Pascal" carried 58 minutes
out of 91, 64.5 % of the speech. It cannot be answered by looking at the
names: the unnamed attendees a large voice would have absorbed show nowhere.
It is answered by looking at **the shape of the cloud**.

The internal coherence of a voice is how much each of its excerpts
resembles its own aggregate. A voice mixing two people has a **lower**
coherence than the others: its aggregate falls between two clouds, hence far
from both. It is a negative sign usable without ground truth.

    python3 tools/voice_coherence.py 2026-09-10_10h10_reunion

The voiceprints come from the cache of `replay_stitching.py`: run it first.
"""

from __future__ import annotations

import argparse
import pickle
import statistics as stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domain.models import Voiceprint  # noqa: E402
from greffier.domain.voiceprints import aggregate, similarity  # noqa: E402

#: Below this, an excerpt no longer resembles its own voice.
FOREIGN = 0.50

#: Under this number of excerpts, a median means nothing.
ENOUGH_EXCERPTS = 12


def cache_of(meeting: str) -> Path:
    return Path("/tmp/greffier-empreintes") / f"{meeting}.pickle"


def coherence(voiceprints: list[Voiceprint]) -> list[float]:
    """How much each excerpt resembles the aggregate of its own voice."""
    ag = aggregate(voiceprints)
    return sorted(similarity(e, ag) for e in voiceprints)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting")
    parser.add_argument("--how-many", type=int, default=6,
                        help="How many voices to examine (the largest)")
    arguments = parser.parse_args()

    cache = cache_of(arguments.meeting)
    if not cache.exists():
        print("The voiceprints are missing: run tools/replay_stitching.py on this "
              "meeting first.", file=sys.stderr)
        return 1
    try:
        per_voice: dict[str, list[Voiceprint]] = pickle.loads(cache.read_bytes())
    except (pickle.UnpicklingError, ModuleNotFoundError, AttributeError, EOFError):
        print("Unreadable cache: run tools/replay_stitching.py on this meeting "
              "again, it will rebuild it.", file=sys.stderr)
        return 1
    largest = sorted(
        per_voice.items(), key=lambda kv: -sum(e.source_duration for e in kv[1])
    )[: arguments.how_many]

    print("== internal coherence: each excerpt against the aggregate of its voice ==")
    print(f"{'voice':>6} {'excerpts':>9} {'seconds':>9} "
          f"{'median':>9} {'1st dec.':>9} {'min':>7}  foreign")
    for voice, voiceprints in largest:
        seconds = sum(e.source_duration for e in voiceprints)
        if len(voiceprints) < ENOUGH_EXCERPTS:
            print(f"{voice:>6} {len(voiceprints):>9} {seconds:>9.0f}"
                  f"   too few excerpts to conclude")
            continue
        values = coherence(voiceprints)
        foreign = sum(1 for v in values if v < FOREIGN)
        print(f"{voice:>6} {len(voiceprints):>9} {seconds:>9.0f} "
              f"{stat.median(values):>9.3f} {values[len(values) // 10]:>9.3f} "
              f"{values[0]:>7.3f}  {foreign:>4} / {len(values)}")

    print("\n== reference: the large voices with each other ==")
    aggregates = {v: aggregate(e) for v, e in largest}
    identifiers = [v for v, _ in largest]
    for i, one in enumerate(identifiers):
        for other in identifiers[i + 1:]:
            print(f"  {one:>6} ↔ {other:<6} {similarity(aggregates[one], aggregates[other]):.3f}")

    print("\nA voice less coherent than its neighbours probably mixes two people.")
    print("More coherent than them, it is a single talkative person.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
