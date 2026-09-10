"""L'assistant entend son nom, dans du vrai son, par le vrai modèle.

Les tests unitaires disent que la règle est juste ; ils ne disent pas que
whisper rend « Lucie » de façon reconnaissable. C'est pourtant la question qui
décide : un prénom que la transcription déforme systématiquement rendrait tout
le reste inutile, et aucune doublure ne l'aurait montré.
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

#: Ce qu'on prononce, et ce qu'on attend. La dernière ne l'appelle pas : sans
#: elle, le test ne prouverait que la moitié de ce qui compte — un assistant
#: qui répond à tout est aussi inutilisable qu'un assistant sourd.
SENTENCES = [
    ("Thomas", f"{NAME}, est-ce que tu nous entends bien ?", True),
    ("Amélie", f"Du coup {NAME}, tu peux nous rappeler ce qu'on a décidé ?", True),
    ("Thomas", "On passe au point suivant, il n'y a plus rien à dire là-dessus.", False),
]


def _synthetiser(voice: str, text: str, target: Path) -> Path | None:
    """Un vrai fichier audio, par la synthèse du système. macOS pour l'instant."""
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


@pytest.mark.parametrize("voice,phrase,attendu", SENTENCES)
def test_son_nom_est_entendu_dans_du_vrai_son(
    voice, phrase, attendu, transcriber, tmp_path
):
    audio = _synthetiser(voice, phrase, tmp_path / "phrase.wav")
    if audio is None:
        pytest.skip("« say » ou ffmpeg absent : synthèse impossible")
    utterances = transcriber.transcribe(audio, "fr", f"{NAME}, l'assistante de réunion.")
    text = " ".join(r.text for r in utterances)
    assert called_by_name(text, NAME) is attendu, f"transcrit : {text!r}"


def test_la_question_est_extraite_sans_le_nom(transcriber, tmp_path):
    """Ce qu'on transmet au modèle est la demande, pas l'apostrophe.

    « Lucie, est-ce que tu nous entends ? » se traite mieux en « est-ce que tu
    nous entends ? » : le nom n'apporte rien et encombre la question.
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
