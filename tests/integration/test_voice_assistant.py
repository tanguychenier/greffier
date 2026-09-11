"""The assistant hears its name, in real sound, through the real model.

The unit tests say the rule is right; they do not say that whisper returns
"Lucie" recognisably. That is the question that decides everything: a first name
the transcription systematically mangles would make all the rest useless, and no
double would have shown it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.domain.participation import called_by_name, question_asked
from greffier.wiring import light_transcriber

NAME = "Lucie"

#: What is said, and what is expected. The last one does not call it: without
#: that, the test would prove only half of what matters, since an assistant that
#: answers everything is as useless as a deaf one.
SENTENCES = [
    ("Thomas", f"{NAME}, est-ce que tu nous entends bien ?", True),
    ("Amélie", f"Du coup {NAME}, tu peux nous rappeler ce qu'on a décidé ?", True),
    ("Thomas", "On passe au point suivant, il n'y a plus rien à dire là-dessus.", False),
]


def _synthetiser(voice: str, text: str, target: Path) -> Path | None:
    """A real audio file, from the system's speech synthesis. macOS for now."""
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        return None
    brut = target.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(brut), text],
                   check=False, capture_output=True)
    if not brut.exists():
        return None
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target)],
        check=False, capture_output=True,
    )
    return target if target.exists() else None


@pytest.fixture(scope="module")
def transcriber():
    outil = light_transcriber(Config())
    if outil is None:
        pytest.skip("aucun modèle de transcription installé")
    return outil


@pytest.mark.parametrize("voice,sentence,expected", SENTENCES)
def test_its_name_is_heard_in_real_sound(
    voice, sentence, expected, transcriber, tmp_path
):
    audio = _synthetiser(voice, sentence, tmp_path / "phrase.wav")
    if audio is None:
        pytest.skip("« say » ou ffmpeg absent : synthèse impossible")
    utterances = transcriber.transcribe(audio, "fr", f"{NAME}, l'assistante de réunion.")
    text = " ".join(r.text for r in utterances)
    assert called_by_name(text, NAME) is expected, f"transcrit : {text!r}"


def test_the_question_is_taken_out_without_the_name(transcriber, tmp_path):
    """What is passed to the model is the request, not the vocative.

    "Lucie, est-ce que tu nous entends ?" is better handled as "est-ce que tu nous
    entends ?": the name adds nothing and clutters the question.
    """
    audio = _synthetiser("Thomas", f"{NAME}, est-ce que tu nous entends bien ?",
                         tmp_path / "phrase.wav")
    if audio is None:
        pytest.skip("« say » ou ffmpeg absent : synthèse impossible")
    text = " ".join(
        r.text for r in transcriber.transcribe(audio, "fr", f"{NAME}.")
    )
    question = question_asked(text, NAME)
    assert NAME.lower() not in question.lower()
    assert "entends" in question
