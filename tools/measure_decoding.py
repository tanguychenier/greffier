#!/usr/bin/env python3
"""Replays the decoding settings on the recordings whose reference is word for word.

On a synthesised meeting the sixteen combinations of `beam_size`,
`vad_filter`, `condition_on_previous_text` and `temperature` gave the same
1.75 % word error rate (`what-is-left.md`, 2026-09-12). Real speech may tell
them apart; this is where that is settled, with the two figures decoding can
move: the word error rate and the rare terms found. Attribution does not
depend on decoding and is not repeated here.

The audio goes through the same preparation as in the chain (level
normalisation by ffmpeg), the model is opened once for all the combinations,
and every transcript is kept next to the recording so that a combination
already measured is not decoded again.

    python3 tools/measure_decoding.py                  # the SUMM-RE recordings
    python3 tools/measure_decoding.py --only 036c      # one of them
    python3 tools/measure_decoding.py --seed "Réunion de travail."   # with a prompt

The result is one line per combination, sorted by error rate, and a JSON
file `<recording>.decoding.json` for the table in `docs/corpus.md`.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from measure_corpus import normalise, rare_terms, terms_found, word_error_rate  # noqa: E402

from greffier.locations import data_folder  # noqa: E402

#: The four settings and their two values each, hence sixteen combinations.
#: The first value of each is what the chain uses today, so the first
#: combination is the product as shipped. The temperature tuple is
#: faster-whisper's fallback ladder, tried when the model is unsure; 0 is
#: greedy and deterministic.
SETTINGS: dict[str, tuple[Any, Any]] = {
    "beam_size": (5, 1),
    "vad_filter": (True, False),
    "condition_on_previous_text": (True, False),
    "temperature": ((0.0, 0.2, 0.4, 0.6, 0.8, 1.0), 0.0),
}


def combinations() -> list[dict[str, Any]]:
    names = list(SETTINGS)
    return [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(SETTINGS[name] for name in names))
    ]


def label(settings: dict[str, Any]) -> str:
    temperature = "ladder" if isinstance(settings["temperature"], tuple) else "0"
    return (
        f"beam={settings['beam_size']} vad={int(settings['vad_filter'])} "
        f"cond={int(settings['condition_on_previous_text'])} temp={temperature}"
    )


def prepared(audio: Path, folder: Path) -> Path:
    from greffier.adapters.audio_ffmpeg import FfmpegRecorder

    recorder = FfmpegRecorder(device="")
    return recorder.prepare_transcript(audio, folder / f"{audio.stem}-niveau.wav")


def transcribe(model: Any, audio: Path, settings: dict[str, Any], seed: str) -> list[str]:
    segments, _ = model.transcribe(
        str(audio), language="fr", initial_prompt=seed or None, **settings
    )
    return [segment.text.strip() for segment in segments]


def opened_model() -> Any:
    """large-v3 on the card, the libraries shown to the loader first, as in the chain."""
    from greffier.adapters import cuda

    cuda.show_to_the_loader()
    from faster_whisper import WhisperModel

    return WhisperModel("large-v3", device="cuda", compute_type="int8")


def measure(audio: Path, seed: str, only_defaults: bool) -> list[dict[str, Any]]:

    reference = json.loads(audio.with_suffix(".reference.json").read_text(encoding="utf-8"))
    turns = sorted(reference["turns"], key=lambda turn: float(turn["start"]))
    reference_words = [word for turn in turns for word in normalise(str(turn["text"]))]
    terms = rare_terms(reference_words)

    cache = audio.with_suffix(".decoding.json")
    rows: list[dict[str, Any]] = (
        json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []
    )
    done = {(row["label"], row["seed"]) for row in rows}
    wanted = [combinations()[0]] if only_defaults else combinations()
    todo = [settings for settings in wanted if (label(settings), seed) not in done]
    if not todo:
        return rows

    model = opened_model()
    with tempfile.TemporaryDirectory() as folder:
        levelled = prepared(audio, Path(folder))
        for settings in todo:
            started = time.monotonic()
            texts = transcribe(model, levelled, settings, seed)
            elapsed = time.monotonic() - started
            hypothesis = [word for text in texts for word in normalise(text)]
            found, total = terms_found(terms, hypothesis)
            row = {
                "recording": audio.stem,
                "label": label(settings),
                "seed": seed,
                "word_error_rate": word_error_rate(reference_words, hypothesis),
                "rare_terms_found": found,
                "rare_terms": total,
                "hypothesis_words": len(hypothesis),
                "seconds": round(elapsed, 1),
            }
            rows.append(row)
            cache.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            print_row(row)
    return rows


def print_row(row: dict[str, Any]) -> None:
    seed = " seeded" if row["seed"] else ""
    print(
        f"{row['recording']:<18} {row['label']:<34}{seed:<7} "
        f"error {100 * row['word_error_rate']:5.1f} %  "
        f"terms {row['rare_terms_found']:>3}/{row['rare_terms']:<3}  "
        f"{row['seconds']:6.1f} s"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, default=data_folder() / "corpus")
    parser.add_argument("--only", default="summre")
    parser.add_argument("--seed", default="")
    parser.add_argument("--defaults-only", action="store_true")
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
        rows = measure(audio, options.seed, options.defaults_only)
        print(f"--- {audio.stem}, best to worst")
        for row in sorted(rows, key=lambda row: row["word_error_rate"]):
            print_row(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
