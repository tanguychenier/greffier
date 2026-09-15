#!/usr/bin/env python3
"""Measures the recognition thresholds on a public corpus of meetings.

The repository's calibration (`docs/calibration.md`) rests on recordings
made here, and it lacks the measurement that matters most: **the same
person, at two different sittings**. That one says whether
`RECOGNITION_THRESHOLD` sits right: too high, nobody is recognised from one
meeting to the next; too low, two colleagues are confused.

The AMI corpus provides it: its meetings come in series, with the **same
attendees**, and each wears their own headset microphone. Two "Headset-N"
files of two meetings of one series are therefore the same person at two
sittings, with no annotation to interpret and no assumption to make.

Usage:

    python3 tools/calibrate_on_corpus.py <corpus folder>

What this script does not do: it changes no threshold. It measures and
prints. Moving a threshold is a decision taken by looking at the numbers,
not an automatic adjustment, which is what tells a calibration from a
setting made at random.

The AMI corpus is distributed under the CC BY 4.0 licence (University of
Edinburgh). It is not versioned here: only this tool is.
"""

from __future__ import annotations

import re
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: Seconds read in the middle of the recording. The start of an AMI meeting
#: carries read-out instructions and silences; the middle carries discussion.
DURATION = 240.0

#: An AMI headset **also** picks up the neighbours around the table, and its
#: wearer only speaks a fraction of the time. Taking the excerpt as it is
#: gives a voiceprint that mixes several voices, silence and breathing:
#: measured, the same person at two sittings then fell to 0.149 while two
#: different people rose to 0.280, the two clouds overlapped, which pointed
#: at the method and not at the threshold.
#:
#: So only the loudest windows are kept: on their own microphone, the wearer
#: is by far the closest, and their level sets them clearly apart from the
#: voices crossing the table.
WINDOW = 1.0
SHARE_KEPT = 0.25

#: "ES2002a.Headset-0.wav" → series ES2002, sitting a, attendee 0.
_NAME = re.compile(r"^(?P<series>[A-Z]{2}\d{4})(?P<sitting>[a-z])\.Headset-(?P<who>\d+)")


def locate(file: Path) -> tuple[str, str, str] | None:
    found = _NAME.match(file.name)
    if found is None:
        return None
    return (found["series"], found["sitting"], found["who"])


def voiceprint_of(file: Path, extractor) -> object | None:
    """The voiceprint of the voice **of the wearer** of the microphone, and theirs only.

    The loudest windows are stitched end to end, the others dropped. That is
    what sets aside the silences, the breathing and the voices crossing the
    table, without which the voiceprint belongs to nobody.
    """
    import numpy as np
    import soundfile as sf

    info = sf.info(str(file))
    start = max(0, int((info.frames - DURATION * info.samplerate) / 2))
    data, frequency = sf.read(
        str(file), start=start,
        frames=int(DURATION * info.samplerate), dtype="float32", always_2d=True,
    )
    mono = data.mean(axis=1)
    if float(np.abs(mono).max()) < 1e-4:
        return None

    per_window = int(WINDOW * frequency)
    whole = len(mono) // per_window
    if whole < 4:
        return extractor.extract(mono, frequency)
    windows = mono[:whole * per_window].reshape(whole, per_window)
    # Root mean square energy per window: that is the level, not a one-off
    # maximum a bang would be enough to push up.
    levels = np.sqrt((windows.astype(np.float64) ** 2).mean(axis=1))
    how_many = max(4, int(whole * SHARE_KEPT))
    kept = np.argsort(levels)[-how_many:]
    return extractor.extract(
        windows[np.sort(kept)].reshape(-1).astype(np.float32), frequency
    )


def main() -> int:
    from greffier.adapters.configuration import Config
    from greffier.adapters.voiceprints_titanet import TitaNetExtractor
    from greffier.domain.voiceprints import (
        MINIMUM_MARGIN,
        RECOGNITION_THRESHOLD,
        similarity,
    )

    folder = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else (
        Config().paths.data / "corpus"
    )
    files = sorted(path for path in folder.glob("*.Headset-*.wav"))
    if len(files) < 2:
        print(f"At least two \"Headset-N\" recordings are needed in {folder}.")
        print("The example script takes them from the AMI corpus, series ES2002a/b.")
        return 1

    model = Config().paths.models / "diarisation" / "nemo_en_titanet_large.onnx"
    if not model.exists():
        print(f"Voiceprint model missing: {model}")
        return 1
    extractor = TitaNetExtractor(model)

    print(f"{len(files)} recording(s), {DURATION:.0f} s read in the middle, "
          f"the loudest {SHARE_KEPT:.0%} of windows kept\n")
    voiceprints: dict[tuple[str, str, str], object] = {}
    for file in files:
        situation = locate(file)
        if situation is None:
            print(f"  skipped, name not recognised: {file.name}")
            continue
        voiceprint = voiceprint_of(file, extractor)
        if voiceprint is None:
            print(f"  skipped, silent: {file.name}")
            continue
        voiceprints[situation] = voiceprint
        series, sitting, who = situation
        print(f"  {series}{sitting} attendee {who}")

    same: list[float] = []
    others: list[float] = []
    print("\nSimilarities measured:\n")
    for (one, other) in combinations(sorted(voiceprints), 2):
        value = similarity(voiceprints[one], voiceprints[other])  # type: ignore[arg-type]
        same_person = one[0] == other[0] and one[2] == other[2]
        same_sitting = one[1] == other[1]
        if same_person and not same_sitting:
            what = "SAME person, two sittings"
            same.append(value)
        elif same_person:
            what = "same person, same sitting"
        else:
            what = "different people"
            others.append(value)
        print(f"  {value:.3f}  {what:<28} "
              f"{one[0]}{one[1]}·{one[2]} / {other[0]}{other[1]}·{other[2]}")

    print(f"\nThreshold in force: {RECOGNITION_THRESHOLD:.2f} "
          f"(minimum margin {MINIMUM_MARGIN:.2f})")
    if same:
        print(f"  same person, two sittings : {min(same):.3f} to {max(same):.3f}")
        under = [value for value in same if value < RECOGNITION_THRESHOLD]
        if under:
            print(f"  ⚠ {len(under)} pair(s) under the threshold: these people would")
            print("    not be recognised from one meeting to the next.")
    if others:
        print(f"  different people          : {min(others):.3f} to {max(others):.3f}")
        above = [value for value in others if value >= RECOGNITION_THRESHOLD]
        if above:
            print(f"  ⚠ {len(above)} pair(s) above the threshold: two different")
            print("    people would be confused.")
    if same and others and max(others) < min(same):
        print(f"\n  The two clouds are apart: any threshold between {max(others):.3f} "
              f"and {min(same):.3f} separates correctly.")
    elif same and others:
        # The ordinary case as soon as enough pairs are measured. What counts
        # then is no longer "which threshold separates" but "what each
        # threshold costs": this table is what makes it possible to decide,
        # and a first measurement on six pairs had suggested a clean split.
        print("\n  The clouds overlap: no threshold separates. What each one "
              "costs:\n")
        print(f"    {'threshold':>9}  {'not recognised':>15}  {'confused':>9}")
        for threshold in (0.70, 0.60, 0.50, 0.45, 0.40, 0.30):
            missed = sum(1 for value in same if value < threshold)
            confused = sum(1 for value in others if value >= threshold)
            print(f"    {threshold:>9.2f}  {missed:>7}/{len(same):<7}  "
                  f"{confused:>4}/{len(others):<4}")
        print("\n  A confusion writes somebody else's name in the minutes;\n"
              "  a missed recognition leaves a voice to name in one click. The two\n"
              "  are not worth the same.")

    print("\n  Caveat: AMI does not guarantee that attendee N keeps the same"
          "\n  microphone from one sitting to the next. Part of the overlap may"
          "\n  therefore be a labelling artefact rather than one of timbre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
