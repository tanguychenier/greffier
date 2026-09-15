#!/usr/bin/env python3
"""Which first names does the transcription model return recognisably?

The assistant answers when its first name is said. A first name the
transcription does not return is therefore a deaf assistant, and nothing
would tell whoever chose it: they would call into the void, and conclude
the tool does not work.

Each candidate goes through four trials: two phrasings, two synthetic
voices, then five traps: sentences without the first name, to check it does
not trigger on them. That is the defect of "Greffier", which "le greffe du
tribunal" was enough to wake, and of "Élise", which "elle a lu ci et ça"
calls.

Kept: four calls out of four, zero false positives out of five. A first name
recognised one time in two is worth nothing, since one calls once and waits.

    python3 tools/probe_first_names.py

**No sound is played**: the files are written then transcribed. So it can
run during a meeting: even if the computation itself fights the live
transcription for the processor.

What it does not measure: what a first name becomes when said by a real
voice, three metres from a table microphone. It is a floor, not a guarantee.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")
from greffier.adapters.configuration import Config
from greffier.domain.participation import called_by_name
from greffier.wiring import light_transcriber

FEMININE = ["Lucie", "Camille", "Alice", "Manon", "Louise", "Élise", "Iris"]
MASCULINE = ["Martin", "Julien", "Antoine", "Nicolas", "Marius", "Léon", "Basile"]

#: Two phrasings, two voices: a first name that only passes one time in two
#: is worth nothing, since one calls once and waits.
SENTENCES = ["{}, est-ce que tu peux noter ça ?",
             "Du coup {}, tu en penses quoi ?"]
VOICE = ["Thomas", "Amélie"]

#: What the first name must **not** trigger on. The trap of "Greffier",
#: which "le greffe du tribunal" was enough to wake.
TRAPS = [
    "on passe au point suivant, la recette est terminée",
    "il faut qu'on parle du budget et des livraisons",
    "le sprint avance bien, la merge request est prête",
    "elle a lu ci et ça dans la documentation",
    "on a vu ça lundi avec l'équipe de Bordeaux",
]

transcriber = light_transcriber(Config())
if transcriber is None:
    raise SystemExit("no transcription model")


def heard(voice, sentence, folder):
    raw, wav = folder / "p.aiff", folder / "p.wav"
    subprocess.run(["say", "-v", voice, "-o", str(raw), sentence],
                   check=False, capture_output=True)
    if not raw.exists():
        return ""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                    str(raw), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(wav)], check=False, capture_output=True)
    raw.unlink(missing_ok=True)
    if not wav.exists():
        return ""
    rendered = " ".join(r.text for r in transcriber.transcribe(wav, "fr", ""))
    wav.unlink(missing_ok=True)
    return rendered


print(f"{'first name':10} {'calls recognised':>16} {'false positives':>15}   example heard")
print("─" * 84)
with tempfile.TemporaryDirectory() as scratch:
    folder = Path(scratch)
    for first_name in FEMININE + MASCULINE:
        recognised, total, example = 0, 0, ""
        for voice in VOICE:
            for sentence in SENTENCES:
                text = heard(voice, sentence.format(first_name), folder)
                total += 1
                if called_by_name(text, first_name):
                    recognised += 1
                elif not example:
                    example = text[:44]
        false = sum(1 for p in TRAPS if called_by_name(p, first_name))
        mark = "  ✓" if recognised == total and false == 0 else "  ✗"
        print(f"{first_name:10} {recognised:>10}/{total}      {false:>10}/{len(TRAPS)}"
              f"{mark} {example}")
