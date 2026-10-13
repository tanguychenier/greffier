#!/usr/bin/env python3
"""Verify actual Windows and Linux packages with a reference meeting."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import wave
from pathlib import Path

from check_packaged_meeting import edit_distance, words
from reference_meeting import copy_reference


def prepare(root: Path) -> tuple[Path, Path]:
    from faster_whisper.utils import download_model

    from greffier.adapters.model_files import CATALOGUE, fetch

    models = root / "models"
    os.environ["GREFFIER_PATHS__MODELS"] = str(models)
    for model in CATALOGUE:
        if model.required and not model.engine:
            print(f"Preparing {model.role}.", flush=True)
            ok, explanation = fetch(model, models)
            if not ok or not model.present(models):
                raise RuntimeError(f"Model preparation failed: {explanation}")
    transcription = download_model("large-v3", cache_dir=str(models / "transcription"))
    audio = copy_reference(root)
    config = root / "meeting.toml"
    config.write_text(
        "[paths]\n" + f"data = {json.dumps(str(root / 'data'))}\n"
        + f"models = {json.dumps(str(models))}\n"
        + '[hardware]\ndevice = "cpu"\n'
        + '[transcription]\nengine = "faster-whisper"\n'
        + f"model = {json.dumps(transcription)}\n"
        + '[minutes]\nengine = "aucun"\n'
        + '[assistant]\nactive = false\n[live]\nactive = false\n',
        encoding="utf-8",
    )
    return audio, config


def measure(root: Path, audio: Path) -> dict[str, object]:
    master = json.loads((root / "data/reunions/synthetic-meeting.json").read_text("utf-8"))
    reference = json.loads(audio.with_suffix(".timeline.json").read_text("utf-8"))
    expected = words(" ".join(row["text"] for row in reference))
    text = " ".join(row["texte"] for row in master["repliques"])
    errors = edit_distance(expected, words(text))
    names = {"A": "Jacques", "B": "Sophie"}
    groups: list[dict[str, str]] = []
    for reply in master["repliques"]:
        name = master["noms"].get(reply["voix"], reply["voix"])
        if groups and groups[-1]["speaker"] == name:
            groups[-1]["text"] += " " + reply["texte"]
        else:
            groups.append({"speaker": name, "text": reply["texte"]})
    speakers_correct = len(groups) == len(reference) and all(
        group["speaker"] == names[row["speaker"]]
        for group, row in zip(groups, reference, strict=True)
    )
    facts = {fact: fact in text.casefold() for fact in (
        "module de facturation", "exactement deux", "pas encore validées", "jeudi prochain",
        "mercredi en fin de journée",
    )}
    return {
        "reference_words": len(expected), "word_edit_operations": errors,
        "word_error_rate": errors / len(expected),
        "recognized_names": sorted(master["noms"].values()),
        "speaker_sequence_correct": speakers_correct, "speaker_groups": groups,
        "facts_preserved": facts,
        "ok": errors / len(expected) <= 0.05 and speakers_correct and all(facts.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    application = arguments.application.resolve()
    runtime = json.loads(arguments.runtime_report.read_text("utf-8"))
    version = importlib.metadata.version("greffier")
    if (
        platform.system() not in ("Linux", "Windows") or not application.is_file()
        or runtime["system"] != platform.system() or runtime["version"] != version
        or not runtime["frozen"] or not runtime["ok"] or runtime["errors"]
    ):
        raise RuntimeError("The native frozen application's runtime proof is required.")
    root = arguments.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    audio, config = prepare(root)
    silence = root / "digital-silence.wav"
    with wave.open(str(silence), "wb") as recording:
        recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        recording.writeframes(bytes(16000 * 2 * 2))
    environment = dict(os.environ, HF_HUB_OFFLINE="1", APPIMAGE_EXTRACT_AND_RUN="1")
    for recording, should_fail in ((silence, True), (audio, False)):
        destination = root / ("silence.log" if should_fail else "pipeline.log")
        environment["GREFFIER_COMPANION_LOG"] = str(
            root / ("silence-companion.log" if should_fail else "pipeline-companion.log")
        )
        with destination.open("w", encoding="utf-8") as log:
            outcome = subprocess.run(
                [str(application), "-m", "greffier", "traiter", str(recording),
                 "--config", str(config), "--sans-envoi", "--sans-compte-rendu"],
                env=environment, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, check=False, timeout=60 if should_fail else 900,
            )
        if (outcome.returncode != 0) != should_fail:
            raise RuntimeError("The packaged pipeline failed its recording check.")
    if (root / "data/transcriptions/digital-silence.txt").exists():
        raise RuntimeError("Digital silence must not produce a transcript.")
    report = measure(root, audio)
    report.update({
        "system": platform.system(), "version": version, "engine": "faster-whisper",
        "reference_audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "pixels_captured": False, "physical_capture_verified": False,
        "writer_called": False, "digital_silence_rejected": True,
    })
    (root / "meeting-proof.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report["ok"]:
        raise RuntimeError("The package lost words, speaker identity or a reference fact.")


if __name__ == "__main__":
    main()
