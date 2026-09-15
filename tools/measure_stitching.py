#!/usr/bin/env python3
"""Replays the three passes of the stitching on a recording with a word-for-word reference.

The stitching brings the segmenter's groups down to the number of people:
pairs first, then adoption of the fragments, then consolidation of what has
grown. On the SUMM-RE meeting where a fifth of the time is spoken by two
people at once, it brought four people down to two. This tool says which
pass did it, and what each threshold would have done instead, against the
reference timings rather than against names put down by hand.

For every strategy, the same figures as `measure_corpus.py`, on the turns:
right, wrong and no opinion shares of the speaking time, once every voice is
the person it mostly carries, and the number of voices that would be
announced (ten seconds or more).

    python3 tools/measure_stitching.py --only 036c
    python3 tools/measure_stitching.py --only 036c --pairs 0.75 0.70 --consolidation 0.70 0.80 0.90

The segmentation and the voiceprints are computed once and kept next to the
recording (`*.segments.json`, `*.voiceprints.pickle`); the strategies then
compare in a second.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greffier.domain import voiceprints as domain  # noqa: E402
from greffier.domain.models import Span, SpeakerTurn  # noqa: E402
from greffier.locations import data_folder  # noqa: E402

#: A voice that spoke less than this is not announced, as in the product.
ATTENDEE_SECONDS = 10.0


def raw_turns(audio: Path) -> list[SpeakerTurn]:
    """The segmenter's own groups, before any stitching, kept next to the audio."""
    cache = audio.with_suffix(".segments.json")
    if cache.exists():
        return [
            SpeakerTurn(Span(entry["start"], entry["end"]), entry["voice"])
            for entry in json.loads(cache.read_text(encoding="utf-8"))
        ]
    from greffier.adapters.configuration import Config
    from greffier.adapters.diarisation_sherpa import SherpaDiariser

    config = Config()
    diarisation = config.paths.models / "diarisation"
    diariser = SherpaDiariser(
        segmentation=diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
        voiceprints=diarisation / "nemo_en_titanet_large.onnx",
        device=config.hardware.device,
    )
    turns = diariser.segment(audio, None)
    cache.write_text(
        json.dumps(
            [{"start": t.span.start, "end": t.span.end, "voice": t.voice} for t in turns],
            indent=1,
        ),
        encoding="utf-8",
    )
    return turns


def voiceprints_of(audio: Path, turns: list[SpeakerTurn]) -> dict[str, list[Any]]:
    cache = audio.with_suffix(".voiceprints.pickle")
    if cache.exists():
        try:
            kept: dict[str, list[Any]] = pickle.loads(cache.read_bytes())
            return kept
        except (pickle.UnpicklingError, ModuleNotFoundError, AttributeError, EOFError):
            cache.unlink()
    from greffier.adapters.configuration import Config
    from greffier.adapters.voiceprints_titanet import TitaNetExtractor
    from greffier.application.render import voiceprints_per_voice

    config = Config()
    extractor = TitaNetExtractor(
        config.paths.models / "diarisation" / "nemo_en_titanet_large.onnx",
        device=config.hardware.device,
    )
    per_voice: dict[str, list[Span]] = defaultdict(list)
    for turn in turns:
        per_voice[turn.voice].append(turn.span)
    voiceprints: dict[str, list[Any]] = voiceprints_per_voice(extractor, audio, per_voice)
    cache.write_bytes(pickle.dumps(voiceprints))
    return voiceprints


@dataclass(frozen=True)
class Score:
    label: str
    voices: int
    scraps: int
    right: float
    wrong: float
    no_opinion: float

    def line(self, people: int) -> str:
        return (
            f"{self.label:<44} voices {self.voices:>2}/{people} (+{self.scraps:>2} scraps)  "
            f"right {100 * self.right:5.1f} %  wrong {100 * self.wrong:5.1f} %  "
            f"no opinion {100 * self.no_opinion:4.1f} %"
        )


def truth_of(turn: SpeakerTurn, reference: list[dict[str, Any]]) -> str | None:
    """Who the reference has speaking under this turn, or None when unclear."""
    under: dict[str, float] = defaultdict(float)
    for entry in reference:
        begins = max(turn.span.start, float(entry["start"]))
        covered = min(turn.span.end, float(entry["end"])) - begins
        if covered > 0:
            under[str(entry["speaker"])] += covered
    if not under:
        return None
    speaker, covered = max(under.items(), key=lambda item: item[1])
    return speaker if covered > sum(under.values()) / 2 else None


def score(
    label: str,
    turns: list[SpeakerTurn],
    membership: dict[str, str],
    truths: list[str | None],
) -> Score:
    """The figures of one stitching, weighted by speaking time."""
    carried: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    spoken: dict[str, float] = defaultdict(float)
    for turn, truth in zip(turns, truths, strict=True):
        voice = membership.get(turn.voice, turn.voice)
        spoken[voice] += turn.span.duration
        if truth is not None:
            carried[voice][truth] += turn.span.duration
    person_of = {
        voice: max(seen.items(), key=lambda item: item[1])[0] for voice, seen in carried.items()
    }
    right = wrong = blank = judged = 0.0
    for turn, truth in zip(turns, truths, strict=True):
        if truth is None:
            continue
        judged += turn.span.duration
        voice = membership.get(turn.voice, turn.voice)
        if voice not in person_of:
            blank += turn.span.duration
        elif person_of[voice] == truth:
            right += turn.span.duration
        else:
            wrong += turn.span.duration
    judged = judged or 1.0
    attendees = sum(1 for seconds in spoken.values() if seconds >= ATTENDEE_SECONDS)
    return Score(
        label,
        attendees,
        len(spoken) - attendees,
        right / judged,
        wrong / judged,
        blank / judged,
    )


def strategies(
    voiceprints: dict[str, list[Any]],
    pairs: list[float],
    adoptions: list[float],
    consolidations: list[float],
) -> list[tuple[str, dict[str, str]]]:
    """Each pass alone, then the product's three passes at every threshold asked."""
    none = {voice: voice for voice in voiceprints}
    kept: list[tuple[str, dict[str, str]]] = [("segmenter alone", none)]
    for threshold in pairs:
        kept.append((f"pairs {threshold:.2f}", domain.join_voices(voiceprints, threshold)))
    product = domain.join_voices(voiceprints)
    for threshold in adoptions:
        kept.append(
            (
                f"pairs {domain.JOIN_THRESHOLD:.2f} + adoption {threshold:.2f}",
                domain.adopt_fragments(voiceprints, product, threshold=threshold),
            )
        )
    for threshold in consolidations:
        kept.append(
            (
                f"pairs + adoption + consolidation {threshold:.2f}",
                domain.stitch(voiceprints, seuil_consolidation=threshold),
            )
        )
    kept.append(("product (0.75 / 0.45 / 0.70)", domain.stitch(voiceprints)))
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, default=data_folder() / "corpus")
    parser.add_argument("--only", default="summre")
    parser.add_argument("--pairs", type=float, nargs="*", default=[0.75, 0.65, 0.55, 0.50])
    parser.add_argument("--adoption", type=float, nargs="*", default=[0.45, 0.55, 0.65])
    parser.add_argument("--consolidation", type=float, nargs="*", default=[0.70, 0.80, 0.90])
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
        if "start" not in reference["turns"][0]:
            print(f"{audio.stem}: reference without timings, skipped")
            continue
        turns = raw_turns(audio)
        voiceprints = voiceprints_of(audio, turns)
        truths = [truth_of(turn, reference["turns"]) for turn in turns]
        people = len({truth for truth in truths if truth is not None})
        print(f"=== {audio.stem}: {len(turns)} segmenter turns, {people} people")
        results = [
            score(label, turns, membership, truths)
            for label, membership in strategies(
                voiceprints, options.pairs, options.adoption, options.consolidation
            )
        ]
        for result in results:
            print(result.line(people))
        audio.with_suffix(".stitching.json").write_text(
            json.dumps([vars(r) for r in results], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
