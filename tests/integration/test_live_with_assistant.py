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

SENTENCE = "Lucie, est-ce que tu peux nous rappeler ce qui reste à faire ?"


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
        self.own_guidance = ""
        self.vu = []

    def write_up(self, text):
        self.vu.append(text)
        return "Il reste la signature, et la recette à caler."


@pytest.fixture
def meeting(tmp_path):
    out_of_reach = voices_are_out_of_reach(1)
    if out_of_reach:
        pytest.skip(out_of_reach)
    from make_meeting import speak

    audio = speak(SENTENCE, "Thomas", tmp_path / "reunion.wav")
    if audio is None:
        pytest.skip("synthèse impossible")
    return audio


@pytest.fixture
def called_by_its_name():
    """These tests only mean something where the name survives the round trip."""
    out_of_reach = the_called_name_is_out_of_reach()
    if out_of_reach:
        pytest.skip(out_of_reach)


def test_called_during_the_meeting_it_answers(called_by_its_name, meeting, tmp_path):
    """The scenario of the demonstration, end to end."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    voice, the_brain = FakeVoiceAdapter(), FakeBrain()
    assistant = AssistantSettings(
        name="Lucie", voice=voice, the_brain=the_brain,
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
        locate=lambda: Position(chunk=meeting, written=duration, offset=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.locate(), tmp_path)
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

    gone = threading.Event()

    class SlowBrain(FakeBrain):
        def write_up(self, text):
            gone.set()
            time.sleep(5.0)
            return "…"

    assistant = AssistantSettings(
        name="Lucie", voice=FakeVoiceAdapter(), the_brain=SlowBrain(),
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion.",
    )
    import soundfile

    duration = soundfile.info(str(meeting)).duration
    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        locate=lambda: Position(chunk=meeting, written=duration, offset=0.0),
        assistant_of=assistant,
    )
    # The model loads at the first transcription -- sixteen seconds on a
    # card, measured. Counting it here would fail the test on a perfectly
    # healthy machine, for a slowness that only happens once per session.
    transcriber.transcribe(meeting, "fr", "")
    depart = time.monotonic()
    watcher.transcription_turn(watcher.locate(), tmp_path)
    rendered = time.monotonic() - depart

    assert gone.wait(timeout=10), "l'assistant n'a pas été sollicité"
    # The transcription itself takes a few seconds; what is checked is that it
    # did not wait for the brain's five on top of them.
    assert rendered < 5.0, f"la veille a attendu la réponse ({rendered:.1f} s)"


def test_an_ordinary_sentence_does_not_make_it_speak(tmp_path):
    """Without its name nothing fires, which is the case for the whole meeting."""
    out_of_reach = voices_are_out_of_reach(1)
    if out_of_reach:
        pytest.skip(out_of_reach)
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
        locate=lambda: Position(chunk=audio, written=soundfile.info(str(audio)).duration,
                                offset=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.locate(), tmp_path)
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
        locate=lambda: Position(chunk=meeting,
                                written=soundfile.info(str(meeting)).duration,
                                offset=0.0),
    )
    watcher.transcription_turn(watcher.locate(), tmp_path)


def test_the_reason_for_speaking_is_the_call(called_by_its_name, meeting, tmp_path):
    """It is not a spontaneous contribution: she was named."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    utterances = transcriber.transcribe(meeting, "fr", "Lucie.")
    assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=0.0))
    retained = assistant.turn(utterances, now=max(
        r.span.end for r in utterances) + 1.0)
    assert retained is not None and retained.because is Because.CALLED


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

    def _thread(self):
        from greffier.domain.models import Span, Utterance

        said_ones = []
        for text, depart, how_many in self.OBSERVE:
            said_ones += [
                Utterance(span=Span(depart + i, depart + i + 1), text=text)
                for i in range(how_many)
            ]
        return sorted(said_ones, key=lambda u: u.span.start)

    def test_the_four_loops_fold_up(self):
        from greffier.domain.boilerplate import collapse_loops

        earlier = self._thread()
        later = collapse_loops(earlier)
        assert len(earlier) == 43
        assert len(later) == 4, [u.text for u in later]

    def test_every_kept_sentence_covers_its_run(self):
        from greffier.domain.boilerplate import collapse_loops

        for kept_one in collapse_loops(self._thread()):
            expected = next(c for t, _d, c in self.OBSERVE if t == kept_one.text)
            assert kept_one.span.end - kept_one.span.start == expected

    def test_the_published_thread_no_longer_carries_the_repetition(self):
        """What the window shows: one line per sentence said."""
        from greffier.domain.boilerplate import collapse_loops

        texts = [u.text for u in collapse_loops(self._thread())]
        assert len(texts) == len(set(texts))


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

    OLD = """
[assistant]
actif = false
nom = "Lucie"
voix = "kokoro"
initiative = false
"""

    def _buttons(self, tmp_path, monkeypatch, content: str):
        from greffier.cli import _reread_the_buttons

        folder = tmp_path / "greffier"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.toml").write_text(content, encoding="utf-8")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("APPDATA", str(tmp_path))
        for clef in ("GREFFIER_ASSISTANT__ACTIVE", "GREFFIER_ASSISTANT__VOICE",
                     "GREFFIER_ASSISTANT__INITIATIVE"):
            monkeypatch.delenv(clef, raising=False)
        return _reread_the_buttons()

    def test_a_file_saying_active_false_no_longer_cuts_the_voice(
        self, tmp_path, monkeypatch
    ):
        out_loud, _of_its_own = self._buttons(tmp_path, monkeypatch, self.OLD)
        assert out_loud, "la voix est réglée sur kokoro : elle doit parler"

    def test_cutting_the_voice_is_still_possible(self, tmp_path, monkeypatch):
        """The only setting that still decides, and it has to decide."""
        out_loud, _ = self._buttons(
            tmp_path, monkeypatch,
            '[assistant]\nactif = true\nnom = "Lucie"\nvoix = "aucun"\n',
        )
        assert not out_loud

    def test_the_initiative_is_read_from_the_file(self, tmp_path, monkeypatch):
        _, of_its_own = self._buttons(
            tmp_path, monkeypatch,
            '[assistant]\nnom = "Lucie"\nvoix = "kokoro"\ninitiative = true\n',
        )
        assert of_its_own

    def test_called_it_answers_despite_the_old_setting(
            self, called_by_its_name, meeting, tmp_path):
        """The whole scenario, with the file that had silenced it."""
        transcriber = light_transcriber(Config())
        if transcriber is None:
            pytest.skip("aucun modèle de transcription installé")
        import soundfile

        voice, the_brain = FakeVoiceAdapter(), FakeBrain()
        assistant = AssistantSettings(
            name="Lucie", voice=voice, the_brain=the_brain,
            manners=Manners(creux_minimal=0.0),
            context=lambda: "Réunion d'équipe sur la recette.",
        )
        watcher = Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=tmp_path / "propositions.jsonl",
            transcriber=transcriber,
            locate=lambda: Position(
                chunk=meeting,
                written=soundfile.info(str(meeting)).duration,
                offset=0.0,
            ),
            assistant_of=assistant,
            # What the watch reads from the file: the voice is granted, no
            # initiative. "actif" no longer enters the decision.
            reread_participation=lambda: (True, False),
        )
        watcher.transcription_turn(watcher.locate(), tmp_path)
        if assistant._job is not None:
            assistant._job.join(timeout=30)
        assert voice.remark, "appelée par son nom, elle doit avoir parlé"
