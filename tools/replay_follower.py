#!/usr/bin/env python3
"""Puts the words a live thread showed through the follower again.

The transcriber is the slow part of the live thread, and the part a change
to the attribution never touches. Given the log a meeting left behind
(`direct/<meeting>.jsonl`) and its recording, this cuts the very slices the
watch cut and hands the follower the sentences of the log instead of the
transcriber's, so that who-said-what is measured in the time the voiceprints
take rather than in the time of the meeting.

    python3 tools/replay_follower.py direct/2026-09-10_14h00_reunion.jsonl reunion.wav
    python3 tools/replay_follower.py thread.jsonl reunion.wav --data ~/.local/share/greffier

The replayed thread is written next to the log (`<log>.replayed.jsonl`) and
printed voice by voice: how many sentences each carried, and the name it
ended up with. `tools/measure_bank.py --replay` judges the same replay
against the SUMM-RE reference.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greffier.locations import data_folder  # noqa: E402

OVERLAP_S = 5.0


def turns_of(log: Path) -> list[dict[str, Any]]:
    """The sentences of a live log, in the order they were shown."""
    turns = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        read = json.loads(line)
        if read.get("genre") == "tour" and read.get("texte"):
            turns.append(read)
    return sorted(turns, key=lambda t: (t["debut"], t["numero"]))


def slices(duration: float, period: float, overlap: float = OVERLAP_S) -> list[tuple[float, float]]:
    """The slices the watch cuts: one per period, each reaching back a little."""
    found: list[tuple[float, float]] = []
    written = period
    while True:
        end = min(written, duration)
        found.append((max(0.0, end - period - overlap), end))
        if end >= duration:
            return found
        written += period


def replay_through(follower: Any, log: Path, audio: Path, period: float) -> Any:
    """Feeds the follower the log's sentences slice by slice; returns its thread."""
    import soundfile as sf

    from greffier.application.watch import extract_slice
    from greffier.domain.models import Span, Utterance

    remaining = turns_of(log)
    duration = sf.info(str(audio)).duration
    with tempfile.TemporaryDirectory() as job:
        for start, end in slices(duration, period):
            last = end >= duration
            due = [t for t in remaining if t["fin"] <= end or last]
            if not due:
                continue
            remaining = [t for t in remaining if t not in due]
            slice_ = extract_slice(audio, start, end, Path(job) / "tranche.wav")
            if slice_ is None:
                continue
            utterances = [
                Utterance(
                    span=Span(max(0.0, t["debut"] - start), max(0.0, t["fin"] - start)),
                    text=t["texte"], confidence=t.get("confiance"),
                )
                for t in due
            ]
            follower.take_in(slice_, utterances, offset=start)
    return follower.thread


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("log", type=Path, help="the live log, direct/<meeting>.jsonl")
    parser.add_argument("audio", type=Path, help="the recording of the same meeting")
    parser.add_argument("--data", type=Path, default=data_folder(),
                        help="the data folder whose voice bank to use")
    parser.add_argument("--period", type=float, default=10.0)
    options = parser.parse_args()

    from greffier.adapters.configuration import Config
    from greffier.application.follow import files
    from greffier.wiring import follower

    config = Config(paths={"donnees": str(options.data)})
    the_follower = follower(config, options.log.stem)
    the_follower.log, the_follower.requests = files(
        options.log.parent, f"{options.log.stem}.replayed"
    )
    the_follower.log.unlink(missing_ok=True)
    thread = replay_through(the_follower, options.log, options.audio, options.period)

    carried = Counter(turn.voice for turn in thread.turns)
    print(f"{len(thread.turns)} sentences replayed, {len(carried)} voices; "
          f"the thread is in {the_follower.log}")
    for voice, count in carried.most_common():
        known = thread.voice[voice]
        print(f"  {thread.label(voice):<16} {count:>4} sentences  "
              f"{known.certainty.value}  {known.confidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
