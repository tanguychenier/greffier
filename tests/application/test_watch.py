"""The watch during a meeting, with no mic and no clipboard."""

import json
import pathlib
from pathlib import Path

import pytest

from greffier.application import watch
from greffier.application.follow import Follower, Position
from greffier.application.watch import Watcher
from greffier.domain.instructions import Kind, WatchRules
from greffier.domain.live import LiveThread
from greffier.domain.models import Span, Utterance


class SliceTranscriber:
    """Returns, for each slice, the utterances it was given in advance."""

    def __init__(self, slices):
        self.slices = list(slices)
        self.calls = 0

    def transcribe(self, audio, language, prompt_seed):
        self.calls += 1
        return self.slices.pop(0) if self.slices else []


def utterance(start, text):
    return Utterance(span=Span(start, start + 4), text=text)


def watcher(tmp_path, **overrides):
    defects = dict(watch_rules=WatchRules(), log=tmp_path / "propositions.jsonl")
    defects.update(overrides)
    return Watcher(**defects)


def where_in(tmp_path, written, offset=0.0):
    """The position in the audio actually written, as the live thread reads it."""
    return Position(chunk=tmp_path / "r-01.wav", written=written, offset=offset)


class TestTheClipboard:
    def test_a_pasted_link_becomes_a_suggestion(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "voir https://miro.com/x")
        fresh = watcher(tmp_path).clipboard_turn(12.0)
        assert [p.text for p in fresh] == ["https://miro.com/x"]

    def test_the_same_link_is_not_offered_every_turn(self, tmp_path, monkeypatch):
        """The clipboard is reread every two seconds."""
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://miro.com/x")
        instance = watcher(tmp_path)
        assert len(instance.clipboard_turn(2.0)) == 1
        assert instance.clipboard_turn(4.0) == []

    def test_an_empty_clipboard_does_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        assert watcher(tmp_path).clipboard_turn(1.0) == []


class TestTheSuggestionsLog:
    def test_every_suggestion_is_one_line(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://a.fr https://b.fr")
        instance = watcher(tmp_path)
        instance.clipboard_turn(7.0)
        lines = (tmp_path / "propositions.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        first_call = json.loads(lines[0])
        assert first_call["genre"] == Kind.LINK.value
        assert first_call["instant"] == 7.0

    def test_the_log_is_appended_to_and_never_rewritten(self, tmp_path, monkeypatch):
        """An interruption must lose nothing of what came before."""
        instance = watcher(tmp_path)
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://a.fr")
        instance.clipboard_turn(1.0)
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "https://b.fr")
        instance.clipboard_turn(2.0)
        assert len((tmp_path / "propositions.jsonl").read_text().strip().splitlines()) == 2


class TestTranscribingAsItGoes:
    def test_the_instants_are_put_back_on_the_meeting_clock(self, tmp_path, monkeypatch):
        """An utterance dated inside its slice would point at the wrong moment."""
        monkeypatch.setattr(watch, "CONTEXT_S", 50.0)
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        # The transcribed window starts CONTEXT_S before the slice: an
        # utterance said 3 s into the slice is dated that much later in it.
        transcriber = SliceTranscriber(
            [[utterance(watch.CONTEXT_S + 3, "Greffier, ouvre le tableau")]]
        )
        instance = watcher(tmp_path, transcriber=transcriber, processed=120.0)
        fresh = instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        # 120 s already read, 5 s of overlap: the slice starts at 115 s.
        assert fresh[0].at_instant == 118.0

    def test_the_timestamps_follow_the_pieces_not_the_clock(self, tmp_path, monkeypatch):
        """After a pause, the audio written and the clock have drifted apart.

        The second piece restarts at zero in its own file: without the offset, a
        sentence said in the fortieth minute would show up in the second.
        """
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber(
            [[utterance(2, "Greffier, ouvre le ticket")]]
        )
        # The piece carries only 20 s: the window cannot reach further back
        # than its start, so the times are the slice's own.
        instance = watcher(tmp_path, transcriber=transcriber, processed=1800.0)
        fresh = instance.transcription_turn(
            where_in(tmp_path, written=20.0, offset=1800.0), tmp_path
        )
        # Half an hour already recorded before this piece, plus 2 s into it.
        assert fresh[0].at_instant == 1802.0

    def test_too_short_a_slice_is_not_transcribed(self, tmp_path, monkeypatch):
        # The model invents more than it hears on two seconds of audio.
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[utterance(0, "à peine un mot")]])
        instance = watcher(tmp_path, transcriber=transcriber)
        assert instance.transcription_turn(where_in(tmp_path, written=2.0), tmp_path) == []
        assert transcriber.calls == 0

    def test_the_text_overlap_between_two_slices_is_removed(
        self, tmp_path, monkeypatch
    ):
        """The real pipeline, with no model: only the transcriber port is a double. A
        sentence astride two successive slices must no longer show up with the end of
        the previous one glued in front.
        """
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([
            # Slice 1 (0-10 s of meeting): a sentence ends at 8 s.
            [Utterance(Span(0, 8), "c'est notre dernier.")],
            # Slice 2: the window starts again at 0 s, the piece carrying no
            # more, and the sentence astride is dated 8 to 14 s there, as the
            # model will date it. It overflows the slice, which starts at 5 s.
            [Utterance(Span(8, 14), "dernier. Sandy, tu peux nous dire où on en est ?")],
        ])
        follower = Follower(thread=LiveThread(), log=tmp_path / "direct.jsonl",
                       requests=tmp_path / "demandes.jsonl")
        instance = watcher(tmp_path, transcriber=transcriber, follower=follower)
        instance.transcription_turn(where_in(tmp_path, written=10.0), tmp_path)
        instance.transcription_turn(where_in(tmp_path, written=20.0), tmp_path)
        assert follower.thread.turns[-1].text == "Sandy, tu peux nous dire où on en est ?"

    def test_a_failed_slice_does_not_grow_for_ever(self, tmp_path, monkeypatch):
        """A lasting failure would grow the slice into minutes of computation."""
        requested_ones = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: requested_ones.append((start, end)) or None,
        )
        instance = watcher(tmp_path, transcriber=SliceTranscriber([]))
        instance.transcription_turn(where_in(tmp_path, written=600.0), tmp_path)
        start, end = requested_ones[0]
        assert end - start == watch.SLICE_MAXIMUM

    def test_an_unreadable_slice_does_not_stop_the_watch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "extract_slice", lambda *args: None)
        instance = watcher(tmp_path, transcriber=SliceTranscriber([]))
        assert instance.transcription_turn(where_in(tmp_path, written=30.0), tmp_path) == []

    def test_with_no_transcriber_only_the_clipboard_watch_runs(self, tmp_path):
        watch = watcher(tmp_path)
        assert watch.transcription_turn(where_in(tmp_path, written=30.0), tmp_path) == []


class TestTheEndOfTheMeeting:
    """The last seconds must not stay in the pipe.

    With no catching up, up to one period of audio is always left untranscribed:
    you finish your sentence in front of a thread that stops before it.
    """

    def test_audio_that_stops_growing_is_still_transcribed(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[utterance(1, "Greffier, ouvre le ticket")]])
        instance = watcher(tmp_path, transcriber=transcriber, slice_period=30.0)
        frozen = where_in(tmp_path, written=6.0)
        # First pass: whether the capture advances is not known yet.
        assert not instance._is_time(frozen)
        # Second: the size has not moved, 6 s are left to say.
        assert instance._is_time(frozen)

    def test_the_last_pass_catches_what_was_left(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[utterance(1, "Greffier, ouvre le ticket")]])
        instance = watcher(
            tmp_path, transcriber=transcriber, slice_period=30.0,
            locate=lambda: where_in(tmp_path, written=12.0),
        )
        # The meeting stops at once: nothing reached the period.
        propositions = instance.loop(
            still_running=lambda: False, since=lambda: 0.0, job=tmp_path,
            pause=lambda _: None,
        )
        assert transcriber.calls == 1
        assert propositions

    def test_too_short_a_remainder_triggers_nothing(self, tmp_path):
        instance = watcher(tmp_path, slice_period=30.0)
        frozen = where_in(tmp_path, written=1.5)
        instance._is_time(frozen)
        assert not instance._is_time(frozen)


class TestTheWholeLoop:
    def test_the_two_rhythms_live_together(self, tmp_path, monkeypatch):
        """The clipboard is reread often, the transcription rarely: one slice costs
        several seconds of computation.
        """
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[], [], []])
        written = {"s": 0.0}
        instance = watcher(
            tmp_path,
            transcriber=transcriber,
            locate=lambda: where_in(tmp_path, written=written["s"]),
        )

        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 40

        instance.loop(
            still_running=still_running,
            since=lambda: written["s"],
            job=tmp_path,
            # Every two-second pause adds two seconds of written audio.
            pause=lambda _: written.__setitem__("s", written["s"] + 2.0),
        )
        # 40 turns × 2 s = 80 s: two slices of 30 s, not forty, plus the last
        # pass, which catches the final twenty seconds.
        assert transcriber.calls == 3

    def test_the_rhythm_follows_the_audio_written_not_the_clock(self, tmp_path, monkeypatch):
        """On pause the file stops growing: one slice, not forty.

        That one is necessary, being the catch-up that shows the end of what has just
        been said. After it there is nothing new, and a clock that keeps advancing
        must not ask for slices of a passage that does not exist.
        """
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[], []])
        clock = {"t": 0.0}
        instance = watcher(
            tmp_path,
            transcriber=transcriber,
            # The audio stays frozen: the recording is paused.
            locate=lambda: where_in(tmp_path, written=4.0),
        )
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 40

        instance.loop(
            still_running=still_running, since=lambda: clock["t"], job=tmp_path,
            pause=lambda _: clock.__setitem__("t", clock["t"] + 2.0),
        )
        assert transcriber.calls == 1

    def test_the_loop_stops_with_the_recording(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        instance = watcher(tmp_path)
        assert instance.loop(still_running=lambda: False, since=lambda: 0.0,
                                job=tmp_path, pause=lambda _: None) == []


class TestAJoinPublishedToTheWindow:
    """A join between voices travels through the log, like the turns.

    The window rebuilds the thread without ever computing a voiceprint: what it
    needs is the result of the stitching, not the means to redo it.
    """

    def test_a_join_replays_from_the_log(self):
        from greffier.application.follow import KIND_MEETING, KIND_TURN, replay

        lines = [
            {"genre": KIND_TURN, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": KIND_TURN, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            {"genre": KIND_MEETING, "voix": "v2", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}
        assert "v2" not in thread.voice

    def test_a_name_given_by_hand_survives_the_replayed_join(self):
        from greffier.application.follow import KIND_CORRECTION, KIND_MEETING, KIND_TURN, replay

        lines = [
            {"genre": KIND_TURN, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": KIND_TURN, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            # "toute_la_voix" spelled out, as the log now writes it: deducing
            # it from the number of turns replayed a correction covering a
            # one-turn voice as "only this sentence".
            {"genre": KIND_CORRECTION, "nom": "Sophie", "voix": "v2",
             "numeros": [2], "toute_la_voix": True},
            {"genre": KIND_MEETING, "voix": "v2", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}
        assert thread.voice["v1"].name == "Sophie"

    def test_an_incomplete_join_line_is_ignored(self):
        """A truncated log must not bring the window down."""
        from greffier.application.follow import KIND_MEETING, KIND_TURN, replay

        lines = [
            {"genre": KIND_TURN, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": KIND_MEETING, "voix": "v1"},
            {"genre": KIND_MEETING, "vers": "v1"},
            {"genre": KIND_MEETING, "voix": "v1", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}


class TestThePromptSeedRereadMidMeeting:
    """A term learnt during a meeting must serve the next sentence.

    The live process froze its seed at startup, so adding "OTP" during the meeting
    only served the meeting after, when a meeting is precisely where the missing
    words are discovered.
    """

    def watcher_with(self, prompt_seed: str, reread_it=None):
        return Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=pathlib.Path("/tmp/greffier-essai.jsonl"),
            transcriber=None,
            locate=lambda: None,
            prompt_seed=prompt_seed,
            reread_the_seed=reread_it,
        )

    def test_without_rereading_the_seed_does_not_change(self):
        watcher = self.watcher_with("Vocabulaire : CASA.")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_a_fresh_seed_replaces_the_old_one(self):
        watcher = self.watcher_with(
            "Vocabulaire : CASA.", reread_it=lambda: "Vocabulaire : CASA, OTP."
        )
        assert "OTP" in watcher._current_prompt_seed()
        assert "OTP" in watcher.prompt_seed, "la nouvelle est retenue"

    def test_an_empty_reread_does_not_lose_the_seed(self):
        """A context momentarily unreadable must not degrade the slice."""
        watcher = self.watcher_with("Vocabulaire : CASA.", reread_it=lambda: "")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_a_reread_that_fails_does_not_raise(self):
        def fall():
            raise OSError("fichier occupé")

        watcher = self.watcher_with("Vocabulaire : CASA.", reread_it=fall)
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."


class TestTheWindowOfContext:
    """The model receives what came before, and shows none of it again.

    Measured on 2026-09-09 on a real meeting: the same passage gives "sur la ZIS"
    with a 15 s window, "sur Asis" with 30 s, "sur Oasis" with 60 s. The context
    makes the right word, but it must repeat nothing. The tests below set
    the window themselves: what they hold is the mechanism, not the figure,
    which `docs/corpus.md` settles.
    """

    @pytest.fixture(autouse=True)
    def _a_wide_window(self, monkeypatch):
        monkeypatch.setattr(watch, "CONTEXT_S", 50.0)

    def test_the_model_gets_more_audio_than_the_slice(self, tmp_path, monkeypatch):
        requested_ones = []

        def extract(audio, start, end, dest):
            requested_ones.append((start, end))
            return dest

        monkeypatch.setattr(watch, "extract_slice", extract)
        transcriber = SliceTranscriber([[]])
        instance = watcher(tmp_path, transcriber=transcriber, processed=120.0)
        instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        slice_, window = requested_ones
        assert slice_ == (115.0, 150.0)
        assert window == (115.0 - watch.CONTEXT_S, 150.0)

    def test_what_is_in_the_context_is_not_shown_again(self, tmp_path, monkeypatch):
        """Sinon chaque phrase s'afficherait six fois."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[
            utterance(2, "phrase déjà affichée, dans le contexte"),
            utterance(watch.CONTEXT_S + 1, "phrase neuve, dans la tranche"),
        ]])
        instance = watcher(tmp_path, transcriber=transcriber, processed=120.0)
        fresh = instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        watch_instance = [p.text for p in fresh]
        assert not any("déjà affichée" in t for t in watch_instance)

    def test_at_the_start_the_window_does_not_reach_before_zero(
        self, tmp_path, monkeypatch
    ):
        requested_ones = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: requested_ones.append(start) or dest,
        )
        transcriber = SliceTranscriber([[]])
        instance = watcher(tmp_path, transcriber=transcriber)
        instance.transcription_turn(where_in(tmp_path, written=12.0), tmp_path)
        assert all(start >= 0.0 for start in requested_ones)

    def test_an_utterance_astride_is_kept_whole(self):
        """Cutting a sentence in the middle is worth less than removing its shown start."""
        kept = watch._within_the_slice(
            [Utterance(Span(8, 14), "dernier. Sandy, tu peux nous dire…")], 10.0
        )
        assert len(kept) == 1
        assert kept[0].span.start == 0.0
        assert kept[0].span.end == 4.0

    def test_an_utterance_wholly_inside_the_context_goes(self):
        assert watch._within_the_slice(
            [Utterance(Span(2, 6), "déjà dit")], 10.0
        ) == []

    def test_with_no_context_nothing_is_touched(self):
        utterances = [Utterance(Span(2, 6), "du texte")]
        assert watch._within_the_slice(utterances, 0.0) == utterances



class TestTheTwoButtonsDuringAMeeting:
    """The window and the watch are two processes.

    The buttons write into the settings, the watch rereads them on every slice.
    Without that the meeting would have to be restarted to change one's mind,
    which makes no sense.

    Two buttons: **the voice**, whether it is heard in the room, and **the
    initiative**, whether it may speak without being called. It always takes part.
    Listening, taking notes and asking its questions in writing is its job, and a
    third setting that unplugged it meant it stopped answering to its name with
    nothing to say so.
    """

    def _watcher(self, assistant_of, buttons, new_voice=None):
        from greffier.application.watch import Watcher
        from greffier.domain.instructions import WatchRules

        return Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=Path("/tmp/inutilise.jsonl"),
            assistant_of=assistant_of,
            reread_participation=lambda: buttons,
            give_voice_back=(lambda: new_voice) if new_voice else None,
        )

    def _assistant_of(self, with_voice=True):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class FakeVoice:
            def __init__(self):
                self.kills = False

            def say(self, _t):
                return True

            def go_quiet(self):
                self.kills = True

            def is_speaking(self):
                return False

        return AssistantSettings(name="Lucie", voice=FakeVoice() if with_voice else None,
                           manners=Manners(active=True))

    def test_cutting_the_voice_stops_it_at_once(self):
        """Pressing it while it speaks must cut, not wait for the end."""
        her = self._assistant_of()
        voice = her.voice
        self._watcher(her, (False, False))._apply_the_buttons(False, False)
        assert voice.kills

    def test_taking_the_voice_away_leaves_it_writing(self):
        her = self._assistant_of()
        self._watcher(her, (False, False))._apply_the_buttons(False, False)
        assert her.voice is None
        assert her.manners.active, "il participe toujours, sans se faire entendre"

    def test_giving_the_voice_back_loads_it_once(self):
        """Loading a model costs: it is done only when asked for."""
        her = self._assistant_of(with_voice=False)
        new_one = object()
        watcher = self._watcher(her, (True, False), new_voice=new_one)
        watcher._apply_the_buttons(True, False)
        assert her.voice is new_one

    def test_with_no_way_to_give_it_back_it_stays_silent(self):
        """No model installed: it takes part in writing, without complaining."""
        her = self._assistant_of(with_voice=False)
        self._watcher(her, (True, False))._apply_the_buttons(True, False)
        assert her.voice is None and her.manners.active

    def test_the_initiative_can_be_taken_mid_meeting(self):
        """The button only took effect at the next meeting, which nobody could guess."""
        her = self._assistant_of()
        watcher = self._watcher(her, (True, True))
        assert not watcher.initiative, "livrée éteinte"
        watcher._apply_the_buttons(True, True)
        assert watcher.initiative

    def test_the_initiative_can_be_taken_back_too(self):
        her = self._assistant_of()
        watcher = self._watcher(her, (True, False))
        watcher.initiative = True
        watcher._apply_the_buttons(True, False)
        assert not watcher.initiative

    def test_without_the_initiative_it_does_not_ask_who_is_speaking(self):
        """The rule that makes it bearable: a word only when it is called."""
        her = self._assistant_of()
        watcher = self._watcher(her, (True, False))
        watcher._apply_the_buttons(True, False)
        assert watcher._voices_to_ask_about(now=600.0) == []

    def test_nothing_changes_when_nothing_changes(self):
        her = self._assistant_of()
        voice = her.voice
        self._watcher(her, (True, True))._apply_the_buttons(True, True)
        assert her.manners.active and her.voice is voice and not voice.kills


class TestOnceTheMeetingEnds:
    """Clicking "end the meeting" must end it, the assistant included.

    The last slice is still transcribed, so nothing said at the very end is
    lost, but it is transcribed silently: an answer coming out of the speakers
    in a room that has just been told the meeting is over would be the one
    thing everybody remembers of the demonstration.
    """

    class FakeVoice:
        def __init__(self):
            self.kills = False
            self.said = []

        def say(self, text):
            self.said.append(text)
            return True

        def go_quiet(self):
            self.kills = True

        def is_speaking(self):
            return False

    def _assistant(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        return AssistantSettings(
            name="Lucie", voice=self.FakeVoice(), manners=Manners(active=True),
        )

    def _watcher(self, tmp_path, monkeypatch, written, her):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        return watcher(
            tmp_path,
            transcriber=SliceTranscriber([[utterance(0.0, "Lucie, tu en penses quoi ?")]]),
            locate=lambda: where_in(tmp_path, written=written),
            assistant_of=her,
        )

    def test_the_last_slice_is_still_transcribed(self, tmp_path, monkeypatch):
        her = self._assistant()
        instance = self._watcher(tmp_path, monkeypatch, 20.0, her)
        instance.last_pass(tmp_path)
        assert instance.processed == 20.0, "the closing audio is read"

    def test_she_does_not_answer_on_the_last_slice(self, tmp_path, monkeypatch):
        """Called by name in the last seconds: transcribed, not answered."""
        her = self._assistant()
        calls = []
        her.answer_aside = lambda opening, now: calls.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, 20.0, her)
        instance.last_pass(tmp_path)
        assert calls == []

    def test_she_answers_on_an_ordinary_slice(self, tmp_path, monkeypatch):
        """The counter-proof: the same slice mid-meeting does reach her."""
        her = self._assistant()
        calls = []
        her.answer_aside = lambda opening, now: calls.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, 20.0, her)
        instance.transcription_turn(where_in(tmp_path, written=20.0), tmp_path)
        assert len(calls) == 1

    def test_the_voice_is_cut_when_the_loop_ends(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        her = self._assistant()
        voice = her.voice
        watcher(tmp_path, assistant_of=her).loop(
            still_running=lambda: False, since=lambda: 0.0, job=tmp_path,
            pause=lambda _: None,
        )
        assert voice.kills, "a sentence under way stops with the meeting"
        assert her.stopped

    def test_a_watch_without_an_assistant_ends_quietly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        watcher(tmp_path).loop(still_running=lambda: False, since=lambda: 0.0,
                               job=tmp_path, pause=lambda _: None)


class TestSheAnswersWithoutWaitingForTheSlice:
    """Being called cost up to fifteen seconds before a word came back.

    Measured on this machine, at the settings it carries: the watch takes one
    full slice every ten seconds, that slice carries fifty seconds of context so
    the spelling holds and costs 2 s to transcribe, and the model that phrases
    the answer costs 3 s whichever one is asked. Being called therefore waited
    for the next slice boundary, and a few seconds were expected.

    Reading the last eight seconds alone, with no context, costs 0.8 s. It only
    looks for the assistant's own name, and the remark it hands over carries a
    subject, so the same call arriving again in the full slice is refused as
    already answered rather than answered twice.
    """

    class Listening:
        """A transcriber that returns what was said, and counts its calls."""

        def __init__(self, text="Lucie, tu en penses quoi ?"):
            self.text = text
            self.calls = 0

        def transcribe(self, audio, language, prompt_seed):
            self.calls += 1
            return [Utterance(span=Span(0.0, 3.0), text=self.text)]

    def _her(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Je regarde."

        return AssistantSettings(name="Lucie", brain=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def _watcher(self, tmp_path, monkeypatch, her, listening):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        return watcher(tmp_path, transcriber=listening, assistant_of=her,
                       locate=lambda: where_in(tmp_path, written=8.0))

    def test_a_call_is_answered_before_the_slice(self, tmp_path, monkeypatch):
        her, listening = self._her(), self.Listening()
        said_ones = []
        her.answer_aside = lambda opening, now: said_ones.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, her, listening)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert len(said_ones) == 1
        assert listening.calls == 1

    def test_an_ordinary_sentence_costs_nothing_but_the_listening(
        self, tmp_path, monkeypatch
    ):
        """The model is not called for a sentence that does not name it."""
        her = self._her()
        listening = self.Listening("on se cale jeudi pour la recette")
        said_ones = []
        her.answer_aside = lambda opening, now: said_ones.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, her, listening)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert said_ones == []

    def test_the_same_call_is_not_answered_twice(self, tmp_path, monkeypatch):
        """The listening pass answers; the full slice must then keep quiet."""
        her, listening = self._her(), self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, her, listening)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        if her._job is not None:
            her._job.join(timeout=5)
        said_ones = []
        her.answer_aside = lambda opening, now: said_ones.append(opening)
        instance.assistant_turn(
            [utterance(0.0, "Lucie, tu en penses quoi ?")], 8.0
        )
        assert said_ones == [], "la tranche complète ne doit pas répéter la réponse"

    def test_it_does_not_listen_while_it_is_speaking(self, tmp_path, monkeypatch):
        her, listening = self._her(), self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, her, listening)

        class Busy:
            def is_alive(self):
                return True

        her._job = Busy()
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert listening.calls == 0

    def test_it_listens_at_its_own_pace(self, tmp_path, monkeypatch):
        """Every clipboard turn would cost 0.8 s of transcription every 2 s."""
        her, listening = self._her(), self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, her, listening)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        # The answer to the first call runs in a thread, and nothing is listened
        # for while it speaks. Left to chance, this test measured the machine's
        # load rather than the pace: one run in three, the thread was still
        # alive at the third turn, which then refused for the right reason and
        # the wrong one.
        if her._job is not None:
            her._job.join(timeout=5)
        instance.listening_turn(where_in(tmp_path, written=9.0), tmp_path)
        assert listening.calls == 1, "une seconde plus tard, on n'écoute pas encore"
        instance.listening_turn(where_in(tmp_path, written=12.0), tmp_path)
        assert listening.calls == 2

    def test_with_no_assistant_nothing_is_transcribed(self, tmp_path, monkeypatch):
        listening = self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, None, listening)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert listening.calls == 0

    def test_an_assistant_switched_off_is_not_listened_for(
        self, tmp_path, monkeypatch
    ):
        from greffier.domain.participation import Manners

        her, listening = self._her(), self.Listening()
        her.manners = Manners(active=False)
        instance = self._watcher(tmp_path, monkeypatch, her, listening)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert listening.calls == 0

    def test_too_little_audio_is_not_read(self, tmp_path, monkeypatch):
        her, listening = self._her(), self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, her, listening)
        instance.listening_turn(where_in(tmp_path, written=1.0), tmp_path)
        assert listening.calls == 0

    def test_the_loop_listens_between_two_slices(self, tmp_path, monkeypatch):
        """The whole point: it happens on the clipboard rhythm, not the slice."""
        her, listening = self._her(), self.Listening()
        said_ones = []
        her.answer_aside = lambda opening, now: said_ones.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, her, listening)
        instance.slice_period = 30.0
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 3

        instance.loop(still_running=still_running, since=lambda: 8.0, job=tmp_path,
                      pause=lambda _: None)
        assert said_ones, "elle a répondu sans attendre la tranche de trente secondes"


class TestTheListeningPassHasItsOwnThread:
    """Measured on a loaded machine: the assistant answered a question twenty
    seconds after the next one had been asked. The pass that spots her name
    took its turn in the loop, after the full slice, and a slice that takes
    longer than its period never leaves a turn.
    """

    class SlowSlice:
        """Slow on the full slice, immediate on the listening pass."""

        def __init__(self, slice_seconds):
            self.slice_seconds = slice_seconds
            self.slice_ended_at = None

        def transcribe(self, audio, language, prompt_seed):
            import time

            if audio.name != "ecoute.wav":
                time.sleep(self.slice_seconds)
                self.slice_ended_at = time.monotonic()
                return [utterance(0.0, "on continue sur la recette")]
            return [Utterance(span=Span(0.0, 3.0), text="Lucie, tu en penses quoi ?")]

    def _her(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Je regarde."

        return AssistantSettings(name="Lucie", brain=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def test_a_call_is_heard_while_a_slow_slice_is_transcribed(
        self, tmp_path, monkeypatch
    ):
        import time

        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        her, slow = self._her(), self.SlowSlice(slice_seconds=0.6)
        spotted = []
        her.answer_aside = lambda opening, now: spotted.append(time.monotonic())
        instance = watcher(tmp_path, transcriber=slow, assistant_of=her,
                           locate=lambda: where_in(tmp_path, written=8.0),
                           slice_period=1.0)
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 2

        instance.loop(still_running=still_running, since=lambda: 8.0, job=tmp_path,
                      pause=lambda _: None)
        assert spotted, "her name was heard"
        assert slow.slice_ended_at is not None
        assert spotted[0] < slow.slice_ended_at, (
            "the call was heard before the slow slice came back"
        )

    def test_the_thread_stops_with_the_loop(self, tmp_path, monkeypatch):
        import threading

        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        before = threading.active_count()
        instance = watcher(tmp_path, transcriber=self.SlowSlice(0.0),
                           assistant_of=self._her(),
                           locate=lambda: where_in(tmp_path, written=8.0))
        instance.loop(still_running=lambda: False, since=lambda: 8.0, job=tmp_path,
                      pause=lambda _: None)
        assert threading.active_count() <= before + 1, (
            "at most the answer's own thread outlives the loop"
        )

    def test_a_pass_that_breaks_does_not_end_the_listening(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)

        class Breaks:
            def __init__(self):
                self.calls = 0

            def transcribe(self, audio, language, prompt_seed):
                if audio.name != "ecoute.wav":
                    return []
                self.calls += 1
                raise ValueError("not one of the errors the pass expects")

        breaks = Breaks()
        her = self._her()
        clock = {"written": 8.0}

        def locate():
            # The meeting clock moves on, or the pass refuses to listen twice.
            clock["written"] += 1.0
            return where_in(tmp_path, written=clock["written"])

        instance = watcher(tmp_path, transcriber=breaks, assistant_of=her, locate=locate)
        monkeypatch.setattr(watch, "LISTENING_PERIOD", 0.05)
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 3

        instance.loop(still_running=still_running, since=lambda: 8.0, job=tmp_path,
                      pause=lambda _: __import__("time").sleep(0.1))
        assert breaks.calls >= 2, "listened again after the pass broke"


class TestItListensTheMomentSomebodyStops:
    """On the clock alone, the bench spotted a call 0.8 to 5.9 s after the
    question ended: a question that ended right after a pass waited for the
    next one. The levels of the file say when somebody stops, and that is the
    moment to listen.
    """

    class Listening:
        """Counts the listening passes alone: the last slice of the meeting
        goes through the same transcriber and must not be mistaken for one."""

        def __init__(self, end=3.0):
            self.end = end
            self.calls = 0

        def transcribe(self, audio, language, prompt_seed):
            if audio.name != "ecoute.wav":
                return []
            self.calls += 1
            return [Utterance(span=Span(0.0, self.end), text="Lucie, tu en penses quoi ?")]

    def _her(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Je regarde."

        return AssistantSettings(name="Lucie", brain=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def _watcher(self, tmp_path, monkeypatch, listening, speaking, clock):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        monkeypatch.setattr(watch, "LISTENING_POLL", 0.02)
        monkeypatch.setattr(watch, "LISTENING_PERIOD", 60.0)
        her = self._her()
        her.answer_aside = lambda opening, now: clock.setdefault("spotted", []).append(now)

        def locate():
            clock["now"] = clock.get("now", 8.0) + 0.1
            return where_in(tmp_path, written=clock["now"])

        return watcher(tmp_path, transcriber=listening, assistant_of=her,
                       locate=locate, speaking=speaking, slice_period=600.0)

    def _run(self, instance, tmp_path, rounds):
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= rounds

        instance.loop(still_running=still_running, since=lambda: 8.0, job=tmp_path,
                      pause=lambda _: __import__("time").sleep(0.05))

    def test_a_pass_runs_when_the_talking_stops_not_on_the_clock(
        self, tmp_path, monkeypatch
    ):
        clock = {}
        listening = self.Listening()
        # Talking until 9.0 s of meeting, quiet afterwards.
        instance = self._watcher(tmp_path, monkeypatch, listening,
                                 speaking=lambda where_: where_.written < 9.0, clock=clock)
        self._run(instance, tmp_path, rounds=8)
        assert clock.get("spotted"), "the call was heard"
        # The clock is a minute away: the only pass is the prompted one, half
        # a second of quiet after the talking stopped.
        assert listening.calls == 1
        assert 9.5 <= clock["spotted"][-1] <= 10.2, clock["spotted"]

    def test_the_clock_does_not_listen_to_a_room_quiet_since_the_last_pass(
        self, tmp_path, monkeypatch
    ):
        """On a small card every pass slows the one that matters."""
        clock = {}
        listening = self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, listening,
                                 speaking=lambda where_: False, clock=clock)
        monkeypatch.setattr(watch, "LISTENING_PERIOD", 0.1)
        self._run(instance, tmp_path, rounds=8)
        assert listening.calls == 0, "nobody spoke: nothing to listen to"

    def test_with_no_level_to_read_the_clock_alone_rules(self, tmp_path, monkeypatch):
        clock = {}
        listening = self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, listening,
                                 speaking=None, clock=clock)
        monkeypatch.setattr(watch, "LISTENING_PERIOD", 0.3)
        self._run(instance, tmp_path, rounds=8)
        assert listening.calls >= 2, "on the clock, quiet room or not"

    def test_a_level_that_cannot_be_told_prompts_nothing(self, tmp_path, monkeypatch):
        clock = {}
        listening = self.Listening()
        instance = self._watcher(tmp_path, monkeypatch, listening,
                                 speaking=lambda where_: None, clock=clock)
        self._run(instance, tmp_path, rounds=8)
        assert listening.calls == 0, "nothing prompted, and the clock a minute away"


class TestHalfAQuestionIsNotAnswered:
    """A pass that lands in the middle of a question reads half of it, and
    half a question answered is worse than a question answered late.
    """

    def _her(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Je regarde."

        return AssistantSettings(name="Lucie", brain=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def _spotted(self, tmp_path, monkeypatch, end):
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)

        class Listening:
            def transcribe(self, audio, language, prompt_seed):
                return [Utterance(span=Span(0.0, end), text="Lucie, à quel jour est-ce ?")]

        her = self._her()
        spotted = []
        her.answer_aside = lambda opening, now: spotted.append(opening.remark)
        instance = watcher(tmp_path, transcriber=Listening(), assistant_of=her)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        return spotted

    def test_a_sentence_running_into_the_end_of_the_window_waits(
        self, tmp_path, monkeypatch
    ):
        assert self._spotted(tmp_path, monkeypatch, end=7.9) == []

    def test_a_sentence_that_ended_before_the_window_is_answered(
        self, tmp_path, monkeypatch
    ):
        assert self._spotted(tmp_path, monkeypatch, end=7.0) == ["à quel jour est-ce ?"]


class TestAPromptedPassTrustsTheRoom:
    """A prompted pass comes half a second after the room went quiet: what it
    hears was finished, however late the model stamps its end.
    """

    def _her(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Je regarde."

        return AssistantSettings(name="Lucie", brain=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def _spotted(self, tmp_path, monkeypatch, prompted):
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)

        class Listening:
            def transcribe(self, audio, language, prompt_seed):
                # Stamped past the end of the window, as the model does.
                return [Utterance(span=Span(0.0, 8.2), text="Lucie, on décale à jeudi ?")]

        her = self._her()
        spotted = []
        her.answer_aside = lambda opening, now: spotted.append(opening.remark)
        instance = watcher(tmp_path, transcriber=Listening(), assistant_of=her)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path, prompted=prompted)
        return spotted

    def test_prompted_it_answers_what_it_heard(self, tmp_path, monkeypatch):
        assert self._spotted(tmp_path, monkeypatch, prompted=True) == ["on décale à jeudi ?"]

    def test_on_the_clock_it_waits_for_the_next_pass(self, tmp_path, monkeypatch):
        assert self._spotted(tmp_path, monkeypatch, prompted=False) == []


class TestABreathInTheMiddleOfAQuestion:
    """Measured on the bench: the levels called an end on a pause inside
    « Lucie, combien d'anomalies bloquantes restent à valider ? », the pass
    heard the question up to « restent », the model answered « RIEN », and the
    whole question was only answered by the slice, ten seconds later. The
    room going on talking while the pass transcribes says the end was not one.
    """

    def _her(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Deux."

        return AssistantSettings(name="Lucie", brain=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def _spotted(self, tmp_path, monkeypatch, resumed):
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        instance_holder = {}

        class Listening:
            def transcribe(self, audio, language, prompt_seed):
                # While the model reads the window, the room goes on.
                if resumed:
                    instance_holder["w"]._speech_end.note(8.4, speaking=True)
                return [Utterance(span=Span(0.0, 8.0),
                                  text="Lucie, combien d'anomalies restent ?")]

        her = self._her()
        spotted = []
        her.answer_aside = lambda opening, now: spotted.append(opening.remark)
        instance = watcher(tmp_path, transcriber=Listening(), assistant_of=her)
        instance_holder["w"] = instance
        instance._speech_end.note(7.4, speaking=True)
        assert instance._speech_end.note(8.0, speaking=False)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path, prompted=True)
        return spotted

    def test_a_room_that_went_on_talking_hands_nothing_over(self, tmp_path, monkeypatch):
        assert self._spotted(tmp_path, monkeypatch, resumed=True) == []

    def test_a_room_that_stayed_quiet_is_answered(self, tmp_path, monkeypatch):
        assert self._spotted(tmp_path, monkeypatch, resumed=False) == [
            "combien d'anomalies restent ?"
        ]


class TestHerNameIsInTheSeed:
    """Measured on the synthesised voices: « Lucie, où en est la recette ? »
    came back « Ici, où en est la recette » two times in ten; a sentence
    calling her by name in the seed brought the ten back whole."""

    def _lui(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Je regarde."

        return AssistantSettings(name="Lucie", brain=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def test_the_transcriber_is_told_she_is_in_the_room(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "extract_slice", lambda audio, start, end, dest: dest)
        seeds = []

        class Ecoute:
            def transcribe(self, audio, language, prompt_seed):
                seeds.append(prompt_seed)
                return []

        instance = watcher(tmp_path, transcriber=Ecoute(), assistant_of=self._lui(),
                           prompt_seed="Réunion de travail. Vocabulaire : Jira.")
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert seeds == [
            "Réunion de travail. Vocabulaire : Jira. Lucie, l'assistante, participe à la réunion."
        ]

    def test_the_slice_carries_it_too_and_her_name_comes_last(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "extract_slice", lambda audio, start, end, dest: dest)
        seeds = []

        class Ecoute:
            def transcribe(self, audio, language, prompt_seed):
                seeds.append(prompt_seed)
                return []

        instance = watcher(tmp_path, transcriber=Ecoute(), assistant_of=self._lui(),
                           prompt_seed="Réunion de travail.",
                           reread_the_seed=lambda: "Réunion de travail. Vocabulaire : CASA.")
        instance.transcription_turn(where_in(tmp_path, written=30.0), tmp_path)
        assert seeds[0].endswith("Lucie, l'assistante, participe à la réunion.")
        assert seeds[0].startswith("Réunion de travail. Vocabulaire : CASA.")

    def test_without_an_assistant_the_seed_is_the_context_s_alone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "extract_slice", lambda audio, start, end, dest: dest)
        seeds = []

        class Ecoute:
            def transcribe(self, audio, language, prompt_seed):
                seeds.append(prompt_seed)
                return []

        instance = watcher(tmp_path, transcriber=Ecoute(), prompt_seed="Réunion de travail.")
        instance.transcription_turn(where_in(tmp_path, written=30.0), tmp_path)
        assert seeds == ["Réunion de travail."]
