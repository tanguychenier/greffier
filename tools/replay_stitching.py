#!/usr/bin/env python3
"""Replays the stitching of the voices on a meeting already recorded.

The stitching decides how many people the minutes announce. Setting it by
guess costs dearly: a real 92-minute meeting came out as **298 voices for
three people around a table**. This tool replays the decision on that very
meeting, with its real voiceprints, and scores it against the names the user
put down by hand, the only ground truth available.

    python3 tools/replay_stitching.py 2026-09-09_16h36_reunion

The voiceprints are computed once then cached: they cost a few minutes, the
strategies then compare in a second.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from greffier.domain import voiceprints as domain  # noqa: E402
from greffier.domain.models import Span, Voiceprint  # noqa: E402
from greffier.locations import data_folder  # noqa: E402


def voiceprints_per_voice(meeting: dict, cache: Path) -> dict[str, list[Voiceprint]]:
    """One list of voiceprints per voice, computed once and kept.

    A cache written by an older version does not stop the run: a rename of a
    module makes it unreadable, and recomputing costs minutes where a crash
    costs the measurement.
    """
    if cache.exists():
        try:
            return pickle.loads(cache.read_bytes())
        except (pickle.UnpicklingError, ModuleNotFoundError, AttributeError, EOFError):
            print(f"Cache illisible ({cache.name}), il est refait.", file=sys.stderr)
            cache.unlink(missing_ok=True)

    import numpy as np
    import soundfile as sf

    from greffier.adapters.voiceprints_titanet import (
        MAXIMUM_LENGTH,
        MINIMUM_LENGTH,
        TitaNetExtractor,
    )

    model = data_folder() / "modeles/diarisation/nemo_en_titanet_large.onnx"
    extractor = TitaNetExtractor(model)

    per_voice: dict[str, list[Span]] = defaultdict(list)
    for turn in meeting["tours"]:
        per_voice[str(turn["voix"])].append(Span(turn["debut"], turn["fin"]))

    outcome: dict[str, list[Voiceprint]] = defaultdict(list)
    # One pass over the file: `extract_spans` reads it whole for every voice,
    # which would be 298 reads of a 531 MB file.
    with sf.SoundFile(str(meeting["audio"])) as file:
        frequency = file.samplerate
        total = sum(len(v) for v in per_voice.values())
        done = 0
        for voice, spans in per_voice.items():
            for span in spans:
                done += 1
                if done % 100 == 0:
                    print(f"  {done}/{total} excerpts…", file=sys.stderr)
                if span.duration < MINIMUM_LENGTH:
                    continue
                start, end = span.start, span.end
                if end - start > MAXIMUM_LENGTH:
                    middle = (start + end) / 2
                    start, end = middle - MAXIMUM_LENGTH / 2, middle + MAXIMUM_LENGTH / 2
                file.seek(int(start * frequency))
                block = file.read(int((end - start) * frequency), dtype="float32",
                                    always_2d=True)
                if len(block) < MINIMUM_LENGTH * frequency:
                    continue
                signal = np.ascontiguousarray(block.mean(axis=1))
                outcome[voice].append(extractor.extract(signal, frequency))

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(dict(outcome)))
    return dict(outcome)


def note(membership: dict[str, str], meeting: dict,
          per_voice: dict[str, list[Voiceprint]]) -> dict:
    """What a stitching is worth, against the names put down by hand."""
    truth = {str(v): n for v, n in meeting["noms"].items()}
    duration = defaultdict(float)
    for turn in meeting["tours"]:
        voice = membership.get(str(turn["voix"]), str(turn["voix"]))
        duration[voice] += turn["fin"] - turn["debut"]

    groups: dict[str, Counter] = defaultdict(Counter)
    for voice, name in truth.items():
        groups[membership.get(voice, voice)][name] += sum(
            e.source_duration for e in per_voice.get(voice, [])) or 1.0

    mixed = {g: dict(c) for g, c in groups.items() if len(c) > 1}
    split = Counter()
    for c in groups.values():
        split[c.most_common(1)[0][0]] += 1
    total = sum(duration.values()) or 1.0
    largest = sorted(duration.items(), key=lambda x: -x[1])[:6]
    return {
        "voices": len(set(membership.values())),
        "mixed": mixed,
        "split": dict(split),
        "largest": [(g, round(s), round(100 * s / total)) for g, s in largest],
    }


def adoption(per_voice, threshold, margin, material) -> dict[str, str]:
    """Attaches the small groups to the large one they resemble most.

    The pair-wise stitching stops as soon as no pair passes its threshold, and
    then leaves hundreds of isolated fragments. The question asked here is the
    voice bank's, inside a single meeting: "which of the established groups
    resembles it most, and **clearly** most". Threshold and margin, then, and
    not a threshold alone.
    """
    membership = domain.join_voices(per_voice)
    groups: dict[str, list[Voiceprint]] = defaultdict(list)
    for voice, into in membership.items():
        groups[into].extend(per_voice.get(voice, []))
    groups = {g: e for g, e in groups.items() if e}
    materials = {g: sum(x.source_duration for x in e) for g, e in groups.items()}
    established = {g: domain.aggregate(e) for g, e in groups.items() if materials[g] >= material}
    if not established:
        return membership
    for small, voiceprints in groups.items():
        if small in established:
            continue
        aggregate_of = domain.aggregate(voiceprints)
        ranking = sorted(
            ((domain.similarity(aggregate_of, a), g) for g, a in established.items()),
            key=lambda x: (-x[0], x[1]),
        )
        best, winner = ranking[0]
        second = ranking[1][0] if len(ranking) > 1 else -1.0
        if best >= threshold and best - second >= margin:
            for voice, into in membership.items():
                if into == small:
                    membership[voice] = winner
    return membership


def consolidation(
    per_voice, adoption_threshold, margin, material, final_threshold
) -> dict[str, str]:
    """Adoption, then the established groups compare with each other.

    Once the fragments are attached, an established group carries minutes of
    speech and no longer a few seconds: its aggregate stops being noisy, and
    two groups that are the same person can finally recognise each other at a
    threshold fragments would not have deserved.
    """
    membership = adoption(per_voice, adoption_threshold, margin, material)
    while True:
        groups: dict[str, list[Voiceprint]] = defaultdict(list)
        for voice, into in membership.items():
            groups[into].extend(per_voice.get(voice, []))
        established = {g: e for g, e in groups.items()
                       if sum(x.source_duration for x in e) >= material}
        aggregates = {g: domain.aggregate(e) for g, e in established.items()}
        names = sorted(aggregates)
        best = None
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                score = domain.similarity(aggregates[a], aggregates[b])
                if score >= final_threshold and (best is None or score > best[0]):
                    best = (score, a, b)
        if best is None:
            return membership
        _, kept, absorbed = best
        if sum(x.source_duration for x in established[absorbed]) > sum(
                x.source_duration for x in established[kept]):
            kept, absorbed = absorbed, kept
        for voice, into in membership.items():
            if into == absorbed:
                membership[voice] = kept


def significant(membership, meeting, minimum=10.0) -> int:
    duration = defaultdict(float)
    for turn in meeting["tours"]:
        duration[membership.get(str(turn["voix"]), str(turn["voix"]))] += (
            turn["fin"] - turn["debut"])
    return sum(1 for d in duration.values() if d >= minimum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting")
    arguments = parser.parse_args()

    path = data_folder() / "reunions" / f"{arguments.meeting}.json"
    meeting = json.loads(path.read_text())
    cache = Path("/tmp/greffier-empreintes") / f"{arguments.meeting}.pickle"
    print(f"Voiceprints of {arguments.meeting}…", file=sys.stderr)
    per_voice = voiceprints_per_voice(meeting, cache)
    print(f"{len(per_voice)} voices carry at least one voiceprint.\n")

    print("== current stitching, by threshold ==")
    for threshold in (0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45):
        measure = note(domain.join_voices(per_voice, threshold=threshold), meeting, per_voice)
        print(f"threshold {threshold:.2f} → {measure['voices']:4d} voices, "
              f"split {measure['split']}, mixed {len(measure['mixed'])}")

    print("\n== stitching then adoption of the small groups ==")
    for threshold in (0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30):
        for margin in (0.0, 0.05, 0.10):
            measure = note(adoption(per_voice, threshold, margin, 30.0), meeting, per_voice)
            print(f"threshold {threshold:.2f} margin {margin:.2f} → {measure['voices']:4d} voices, "
                  f"split {measure['split']}, mixed {len(measure['mixed'])}, "
                  f"largest {measure['largest'][:4]}")
    print("\n== adoption then consolidation of the established ==")
    for adopt in (0.45, 0.40, 0.35):
        for final in (0.80, 0.70, 0.65, 0.60, 0.55, 0.50):
            a = consolidation(per_voice, adopt, 0.0, 30.0, final)
            measure = note(a, meeting, per_voice)
            print(f"adoption {adopt:.2f} / consolidation {final:.2f} → "
                  f"{measure['voices']:4d} voices ({significant(a, meeting)} significant), "
                  f"split {measure['split']}, mixed {len(measure['mixed'])}, "
                  f"largest {measure['largest'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
