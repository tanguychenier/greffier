#!/usr/bin/env python3
"""Compares voiceprint extractors on a meeting already labelled.

The choice of a voiceprint model decides everything downstream: the
attachment threshold, the number of voices shown, the accuracy of the
attributions. It was made once, at the start of the project, and never
measured again, while the engine's catalogue offers twenty-one.

What this tool measures is not the accuracy on a speaker recognition set,
where all these models are excellent. It is the only thing that counts
here: **on short excerpts, the gap between "same person" and "different
people"**. That gap is what makes a threshold possible, and it is what was
missing when the thread showed a hundred and eleven voices.

    python3 tools/compare_extractors.py 2026-09-09_16h36_reunion

The ground truth comes from the final stitching of the meeting, which was
checked against the names put down by hand. The voiceprints are cached per
model: computing costs a few minutes, comparing is then immediate.

**Do not run during a meeting**: the extraction takes all the processor the
live transcription is using.
"""

from __future__ import annotations

import argparse
import json
import pickle
import statistics as stat
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domain.voiceprints import aggregate, similarity, stitch  # noqa: E402
from greffier.locations import data_folder  # noqa: E402

CATALOGUE = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/")

#: The candidates, and why each one.
#:
#: TitaNet is the one in place. The others are reputed better on the speaker
#: verification rankings, but those rankings bear on excerpts of several
#: seconds, spoken alone in front of a microphone, which is not our case.
#: Hence the measurement.
CANDIDATES = {
    "titanet_large": "nemo_en_titanet_large.onnx",
    "campplus_LM": "wespeaker_en_voxceleb_CAM++_LM.onnx",
    "resnet293_LM": "wespeaker_en_voxceleb_resnet293_LM.onnx",
    "eres2netv2": "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
}

#: The length of the excerpts measured. It is that of a live slice block,
#: hence the one where the choice of model is decided.
WINDOW = 2.5
CACHE = Path("/tmp/greffier-extracteurs")


def download(name: str, target: Path) -> Path:
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {name}…", file=sys.stderr)
    partial = target.with_suffix(".partial")
    with urllib.request.urlopen(CATALOGUE + name) as stream, partial.open("wb") as output:
        while chunk := stream.read(1 << 20):
            output.write(chunk)
    partial.replace(target)
    return target


def voiceprints(model: Path, meeting: dict, key: str) -> list:
    """One voiceprint per window, in the order of time. Cached."""
    file = CACHE / f"{key}.pickle"
    if file.exists():
        return pickle.loads(file.read_bytes())

    import numpy as np
    import soundfile as sf

    from greffier.adapters.voiceprints_titanet import MINIMUM_LENGTH, TitaNetExtractor

    extractor = TitaNetExtractor(model)
    rendered = []
    with sf.SoundFile(str(meeting["audio"])) as stream:
        frequency = stream.samplerate
        for turn in meeting["tours"]:
            at_instant = turn["debut"]
            while at_instant + MINIMUM_LENGTH <= turn["fin"]:
                until = min(at_instant + WINDOW, turn["fin"])
                stream.seek(int(at_instant * frequency))
                block = stream.read(int((until - at_instant) * frequency),
                                    dtype="float32", always_2d=True)
                if len(block) >= MINIMUM_LENGTH * frequency:
                    signal = np.ascontiguousarray(block.mean(axis=1))
                    rendered.append((at_instant, extractor.extract(signal, frequency)))
                at_instant = until
    rendered.sort()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(pickle.dumps(rendered))
    return rendered


def truth(meeting: dict) -> list:
    """Who spoke when, according to the final stitching of the meeting."""
    cache = Path("/tmp/greffier-empreintes") / f"{meeting['identifiant']}.pickle"
    if not cache.exists():
        raise SystemExit(
            "The ground truth is missing: run tools/replay_stitching.py on this "
            "meeting first."
        )
    try:
        per_voice = pickle.loads(cache.read_bytes())
    except (pickle.UnpicklingError, ModuleNotFoundError, AttributeError, EOFError):
        print("Unreadable cache: run tools/replay_stitching.py on this meeting "
              "again, it will rebuild it.", file=sys.stderr)
        return 1
    membership = stitch(per_voice)
    return sorted(
        (t["debut"], t["fin"], membership.get(str(t["voix"]), str(t["voix"])))
        for t in meeting["tours"]
    )


def grade(labelled: list) -> dict:
    """The gap between "same person" and "different people".

    On the aggregates, because that is the comparison the attachment makes: a
    sentence against an accumulated voice, never two sentences with each other.
    """
    per = defaultdict(list)
    for who, voiceprint in labelled:
        per[who].append(voiceprint)
    largest = sorted(per, key=lambda q: -len(per[q]))[:3]
    if len(largest) < 2:
        return {}
    same, others = [], []
    for who in largest:
        reference = aggregate(per[who][:40])
        same += [similarity(e, reference) for e in per[who][40:140]]
        for other in largest:
            if other != who:
                others += [similarity(e, reference) for e in per[other][40:140]]
    if len(same) < 10 or len(others) < 10:
        return {}
    same.sort()
    others.sort()
    return {
        "same": stat.median(same),
        "same_low": same[len(same) // 10],
        "other": stat.median(others),
        "other_high": others[9 * len(others) // 10],
        # What decides: the room left between the two distributions. A
        # negative gap means no threshold separates them cleanly.
        "margin": same[len(same) // 10] - others[9 * len(others) // 10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting")
    arguments = parser.parse_args()

    path = data_folder() / "reunions" / f"{arguments.meeting}.json"
    meeting = json.loads(path.read_text())
    meeting["identifiant"] = arguments.meeting
    turns = truth(meeting)

    def who(at_instant: float) -> str | None:
        for start, end, voice in turns:
            if start <= at_instant < end:
                return voice
        return None

    print(f"{len(turns)} turns, windows of {WINDOW} s\n")
    print(f"{'model':16} {'same':>7} {'decile':>7} │ {'other':>7} {'decile':>7} │ "
          f"{'margin':>7} {'ms/excerpt':>11}")
    print("─" * 74)
    for key, name in CANDIDATES.items():
        model = download(name, CACHE / name)
        started = time.time()
        excerpts = voiceprints(model, meeting, key)
        cost = 1000 * (time.time() - started) / max(1, len(excerpts))
        labelled = [(who(t), e) for t, e in excerpts]
        scores = grade([(q, e) for q, e in labelled if q])
        if not scores:
            print(f"{key:16} not enough labelled material")
            continue
        print(f"{key:16} {scores['same']:7.3f} {scores['same_low']:7.3f} │ "
              f"{scores['other']:7.3f} {scores['other_high']:7.3f} │ "
              f"{scores['margin']:+7.3f} {cost:10.1f}")
    print("\nThe margin is what decides: it is the room left between the first "
          "decile\nof the same and the ninth of the others. Negative, no "
          "threshold separates them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
