#!/usr/bin/env python3
"""Fetches the real French recordings the measurements in `docs/corpus.md` rest on.

Nothing here is versioned but this script: the audio stays with its producer
and comes down on demand. Two sources, chosen for what each one alone gives:

- **SUMM-RE** (LINAGORA / LPL, CC BY-SA 4.0): meeting-style conversations of
  three or four people recorded in the same room, one microphone per person,
  transcribed by hand and aligned to the word. The tracks are mixed into one
  mono file, which is what a single recorder in the room would have heard,
  and the per-speaker timings become the reference.
- **Assemblée nationale**: a committee hearing, one room, table microphones,
  people at varying distances, interruptions. The published minutes name every
  speaker but are edited, so they are a reference for terms and for who spoke,
  not for a raw word error rate.

    python3 tools/fetch_corpus.py                 # everything, into the data folder
    python3 tools/fetch_corpus.py summre          # one source only
    python3 tools/fetch_corpus.py --into /tmp/c   # elsewhere

Needs `pyarrow` and `huggingface_hub` for SUMM-RE (`pip install ".[corpus]"`),
and `ffmpeg` and `pdftotext` on the PATH for the Assemblée.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greffier.locations import data_folder  # noqa: E402

#: The SUMM-RE meetings kept: four people each, recorded in person at the
#: H2C2 studio, a reporting meeting and a planning meeting, each held in a
#: single parquet file of the `dev` split so that one download is enough.
#: 032b is the decision meeting of the same series as 032a, the same four
#: people a second time: what the voice bank is measured on.
SUMMRE_REPOSITORY = "linagora/SUMM-RE"
SUMMRE_MEETINGS = {
    "032a_EARH": "data/dev/dev-00009-of-00029.parquet",
    "032b_EADH": "data/dev/dev-00010-of-00029.parquet",
    "036c_EAPH": "data/dev/dev-00015-of-00029.parquet",
}
SUMMRE_LICENCE = "CC BY-SA 4.0, LINAGORA and LPL Aix-Marseille (ANR-20-CE23-0017)"

#: The hearing kept: 22 July 2026, "Les Oubliés de la République", five
#: witnesses, the chair, the rapporteur and the members who asked questions.
#: Minutes n° 10 of the committee of inquiry on the rise of poverty.
ASSEMBLEE_VIDEO = (
    "http://anorigin.vodalys.com/vod/mp4/ida/domain1/2026/07/6237_20260722142127_1.mp4"
)
ASSEMBLEE_MINUTES_PDF = (
    "https://www.assemblee-nationale.fr/dyn/17/comptes-rendus/cepauvr/"
    "l17cepauvr2526010_compte-rendu.pdf"
)
ASSEMBLEE_NAME = "assemblee-2026-07-22"
ASSEMBLEE_LICENCE = (
    "Video: download open on the portal, licence unstated. "
    "Minutes: public parliamentary document. Local measurement, no redistribution."
)

#: What every recording is brought to: what the transcriber reads.
SAMPLE_RATE = 16_000

#: The stream starts a quarter of an hour before the chair opens the sitting,
#: on an empty room. Speech is kept from the first window louder than the
#: floor, and for as long as the plan asks: a recording of twenty to forty
#: minutes, which bounds what a transcription of it costs.
ASSEMBLEE_WINDOW = 10.0
ASSEMBLEE_FLOOR_DB = -45.0
ASSEMBLEE_MINUTES = 40.0

#: A turn in the minutes starts with a civility and a name, then a full stop.
#: "M. le président Jean-Marie Fiévet." and "Mme Karen Erodi (LFI-NFP)." both fit.
_TURN = re.compile(
    r"^\s*(?P<speaker>(?:M\.|Mme)\s(?:le président\s|la présidente\s)?"
    r"[A-ZÉ][^.()]{1,60}(?:\([^)]{1,30}\))?)\.\s+(?P<text>\S.*)$"
)
_PAGE_MARK = re.compile(r"^\s*—\s*\d+\s*—\s*$")
_CLOSING = re.compile(r"^\s*(La séance (est levée|s’achève|s'achève)|Membres présents)")


Turn = dict[str, object]


def fetch_summre(into: Path) -> list[Path]:
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from huggingface_hub import hf_hub_download

    written: list[Path] = []
    for meeting, shard in SUMMRE_MEETINGS.items():
        target = into / f"summre-{meeting}.wav"
        if target.exists():
            print(f"  {target.name} already there")
            written.append(target)
            continue
        print(f"  {meeting}: downloading {shard}")
        local = hf_hub_download(SUMMRE_REPOSITORY, shard, repo_type="dataset")
        table = pq.read_table(local, filters=[("meeting_id", "=", meeting)])
        rows = table.to_pylist()
        if not rows:
            raise SystemExit(f"{meeting} not in {shard}")

        tracks: list[np.ndarray] = []
        turns: list[Turn] = []
        for row in rows:
            audio = row["audio"]
            data, rate = sf.read(io.BytesIO(audio["bytes"]), dtype="float32", always_2d=True)
            mono = data.mean(axis=1)
            tracks.append(_resample(mono, rate, SAMPLE_RATE))
            for segment in row["segments"]:
                turns.append(
                    {
                        "speaker": row["speaker_id"],
                        "start": segment["start"],
                        "end": segment["end"],
                        "text": segment["transcript"],
                        "words": segment["words"],
                    }
                )
        length = max(len(track) for track in tracks)
        mix = np.zeros(length, dtype=np.float32)
        for track in tracks:
            mix[: len(track)] += track
        peak = float(np.max(np.abs(mix))) or 1.0
        mix *= 0.9 / peak
        sf.write(str(target), mix, SAMPLE_RATE)

        turns.sort(key=lambda turn: float(str(turn["start"])))
        reference = {
            "source": f"SUMM-RE {meeting}, split dev",
            "licence": SUMMRE_LICENCE,
            "reference": "manual, word-aligned, one track per person",
            "speakers": sorted({str(turn["speaker"]) for turn in turns}),
            "turns": turns,
        }
        target.with_suffix(".reference.json").write_text(
            json.dumps(reference, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        minutes = length / SAMPLE_RATE / 60
        print(f"  {target.name}: {len(tracks)} voices, {minutes:.1f} min, {len(turns)} turns")
        written.append(target)
    return written


def _resample(signal: np.ndarray, rate: int, wanted: int) -> np.ndarray:
    import numpy as np

    if rate == wanted:
        return signal
    positions = np.arange(0, len(signal), rate / wanted)
    resampled: np.ndarray = np.interp(positions, np.arange(len(signal)), signal)
    return resampled.astype(np.float32)


def fetch_assemblee(into: Path) -> list[Path]:
    for tool in ("ffmpeg", "pdftotext"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is missing from the PATH")
    target = into / f"{ASSEMBLEE_NAME}.wav"
    video = into / f"{ASSEMBLEE_NAME}.mp4"
    if not target.exists():
        if not video.exists():
            print("  downloading the video (1.2 GB)")
            _download(ASSEMBLEE_VIDEO, video)
        print("  extracting the audio track")
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                str(target),
            ],
            check=True,
        )
        video.unlink()
        _keep_the_speech(target)
    else:
        print(f"  {target.name} already there")

    minutes = into / f"{ASSEMBLEE_NAME}.pdf"
    if not minutes.exists():
        print("  downloading the minutes")
        _download(ASSEMBLEE_MINUTES_PDF, minutes)
    text = subprocess.run(
        ["pdftotext", "-layout", str(minutes), "-"], check=True, capture_output=True, text=True
    ).stdout
    turns = minutes_turns(text)
    reference = {
        "source": "Assemblée nationale, committee of inquiry on the rise of poverty, "
        "hearing of 22 July 2026, minutes n° 10",
        "licence": ASSEMBLEE_LICENCE,
        "reference": "edited minutes: speakers and words, no timings",
        "speakers": sorted({turn["speaker"] for turn in turns}),
        "turns": turns,
    }
    target.with_suffix(".reference.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  {target.name}: {len(reference['speakers'])} named speakers, {len(turns)} turns")
    return [target]


def _keep_the_speech(target: Path) -> None:
    import numpy as np
    import soundfile as sf

    data, rate = sf.read(str(target), dtype="float32")
    window = int(ASSEMBLEE_WINDOW * rate)
    levels = [
        20 * np.log10(float(np.sqrt(np.mean(data[i : i + window] ** 2))) + 1e-9)
        for i in range(0, len(data), window)
    ]
    first = next((i for i, level in enumerate(levels) if level > ASSEMBLEE_FLOOR_DB), 0)
    start = first * window
    end = start + int(ASSEMBLEE_MINUTES * 60 * rate)
    sf.write(str(target), data[start:end], rate)
    since = first * ASSEMBLEE_WINDOW / 60
    print(f"  speech from {since:.1f} min on, {ASSEMBLEE_MINUTES:.0f} min kept")


def minutes_turns(text: str) -> list[dict[str, str]]:
    """The spoken turns of the minutes, from the opening to the attendance list."""
    turns: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    started = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not started:
            started = "La séance est ouverte" in line
            continue
        if _CLOSING.match(line):
            break
        if _PAGE_MARK.match(line) or not line.strip():
            continue
        found = _TURN.match(line)
        if found:
            current = {"speaker": _clean(found["speaker"]), "text": found["text"].strip()}
            turns.append(current)
        elif current is not None:
            current["text"] += " " + line.strip()
    return _one_spelling_per_speaker(turns)


def _one_spelling_per_speaker(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    """The minutes write "Élina" seven times and "Elina" once: one person, one name."""
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    for turn in turns:
        spellings[_folded(turn["speaker"])][turn["speaker"]] += 1
    usual = {key: seen.most_common(1)[0][0] for key, seen in spellings.items()}
    for turn in turns:
        turn["speaker"] = usual[_folded(turn["speaker"])]
    return turns


def _folded(name: str) -> str:
    decomposed = unicodedata.normalize("NFD", name.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _clean(speaker: str) -> str:
    return re.sub(r"\s+", " ", speaker).strip()


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(request) as answer, partial.open("wb") as out:
        shutil.copyfileobj(answer, out, length=1 << 20)
    partial.rename(target)


SOURCES = {"summre": fetch_summre, "assemblee": fetch_assemblee}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("sources", nargs="*", choices=[*SOURCES, "all"], default=["all"])
    parser.add_argument("--into", type=Path, default=data_folder() / "corpus")
    options = parser.parse_args()
    wanted = list(SOURCES) if "all" in options.sources else options.sources
    options.into.mkdir(parents=True, exist_ok=True)
    print(f"Corpus in {options.into}")
    for name in wanted:
        print(name)
        SOURCES[name](options.into)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
