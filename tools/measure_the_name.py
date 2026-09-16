#!/usr/bin/env python3
"""Measures whether the assistant hears her own name in a real voice.

She only speaks when she hears her name, and the listening pass hears it
through the live model alone, on eight seconds of audio with no context.
On the synthesised voices « Lucie » came back « Ici » or « Si » once in
ten. Nobody had measured it on a real voice, and no meeting is needed for
that: ten questions said into the microphone are enough.

    python3 tools/measure_the_name.py --record 10
    python3 tools/measure_the_name.py --folder ~/.local/share/greffier/corpus/name

`--record` asks for one question per take, records six seconds through
the microphone the settings name, and keeps the takes in the corpus
folder; with a folder of takes already there, it only listens. Each take
goes through the live model twice, with the seed the watch gives it (her
name in it) and without, and the tool says what it heard each time and
how many takes out of the lot carried her name.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greffier.locations import data_folder  # noqa: E402

TAKE_S = 6.0

#: Questions somebody would ask her in a meeting, varied on purpose: the
#: name is what is measured, the rest must not be the same ten times.
QUESTIONS = [
    "Lucie, à quel jour est décalée la recette ?",
    "Lucie, combien d'anomalies restent à valider ?",
    "Lucie, tu peux nous rappeler ce qui a été décidé ?",
    "Lucie, c'est quoi une préproduction, en une phrase ?",
    "Lucie, qui prévient les utilisateurs ?",
    "Lucie, on avait dit quoi pour le budget ?",
    "Lucie, est-ce que quelqu'un a répondu à Bruno ?",
    "Lucie, tu notes que la réunion suivante est jeudi ?",
    "Lucie, il reste combien de temps ?",
    "Lucie, tu as le lien du ticket ?",
]


def record(folder: Path, count: int, config: Any) -> list[Path]:
    """One take per question, six seconds each, through the settings' microphone."""
    from greffier.adapters.audio_ffmpeg import FfmpegRecorder

    recorder = FfmpegRecorder(config.audio.input)
    folder.mkdir(parents=True, exist_ok=True)
    takes: list[Path] = []
    for number in range(1, count + 1):
        question = QUESTIONS[(number - 1) % len(QUESTIONS)]
        input(f"\nPrise {number}/{count}. Dis, par exemple : « {question} »\n"
              f"Entrée pour enregistrer {TAKE_S:.0f} secondes… ")
        take = folder / f"prise-{number:02d}.wav"
        process_id = recorder.start_recording(take)
        print("… parle.", flush=True)
        time.sleep(TAKE_S)
        recorder.stop_recording(process_id)
        print(f"enregistré dans {take.name}")
        takes.append(take)
    return takes


def heard(takes: list[Path], config: Any) -> list[dict[str, Any]]:
    """What the live model heard on each take, with the seed and without."""
    from greffier.application.watch import HER_NAME_SEED
    from greffier.domain.participation import called_by_name
    from greffier.wiring import light_transcriber

    transcriber = light_transcriber(config)
    if transcriber is None:
        raise SystemExit("aucun modèle de transcription installé : python3 tools/install.py")
    name = config.assistant.name
    seed = HER_NAME_SEED.format(name=name)
    rows: list[dict[str, Any]] = []
    for take in takes:
        with_seed = " ".join(u.text for u in transcriber.transcribe(take, "fr", seed)).strip()
        without = " ".join(u.text for u in transcriber.transcribe(take, "fr", "")).strip()
        rows.append({
            "take": take.name,
            "with_seed": with_seed, "heard_with_seed": called_by_name(with_seed, name),
            "without_seed": without, "heard_without_seed": called_by_name(without, name),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--record", type=int, default=0, help="how many takes to record")
    parser.add_argument("--folder", type=Path, default=data_folder() / "corpus" / "name",
                        help="where the takes are, or go")
    options = parser.parse_args()

    from greffier.adapters.configuration import Config

    config = Config()
    if options.record:
        takes = record(options.folder, options.record, config)
    else:
        takes = sorted(options.folder.glob("*.wav"))
    if not takes:
        print(f"aucune prise dans {options.folder} : python3 tools/measure_the_name.py --record 10")
        return 1

    rows = heard(takes, config)
    for row in rows:
        mark = "oui" if row["heard_with_seed"] else "NON"
        other = "oui" if row["heard_without_seed"] else "NON"
        print(f"{row['take']}  avec l'amorce {mark:<3} « {row['with_seed']} »"
              f"   sans {other:<3} « {row['without_seed']} »")
    with_seed = sum(1 for row in rows if row["heard_with_seed"])
    without = sum(1 for row in rows if row["heard_without_seed"])
    print(f"\n{config.assistant.name} entendue {with_seed} fois sur {len(rows)} avec l'amorce, "
          f"{without} sur {len(rows)} sans.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
