#!/usr/bin/env python3
"""Measure the published macOS bundle on a known synthetic meeting.

Run this script with the bundle's interpreter, not the checkout's interpreter.
No microphone, account, writer or mail transport is used.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    # Orthography alone must not count as lost information.
    text = text.replace("pré-production", "préproduction")
    return re.findall(r"[^\W_]+", text)


def edit_distance(expected: list[str], actual: list[str]) -> int:
    previous = list(range(len(actual) + 1))
    for index, word in enumerate(expected, 1):
        current = [index]
        for other_index, other in enumerate(actual, 1):
            current.append(min(
                current[-1] + 1, previous[other_index] + 1,
                previous[other_index - 1] + (word != other),
            ))
        previous = current
    return previous[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--diagnose-whisper", action="store_true")
    arguments = parser.parse_args()
    root = arguments.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    executable = Path(sys.executable).resolve()
    if platform.system() != "Darwin" or ".app/Contents/" not in str(executable):
        raise RuntimeError("Use the native macOS bundle's own interpreter.")
    import greffier
    if ".app/Contents/" not in str(Path(greffier.__file__).resolve()):
        raise RuntimeError("The application was imported outside its bundle.")
    version = importlib.metadata.version("greffier")
    if version != arguments.version:
        raise RuntimeError(f"Expected {arguments.version}, got {version}.")
    models = root / "models"
    os.environ["GREFFIER_PATHS__MODELS"] = str(models)
    from greffier.adapters.model_files import CATALOGUE, fetch
    for model in CATALOGUE:
        if model.required and model.engine in ("", "whisper.cpp"):
            print(f"Preparing {model.role}.", flush=True)
            ok, explanation = fetch(model, models)
            if not ok or not model.present(models):
                raise RuntimeError(f"Model preparation failed for {model.name}: {explanation}")
    # The two VITS timbres make the same reference available on every OS.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import make_meeting
    make_meeting.synthesis_engine = lambda: "vits"
    audio = make_meeting.make(root / "synthetic-meeting.wav")
    reference = json.loads(audio.with_suffix(".timeline.json").read_text(encoding="utf-8"))
    if arguments.diagnose_whisper:
        from greffier.adapters.transcription_whisper_cpp import lire_srt
        results = []
        for name, cpu, vad, timeout in (
            ("cpu-vad", True, True, 120),
            ("cpu-no-vad", True, False, 120),
            ("auto-vad", False, True, 45),
        ):
            destination = root / name
            command = [
                "whisper-cli", "-m", str(models / "ggml-large-v3-turbo.bin"),
                "-f", str(audio), "-l", "auto", "-t", "8",
                "-osrt", "-of", str(destination),
            ]
            if cpu:
                command.append("--no-gpu")
            if vad:
                command += ["--vad", "--vad-model", str(models / "ggml-silero-v5.1.2.bin")]
            print(f"Diagnosing {name}.", flush=True)
            started = time.monotonic()
            timed_out = False
            with destination.with_suffix(".log").open("w", encoding="utf-8") as log:
                try:
                    completed = subprocess.run(
                        command, stdout=log, stderr=subprocess.STDOUT,
                        timeout=timeout, check=False,
                    )
                    returncode = completed.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
                    returncode = None
            subtitles = destination.with_suffix(".srt")
            transcript = (
                " ".join(row.text for row in lire_srt(subtitles))
                if subtitles.exists() else ""
            )
            result = {
                "case": name, "timed_out": timed_out, "returncode": returncode,
                "seconds": round(time.monotonic() - started, 2),
                "words": len(words(transcript)), "transcript": transcript,
            }
            results.append(result)
            (root / "whisper-diagnostic.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
        return
    config = root / "meeting.toml"
    config.write_text(
        "[paths]\n" + f"data = {json.dumps(str(root / 'data'))}\n"
        + f"models = {json.dumps(str(models))}\n"
        + '[hardware]\ndevice = "cpu"\n'
        + '[transcription]\nengine = "whisper.cpp"\n'
        + '[minutes]\nengine = "aucun"\n'
        + '[assistant]\nactive = false\n[live]\nactive = false\n',
        encoding="utf-8",
    )
    with (root / "pipeline.log").open("w", encoding="utf-8") as log:
        outcome = subprocess.run(
            [str(executable), "-m", "greffier", "traiter", str(audio),
             "--config", str(config), "--sans-envoi", "--sans-compte-rendu"],
            stdout=log, stderr=subprocess.STDOUT, check=False, timeout=600,
        )
    if outcome.returncode:
        raise RuntimeError("The packaged meeting pipeline failed; see pipeline.log.")
    master = json.loads((root / "data/reunions/synthetic-meeting.json").read_text(encoding="utf-8"))
    expected = words(" ".join(row["text"] for row in reference))
    actual = words(" ".join(row["texte"] for row in master["repliques"]))
    errors = edit_distance(expected, actual)
    expected_names = {"A": "Jacques", "B": "Sophie"}
    groups: list[dict[str, str]] = []
    for reply in master["repliques"]:
        name = master["noms"].get(reply["voix"], reply["voix"])
        if groups and groups[-1]["speaker"] == name:
            groups[-1]["text"] += " " + reply["texte"]
        else:
            groups.append({"speaker": name, "text": reply["texte"]})
    speakers_correct = (
        len(groups) == len(reference)
        and all(group["speaker"] == expected_names[row["speaker"]]
                for group, row in zip(groups, reference, strict=True))
    )
    text = " ".join(row["texte"] for row in master["repliques"]).casefold()
    facts = {fact: fact in text for fact in (
        "exactement deux", "pas encore validées", "jeudi prochain",
        "mercredi en fin de journée",
    )}
    report = {
        "system": platform.system(), "version": version,
        "engine": "whisper.cpp", "reference_words": len(expected),
        "word_edit_operations": errors, "word_error_rate": errors / len(expected),
        "recognized_names": sorted(master["noms"].values()),
        "speaker_sequence_correct": speakers_correct, "facts_preserved": facts,
        "speaker_groups": groups, "pixels_captured": False,
        "physical_capture_verified": False, "writer_called": False,
        "ok": errors / len(expected) <= 0.05 and speakers_correct and all(facts.values()),
    }
    (root / "meeting-proof.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report["ok"]:
        raise RuntimeError("The packaged meeting lost words, speaker identity or a reference fact.")


if __name__ == "__main__":
    main()
