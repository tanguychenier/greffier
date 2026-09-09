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

from greffier.adaptateurs.configuration import Config
from greffier.composition import transcripteur_leger
from greffier.domaine.participation import appelee, question_posee

NOM = "Lucie"

#: Ce qu'on prononce, et ce qu'on attend. La dernière ne l'appelle pas : sans
#: elle, le test ne prouverait que la moitié de ce qui compte — un assistant
#: qui répond à tout est aussi inutilisable qu'un assistant sourd.
PHRASES = [
    ("Thomas", f"{NOM}, est-ce que tu nous entends bien ?", True),
    ("Amélie", f"Du coup {NOM}, tu peux nous rappeler ce qu'on a décidé ?", True),
    ("Thomas", "On passe au point suivant, il n'y a plus rien à dire là-dessus.", False),
]


def _synthetiser(voix: str, texte: str, cible: Path) -> Path | None:
    """Un vrai fichier audio, par la synthèse du système. macOS pour l'instant."""
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        return None
    brut = cible.with_suffix(".aiff")
    subprocess.run(["say", "-v", voix, "-o", str(brut), texte],
                   check=False, capture_output=True)
    if not brut.exists():
        return None
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(cible)],
        check=False, capture_output=True,
    )
    return cible if cible.exists() else None


@pytest.fixture(scope="module")
def transcripteur():
    outil = transcripteur_leger(Config())
    if outil is None:
        pytest.skip("aucun modèle de transcription installé")
    return outil


@pytest.mark.parametrize("voix,phrase,attendu", PHRASES)
def test_son_nom_est_entendu_dans_du_vrai_son(
    voix, phrase, attendu, transcripteur, tmp_path
):
    audio = _synthetiser(voix, phrase, tmp_path / "phrase.wav")
    if audio is None:
        pytest.skip("« say » ou ffmpeg absent : synthèse impossible")
    repliques = transcripteur.transcrire(audio, "fr", f"{NOM}, l'assistante de réunion.")
    texte = " ".join(r.texte for r in repliques)
    assert appelee(texte, NOM) is attendu, f"transcrit : {texte!r}"


def test_la_question_est_extraite_sans_le_nom(transcripteur, tmp_path):
    """Ce qu'on transmet au modèle est la demande, pas l'apostrophe.

    « Lucie, est-ce que tu nous entends ? » se traite mieux en « est-ce que tu
    nous entends ? » : le nom n'apporte rien et encombre la question.
    """
    audio = _synthetiser("Thomas", f"{NOM}, est-ce que tu nous entends bien ?",
                         tmp_path / "phrase.wav")
    if audio is None:
        pytest.skip("« say » ou ffmpeg absent : synthèse impossible")
    texte = " ".join(
        r.texte for r in transcripteur.transcrire(audio, "fr", f"{NOM}.")
    )
    question = question_posee(texte, NOM)
    assert NOM.lower() not in question.lower()
    assert "entends" in question
