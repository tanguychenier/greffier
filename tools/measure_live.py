#!/usr/bin/env python3
"""Measures the live words against the reference, slice by slice, off line.

The live thread never sees the whole recording: it transcribes what was
written since the last slice, with a window of context before it, and keeps
what falls inside the slice. Reported from use: the words shown live did not
match what was said. This tool replays exactly that slicing, through the
product's own `Watcher.transcription_turn`, but drives the clock itself, so a
twenty-minute meeting is measured in the time the model takes rather than in
twenty minutes. The timing of a real replay is `greffier rejouer`'s business.

    python3 tools/measure_live.py --only 032a
    python3 tools/measure_live.py --only 032a --period 5 --context 0

For each setting: the word error rate of the live text against the
reference, the number of slices, and the seconds of model time per slice.
The final transcription of the same file (`measure_corpus.py`) is the figure
to hold it against: live can only be worse, the question is by how much.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from measure_corpus import normalise, rare_terms, terms_found, word_error_rate  # noqa: E402

from greffier.application.watch import SLICE_POLL as STEP_S  # noqa: E402
from greffier.application.watch import SLICE_SLACK_S as SLACK_S  # noqa: E402
from greffier.locations import data_folder  # noqa: E402


def quiet_moment(audio: Path, from_s: float, until_s: float) -> float:
    """The first moment nobody talks between the two, or the last one."""
    from greffier.adapters.live_levels import read_level
    from greffier.domain.channels import WhoSpeaks

    at = from_s
    while at < until_s:
        reading = read_level(audio, up_to=at)
        if reading is not None and reading.who is WhoSpeaks.NOBODY:
            return at
        at += STEP_S
    return until_s


def cuts(duration: float, period: float, on_silence: Path | None = None) -> Iterator[float]:
    """Where each slice ends: every period, or at the next quiet moment past it.

    The last slice ends where the recording does, once. Written as a loop
    on the clock, the cut on silence stayed on the last slice for ever: the
    end of the file is a quiet moment, and the clock never moved past it.
    """
    written = period
    while True:
        cut = min(written, duration)
        if on_silence is not None and cut < duration:
            cut = min(duration, quiet_moment(on_silence, cut, cut + SLACK_S))
        yield cut
        if cut >= duration:
            return
        written = cut + period


def live_words(
    audio: Path, period: float, context_s: float, overlap_s: float, levelled: bool,
    model: str = "", on_silence: bool = False,
) -> tuple[list[str], int, float]:
    """The words the live thread would have shown, the slices, the model seconds.

    The real thread, not a stand-in: what it shows is what the slices hand
    over **minus** what the overlap brings back a second time, and a stand-in
    that kept everything measured 75 % of errors on a file the final
    transcription reads at 24 %.
    """
    import soundfile as sf

    from greffier.adapters.configuration import Config
    from greffier.application import watch
    from greffier.application.follow import Position
    from greffier.application.watch import Watcher
    from greffier.domain.instructions import WatchRules
    from greffier.wiring import _audio_recorder, follower, light_transcriber

    config = Config()
    duration = sf.info(str(audio)).duration
    watch.CONTEXT_S = context_s
    watch.OVERLAP = overlap_s
    slices = 0
    spent = 0.0
    # Its own data folder: the thread's log and the voices it founds belong
    # to the measurement, not to the machine's meetings, and go with it.
    with tempfile.TemporaryDirectory(prefix="measure-live-") as data, \
            tempfile.TemporaryDirectory() as job:
        config.paths.data = Path(data)
        if model:
            config.live.model = model
        the_follower = follower(config, audio.stem)
        watcher = Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=config.paths.propositions / f"{audio.stem}.jsonl",
            transcriber=light_transcriber(config),
            follower=the_follower,
            preparer=_audio_recorder(config) if levelled else None,
            language="fr",
            slice_period=period,
        )
        for cut in cuts(duration, period, audio if on_silence else None):
            where = Position(chunk=audio, written=cut, offset=0.0)
            started = time.monotonic()
            watcher.transcription_turn(where, Path(job), let_speak=False)
            spent += time.monotonic() - started
            slices += 1
        words = [word for turn in the_follower.thread.turns for word in normalise(turn.text)]
    return words, slices, spent / max(1, slices)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, default=data_folder() / "corpus")
    parser.add_argument("--only", default="summre")
    parser.add_argument("--period", type=float, default=10.0)
    parser.add_argument("--context", type=float, default=50.0)
    parser.add_argument("--overlap", type=float, default=5.0)
    parser.add_argument("--raw", action="store_true", help="skip the level normalisation")
    parser.add_argument("--model", default="", help="the live model, default from the settings")
    parser.add_argument("--on-silence", action="store_true",
                        help="cut each slice when the room goes quiet, up to three seconds late")
    options = parser.parse_args()

    recordings = sorted(
        audio
        for audio in options.corpus.glob("*.wav")
        if options.only in audio.stem and audio.with_suffix(".reference.json").exists()
    )
    if not recordings:
        print(f"No recording with a reference in {options.corpus}")
        return 1
    for audio in recordings:
        reference = json.loads(audio.with_suffix(".reference.json").read_text(encoding="utf-8"))
        turns = reference["turns"]
        if "start" not in turns[0]:
            print(f"{audio.stem}: reference without timings, skipped")
            continue
        in_order = sorted(turns, key=lambda t: float(t["start"]))
        reference_words = [w for t in in_order for w in normalise(str(t["text"]))]
        words, slices, per_slice = live_words(
            audio, options.period, options.context, options.overlap, not options.raw,
            options.model, options.on_silence,
        )
        found, wanted = terms_found(rare_terms(reference_words), words)
        row = {
            "recording": audio.stem,
            "model": options.model or "settings",
            "cut": "silence" if options.on_silence else "clock",
            "period": options.period,
            "context": options.context,
            "overlap": options.overlap,
            "levelled": not options.raw,
            "word_error_rate": word_error_rate(reference_words, words),
            "rare_terms_found": found,
            "rare_terms": wanted,
            "hypothesis_words": len(words),
            "slices": slices,
            "seconds_per_slice": round(per_slice, 2),
        }
        label = (
            f"{options.model or 'settings'} period {options.period:.0f} s, "
            f"context {options.context:.0f} s, overlap {options.overlap:.0f} s"
            + (", cut on silence" if options.on_silence else "")
        )
        print(
            f"{audio.stem:<18} {label:<44} error {100 * row['word_error_rate']:5.1f} %  "
            f"terms {found:>3}/{wanted:<3}  {slices:>4} slices  {per_slice:5.2f} s/slice"
        )
        cache = audio.with_suffix(".live.json")
        rows = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []
        rows.append(row)
        cache.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
