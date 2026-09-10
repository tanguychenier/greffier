"""La veille, le fil et l'assistant, ensemble, sur du vrai son.

Les tests unitaires éprouvent chaque pièce ; celui-ci éprouve leur montage.
C'est le scénario de la démonstration : la réunion tourne, quelqu'un appelle
l'assistant par son prénom, et il répond — sans que la transcription prenne du
retard pendant qu'il réfléchit.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from greffier.adapters.configuration import Config
from greffier.application.follow import Position
from greffier.application.take_part import AssistantSettings
from greffier.application.watch import Watcher
from greffier.domain.instructions import WatchRules
from greffier.domain.participation import Because, Manners
from greffier.wiring import light_transcriber

pytestmark = pytest.mark.integration

PHRASE = "Lucie, est-ce que tu peux nous rappeler ce qui reste à faire ?"


class VoixFactice:
    def __init__(self):
        self.remark = []

    def say(self, text):
        self.remark.append(text)
        return True

    def go_quiet(self):
        ...

    def is_speaking(self):
        return False


class CerveauFactice:
    """Le cerveau est doublé : on éprouve le montage, pas le modèle distant."""

    def __init__(self):
        self.consignes_propres = ""
        self.vu = []

    def write_up(self, text):
        self.vu.append(text)
        return "Il reste la signature, et la recette à caler."


@pytest.fixture
def meeting(tmp_path):
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        pytest.skip("« say » ou ffmpeg absent")
    brut = tmp_path / "phrase.aiff"
    audio = tmp_path / "reunion.wav"
    subprocess.run(["say", "-v", "Thomas", "-o", str(brut), PHRASE],
                   check=False, capture_output=True)
    if not brut.exists():
        pytest.skip("synthèse impossible")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(audio)],
        check=False, capture_output=True,
    )
    return audio


def test_appele_pendant_la_reunion_il_repond(meeting, tmp_path):
    """Le scénario de la démonstration, de bout en bout."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    voice, cerveau = VoixFactice(), CerveauFactice()
    assistant = AssistantSettings(
        name="Lucie", voice=voice, cerveau=cerveau,
        # Un creux large : le fichier s'arrête sur la phrase, donc la fin de la
        # dernière réplique tombe près de « maintenant ».
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion d'équipe sur la recette.",
    )
    import soundfile

    duration = soundfile.info(str(meeting)).duration
    watcher = Watcher(
        watch_rules=WatchRules(mot_cle="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting, ecrit=duration, decalage=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)
    # La réponse est formulée dans un fil séparé : on l'attend, sans quoi le
    # test mesurerait seulement qu'on ne bloque pas la transcription.
    if assistant._job is not None:
        assistant._job.join(timeout=30)

    assert voice.remark == ["Il reste la signature, et la recette à caler."]
    assert assistant.manners.parle_le is not None


def test_la_transcription_n_attend_pas_la_reponse(meeting, tmp_path):
    """Formuler prend des secondes ; les passer à attendre coûte de l'audio.

    On mesure que la main revient avant que le cerveau ait répondu, ce qui est
    précisément ce que le fil séparé garantit.
    """
    import threading
    import time

    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    parti = threading.Event()

    class CerveauLent(CerveauFactice):
        def write_up(self, text):
            parti.set()
            time.sleep(5.0)
            return "…"

    assistant = AssistantSettings(
        name="Lucie", voice=VoixFactice(), cerveau=CerveauLent(),
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion.",
    )
    import soundfile

    duration = soundfile.info(str(meeting)).duration
    watcher = Watcher(
        watch_rules=WatchRules(mot_cle="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting, ecrit=duration, decalage=0.0),
        assistant_of=assistant,
    )
    depart = time.monotonic()
    watcher.transcription_turn(watcher.situer(), tmp_path)
    rendered = time.monotonic() - depart

    assert parti.wait(timeout=10), "l'assistant n'a pas été sollicité"
    # La transcription elle-même prend quelques secondes ; ce qu'on vérifie est
    # qu'elle n'a pas attendu les cinq du cerveau par-dessus.
    assert rendered < 5.0, f"la veille a attendu la réponse ({rendered:.1f} s)"


def test_une_phrase_ordinaire_ne_le_fait_pas_parler(tmp_path):
    """Sans son nom, rien ne se déclenche : c'est le cas de toute la réunion."""
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        pytest.skip("« say » ou ffmpeg absent")
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    brut, audio = tmp_path / "p.aiff", tmp_path / "p.wav"
    subprocess.run(["say", "-v", "Thomas", "-o", str(brut),
                    "On passe au point suivant, la recette est terminée."],
                   check=False, capture_output=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                    str(brut), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(audio)], check=False, capture_output=True)

    voice = VoixFactice()
    assistant = AssistantSettings(name="Lucie", voice=voice, manners=Manners(creux_minimal=0.0))
    import soundfile

    watcher = Watcher(
        watch_rules=WatchRules(mot_cle="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=audio, ecrit=soundfile.info(str(audio)).duration,
                                decalage=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)
    assert voice.remark == []


def test_l_assistant_absent_ne_change_rien(meeting, tmp_path):
    """La veille sans assistant est ce qu'elle a toujours été."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    import soundfile

    watcher = Watcher(
        watch_rules=WatchRules(mot_cle="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting,
                                ecrit=soundfile.info(str(meeting)).duration,
                                decalage=0.0),
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)


def test_la_raison_de_parler_est_l_appel(meeting, tmp_path):
    """Ce n'est pas un apport spontané : c'est qu'on l'a nommée."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    utterances = transcriber.transcribe(meeting, "fr", "Lucie.")
    assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=0.0))
    retenue = assistant.turn(utterances, now=max(
        r.span.end for r in utterances) + 1.0)
    assert retenue is not None and retenue.because is Because.APPELE
