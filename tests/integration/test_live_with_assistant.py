"""The watch, the thread and the assistant together, on real sound.

The unit tests cover each piece; this one covers how they are assembled. It is
the scenario of the demonstration: the meeting is running, somebody calls the
assistant by its first name, and it answers, without the transcription falling
behind while it thinks.
"""

from __future__ import annotations

import pytest

from greffier.adapters.configuration import Config
from greffier.application.follow import Position
from greffier.application.take_part import AssistantSettings
from greffier.application.watch import Watcher
from greffier.domain.instructions import WatchRules
from greffier.domain.participation import Because, Manners
from greffier.wiring import light_transcriber
from tests.integration.prerequisites import (
    the_called_name_is_out_of_reach,
    voices_are_out_of_reach,
)

pytestmark = pytest.mark.integration

PHRASE = "Lucie, est-ce que tu peux nous rappeler ce qui reste à faire ?"


class FakeVoiceAdapter:
    def __init__(self):
        self.remark = []

    def say(self, text):
        self.remark.append(text)
        return True

    def go_quiet(self):
        ...

    def is_speaking(self):
        return False


class FakeBrain:
    """The brain is doubled: what is covered is the assembly, not the remote model."""

    def __init__(self):
        self.consignes_propres = ""
        self.vu = []

    def write_up(self, text):
        self.vu.append(text)
        return "Il reste la signature, et la recette à caler."


@pytest.fixture
def meeting(tmp_path):
    hors_de_portee = voices_are_out_of_reach(1)
    if hors_de_portee:
        pytest.skip(hors_de_portee)
    from make_meeting import speak

    audio = speak(PHRASE, "Thomas", tmp_path / "reunion.wav")
    if audio is None:
        pytest.skip("synthèse impossible")
    return audio


@pytest.fixture
def called_by_its_name():
    """These tests only mean something where the name survives the round trip."""
    hors_de_portee = the_called_name_is_out_of_reach()
    if hors_de_portee:
        pytest.skip(hors_de_portee)


def test_called_during_the_meeting_it_answers(called_by_its_name, meeting, tmp_path):
    """The scenario of the demonstration, end to end."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    voice, cerveau = FakeVoiceAdapter(), FakeBrain()
    assistant = AssistantSettings(
        name="Lucie", voice=voice, cerveau=cerveau,
        # A wide lull: the file stops on the sentence, so the end of the last
        # utterance falls near "now".
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion d'équipe sur la recette.",
    )
    import soundfile

    duration = soundfile.info(str(meeting)).duration
    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting, written=duration, offset=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)
    # The answer is phrased in a separate thread: it is waited for, or the
    # test would only measure that the transcription is not blocked.
    if assistant._job is not None:
        assistant._job.join(timeout=30)

    assert voice.remark == ["Il reste la signature, et la recette à caler."]
    assert assistant.manners.spoke_at is not None


def test_the_transcription_does_not_wait_for_the_answer(meeting, tmp_path):
    """Phrasing takes seconds; spending them waiting costs audio.

    What is measured is that control comes back before the brain has answered,
    which is exactly what the separate thread guarantees.
    """
    import threading
    import time

    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    parti = threading.Event()

    class SlowBrain(FakeBrain):
        def write_up(self, text):
            parti.set()
            time.sleep(5.0)
            return "…"

    assistant = AssistantSettings(
        name="Lucie", voice=FakeVoiceAdapter(), cerveau=SlowBrain(),
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion.",
    )
    import soundfile

    duration = soundfile.info(str(meeting)).duration
    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting, written=duration, offset=0.0),
        assistant_of=assistant,
    )
    # Le modèle se charge à la première transcription -- seize secondes sur une
    # carte, mesuré. Le compter ici ferait échouer le test sur une machine
    # parfaitement saine, pour une lenteur qui n'arrive qu'une fois par session.
    transcriber.transcribe(meeting, "fr", "")
    depart = time.monotonic()
    watcher.transcription_turn(watcher.situer(), tmp_path)
    rendered = time.monotonic() - depart

    assert parti.wait(timeout=10), "l'assistant n'a pas été sollicité"
    # The transcription itself takes a few seconds; what is checked is that it
    # did not wait for the brain's five on top of them.
    assert rendered < 5.0, f"la veille a attendu la réponse ({rendered:.1f} s)"


def test_an_ordinary_sentence_does_not_make_it_speak(tmp_path):
    """Without its name nothing fires, which is the case for the whole meeting."""
    hors_de_portee = voices_are_out_of_reach(1)
    if hors_de_portee:
        pytest.skip(hors_de_portee)
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    from make_meeting import speak

    audio = speak("On passe au point suivant, la recette est terminée.",
                  "Thomas", tmp_path / "p.wav")
    if audio is None:
        pytest.skip("synthèse impossible")

    voice = FakeVoiceAdapter()
    assistant = AssistantSettings(name="Lucie", voice=voice, manners=Manners(creux_minimal=0.0))
    import soundfile

    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=audio, written=soundfile.info(str(audio)).duration,
                                offset=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)
    assert voice.remark == []


def test_no_assistant_changes_nothing(meeting, tmp_path):
    """The watch with no assistant is what it has always been."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    import soundfile

    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting,
                                written=soundfile.info(str(meeting)).duration,
                                offset=0.0),
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)


def test_the_reason_for_speaking_is_the_call(called_by_its_name, meeting, tmp_path):
    """Ce n'est pas un apport spontané : c'est qu'on l'a nommée."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    utterances = transcriber.transcribe(meeting, "fr", "Lucie.")
    assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=0.0))
    retenue = assistant.turn(utterances, now=max(
        r.span.end for r in utterances) + 1.0)
    assert retenue is not None and retenue.because is Because.APPELE


@pytest.mark.integration
class TestTheLoopOnARealThread:
    """The transcriber's loop, on the thread of a real meeting.

    Rebuilt from the thread of 2026-09-10 at 13:08, exactly as it was published:
    a hundred and twenty-five turns, sixty-five of them repetition, four distinct
    loops, the longest of twelve one-second segments.
    """

    #: The four loops actually observed, in the order of the thread.
    OBSERVE = [
        ("Est-ce que tu entends Lucie ?", 30.0, 11),
        ("- C'est ça qu'on va faire.", 125.0, 12),
        ("Je vais vous créer la vache.", 166.0, 11),
        ("Est-ce que tu n'as pas fait ?", 41.0, 9),
    ]

    def _fil(self):
        from greffier.domain.models import Span, Utterance

        dites = []
        for texte, depart, how_many in self.OBSERVE:
            dites += [
                Utterance(span=Span(depart + i, depart + i + 1), text=texte)
                for i in range(how_many)
            ]
        return sorted(dites, key=lambda u: u.span.start)

    def test_the_four_loops_fold_up(self):
        from greffier.domain.boilerplate import collapse_loops

        avant = self._fil()
        apres = collapse_loops(avant)
        assert len(avant) == 43
        assert len(apres) == 4, [u.text for u in apres]

    def test_every_kept_sentence_covers_its_run(self):
        from greffier.domain.boilerplate import collapse_loops

        for gardee in collapse_loops(self._fil()):
            expected = next(c for t, _d, c in self.OBSERVE if t == gardee.text)
            assert gardee.span.end - gardee.span.start == expected

    def test_the_published_thread_no_longer_carries_the_repetition(self):
        """What the window shows: one line per sentence said."""
        from greffier.domain.boilerplate import collapse_loops

        textes = [u.text for u in collapse_loops(self._fil())]
        assert len(textes) == len(set(textes))


@pytest.mark.integration
class TestAnOldSettingNoLongerSilencesIt:
    """A setting the window no longer exposes must no longer decide.

    The defect, lived through twice in a meeting: the settings file carried
    "actif = false", written when a button existed for it. Changing the default to
    true achieved nothing, an existing file keeping its own value, and since the
    window no longer exposed that button nothing could put it back. The call was
    heard perfectly well: "Est-ce que tu entends, Lucie ?" appears twelve times in
    the thread of 2026-09-10 at 13:08. It did not answer once.

    This test reads a real file, in the state machines carry one.
    """

    ANCIEN = """
[assistant]
actif = false
nom = "Lucie"
voix = "kokoro"
initiative = false
"""

    def _boutons(self, tmp_path, monkeypatch, contenu: str):
        from greffier.cli import _reread_the_buttons

        dossier = tmp_path / "greffier"
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "config.toml").write_text(contenu, encoding="utf-8")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("APPDATA", str(tmp_path))
        for clef in ("GREFFIER_ASSISTANT__ACTIVE", "GREFFIER_ASSISTANT__VOICE",
                     "GREFFIER_ASSISTANT__INITIATIVE"):
            monkeypatch.delenv(clef, raising=False)
        return _reread_the_buttons()

    def test_a_file_saying_active_false_no_longer_cuts_the_voice(
        self, tmp_path, monkeypatch
    ):
        a_voix_haute, _de_lui_meme = self._boutons(tmp_path, monkeypatch, self.ANCIEN)
        assert a_voix_haute, "la voix est réglée sur kokoro : elle doit parler"

    def test_cutting_the_voice_is_still_possible(self, tmp_path, monkeypatch):
        """The only setting that still decides, and it has to decide."""
        a_voix_haute, _ = self._boutons(
            tmp_path, monkeypatch,
            '[assistant]\nactif = true\nnom = "Lucie"\nvoix = "aucun"\n',
        )
        assert not a_voix_haute

    def test_the_initiative_is_read_from_the_file(self, tmp_path, monkeypatch):
        _, de_lui_meme = self._boutons(
            tmp_path, monkeypatch,
            '[assistant]\nnom = "Lucie"\nvoix = "kokoro"\ninitiative = true\n',
        )
        assert de_lui_meme

    def test_called_it_answers_despite_the_old_setting(
            self, called_by_its_name, meeting, tmp_path):
        """The whole scenario, with the file that had silenced it."""
        transcriber = light_transcriber(Config())
        if transcriber is None:
            pytest.skip("aucun modèle de transcription installé")
        import soundfile

        voice, cerveau = FakeVoiceAdapter(), FakeBrain()
        assistant = AssistantSettings(
            name="Lucie", voice=voice, cerveau=cerveau,
            manners=Manners(creux_minimal=0.0),
            context=lambda: "Réunion d'équipe sur la recette.",
        )
        watcher = Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=tmp_path / "propositions.jsonl",
            transcriber=transcriber,
            situer=lambda: Position(
                morceau=meeting,
                written=soundfile.info(str(meeting)).duration,
                offset=0.0,
            ),
            assistant_of=assistant,
            # What the watch reads from the file: the voice is granted, no
            # initiative. "actif" no longer enters the decision.
            reread_participation=lambda: (True, False),
        )
        watcher.transcription_turn(watcher.situer(), tmp_path)
        if assistant._job is not None:
            assistant._job.join(timeout=30)
        assert voice.remark, "appelée par son nom, elle doit avoir parlé"
