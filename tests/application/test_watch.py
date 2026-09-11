"""The watch during a meeting, with no mic and no clipboard."""

import json
import pathlib
from pathlib import Path

from greffier.application import watch
from greffier.application.follow import Follower, Position
from greffier.application.watch import Watcher
from greffier.domain.instructions import Kind, WatchRules
from greffier.domain.live import LiveThread
from greffier.domain.models import Span, Utterance


class SliceTranscriber:
    """Returns, for each slice, the utterances it was given in advance."""

    def __init__(self, tranches):
        self.tranches = list(tranches)
        self.appels = 0

    def transcribe(self, audio, language, prompt_seed):
        self.appels += 1
        return self.tranches.pop(0) if self.tranches else []


def utterance(start, text):
    return Utterance(span=Span(start, start + 4), text=text)


def watcher(tmp_path, **overrides):
    defauts = dict(watch_rules=WatchRules(), log=tmp_path / "propositions.jsonl")
    defauts.update(overrides)
    return Watcher(**defauts)


def where_in(tmp_path, written, offset=0.0):
    """The position in the audio actually written, as the live thread reads it."""
    return Position(morceau=tmp_path / "r-01.wav", written=written, offset=offset)


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
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        # The transcribed window starts CONTEXTE_S before the slice: an
        # utterance said 3 s into the slice is dated that much later in it.
        transcriber = SliceTranscriber(
            [[utterance(watch.CONTEXTE_S + 3, "Greffier, ouvre le tableau")]]
        )
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
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
        instance = watcher(tmp_path, transcriber=transcriber, traite=1800.0)
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
        assert transcriber.appels == 0

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
        demandees = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: demandees.append((start, end)) or None,
        )
        instance = watcher(tmp_path, transcriber=SliceTranscriber([]))
        instance.transcription_turn(where_in(tmp_path, written=600.0), tmp_path)
        start, end = demandees[0]
        assert end - start == watch.TRANCHE_MAXIMALE

    def test_an_unreadable_slice_does_not_stop_the_watch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "extract_slice", lambda *args: None)
        instance = watcher(tmp_path, transcriber=SliceTranscriber([]))
        assert instance.transcription_turn(where_in(tmp_path, written=30.0), tmp_path) == []

    def test_with_no_transcriber_only_the_clipboard_watch_runs(self, tmp_path):
        veille = watcher(tmp_path)
        assert veille.transcription_turn(where_in(tmp_path, written=30.0), tmp_path) == []


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
        fige = where_in(tmp_path, written=6.0)
        # First pass: whether the capture advances is not known yet.
        assert not instance._is_time(fige)
        # Second: the size has not moved, 6 s are left to say.
        assert instance._is_time(fige)

    def test_the_last_pass_catches_what_was_left(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[utterance(1, "Greffier, ouvre le ticket")]])
        instance = watcher(
            tmp_path, transcriber=transcriber, slice_period=30.0,
            situer=lambda: where_in(tmp_path, written=12.0),
        )
        # The meeting stops at once: nothing reached the period.
        propositions = instance.loop(
            still_running=lambda: False, since=lambda: 0.0, job=tmp_path,
            pause=lambda _: None,
        )
        assert transcriber.appels == 1
        assert propositions

    def test_too_short_a_remainder_triggers_nothing(self, tmp_path):
        instance = watcher(tmp_path, slice_period=30.0)
        fige = where_in(tmp_path, written=1.5)
        instance._is_time(fige)
        assert not instance._is_time(fige)


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
            situer=lambda: where_in(tmp_path, written=written["s"]),
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
        assert transcriber.appels == 3

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
            situer=lambda: where_in(tmp_path, written=4.0),
        )
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 40

        instance.loop(
            still_running=still_running, since=lambda: clock["t"], job=tmp_path,
            pause=lambda _: clock.__setitem__("t", clock["t"] + 2.0),
        )
        assert transcriber.appels == 1

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
        from greffier.application.follow import GENRE_REUNION, GENRE_TOUR, replay

        lines = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_TOUR, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            {"genre": GENRE_REUNION, "voix": "v2", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}
        assert "v2" not in thread.voice

    def test_a_name_given_by_hand_survives_the_replayed_join(self):
        from greffier.application.follow import GENRE_CORRECTION, GENRE_REUNION, GENRE_TOUR, replay

        lines = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_TOUR, "numero": 2, "debut": 2.0, "fin": 4.0,
             "texte": "salut", "voix": "v2", "nom": None,
             "certitude": "inconnue", "rang": 2},
            # "toute_la_voix" spelled out, as the log now writes it: deducing
            # it from the number of turns replayed a correction covering a
            # one-turn voice as "only this sentence".
            {"genre": GENRE_CORRECTION, "nom": "Sophie", "voix": "v2",
             "numeros": [2], "toute_la_voix": True},
            {"genre": GENRE_REUNION, "voix": "v2", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}
        assert thread.voice["v1"].name == "Sophie"

    def test_an_incomplete_join_line_is_ignored(self):
        """A truncated log must not bring the window down."""
        from greffier.application.follow import GENRE_REUNION, GENRE_TOUR, replay

        lines = [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 2.0,
             "texte": "bonjour", "voix": "v1", "nom": None,
             "certitude": "inconnue", "rang": 1},
            {"genre": GENRE_REUNION, "voix": "v1"},
            {"genre": GENRE_REUNION, "vers": "v1"},
            {"genre": GENRE_REUNION, "voix": "v1", "vers": "v1"},
        ]
        thread = replay(lines)
        assert {t.voice for t in thread.turns} == {"v1"}


class TestThePromptSeedRereadMidMeeting:
    """A term learnt during a meeting must serve the next sentence.

    The live process froze its seed at startup, so adding "OTP" during the meeting
    only served the meeting after, when a meeting is precisely where the missing
    words are discovered.
    """

    def watcher_with(self, prompt_seed: str, relire=None):
        return Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=pathlib.Path("/tmp/greffier-essai.jsonl"),
            transcriber=None,
            situer=lambda: None,
            prompt_seed=prompt_seed,
            relire_l_amorce=relire,
        )

    def test_without_rereading_the_seed_does_not_change(self):
        watcher = self.watcher_with("Vocabulaire : CASA.")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_a_fresh_seed_replaces_the_old_one(self):
        watcher = self.watcher_with(
            "Vocabulaire : CASA.", relire=lambda: "Vocabulaire : CASA, OTP."
        )
        assert "OTP" in watcher._current_prompt_seed()
        assert "OTP" in watcher.prompt_seed, "la nouvelle est retenue"

    def test_an_empty_reread_does_not_lose_the_seed(self):
        """A context momentarily unreadable must not degrade the slice."""
        watcher = self.watcher_with("Vocabulaire : CASA.", relire=lambda: "")
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."

    def test_a_reread_that_fails_does_not_raise(self):
        def tomber():
            raise OSError("fichier occupé")

        watcher = self.watcher_with("Vocabulaire : CASA.", relire=tomber)
        assert watcher._current_prompt_seed() == "Vocabulaire : CASA."


class TestTheWindowOfContext:
    """The model receives what came before, and shows none of it again.

    Measured on 2026-09-09 on a real meeting: the same passage gives "sur la ZIS"
    with a 15 s window, "sur Asis" with 30 s, "sur Oasis" with 60 s. The context
    makes the right word, but it must repeat nothing.
    """

    def test_the_model_gets_more_audio_than_the_slice(self, tmp_path, monkeypatch):
        demandees = []

        def extract(audio, start, end, dest):
            demandees.append((start, end))
            return dest

        monkeypatch.setattr(watch, "extract_slice", extract)
        transcriber = SliceTranscriber([[]])
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        slice_, window = demandees
        assert slice_ == (115.0, 150.0)
        assert window == (115.0 - watch.CONTEXTE_S, 150.0)

    def test_what_is_in_the_context_is_not_shown_again(self, tmp_path, monkeypatch):
        """Sinon chaque phrase s'afficherait six fois."""
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        transcriber = SliceTranscriber([[
            utterance(2, "phrase déjà affichée, dans le contexte"),
            utterance(watch.CONTEXTE_S + 1, "phrase neuve, dans la tranche"),
        ]])
        instance = watcher(tmp_path, transcriber=transcriber, traite=120.0)
        fresh = instance.transcription_turn(where_in(tmp_path, written=150.0), tmp_path)
        instance_veille = [p.text for p in fresh]
        assert not any("déjà affichée" in t for t in instance_veille)

    def test_at_the_start_the_window_does_not_reach_before_zero(
        self, tmp_path, monkeypatch
    ):
        demandees = []
        monkeypatch.setattr(
            watch, "extract_slice",
            lambda audio, start, end, dest: demandees.append(start) or dest,
        )
        transcriber = SliceTranscriber([[]])
        instance = watcher(tmp_path, transcriber=transcriber)
        instance.transcription_turn(where_in(tmp_path, written=12.0), tmp_path)
        assert all(start >= 0.0 for start in demandees)

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

    def _watcher(self, assistant_of, buttons, voix_neuve=None):
        from greffier.application.watch import Watcher
        from greffier.domain.instructions import WatchRules

        return Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=Path("/tmp/inutilise.jsonl"),
            assistant_of=assistant_of,
            reread_participation=lambda: buttons,
            give_voice_back=(lambda: voix_neuve) if voix_neuve else None,
        )

    def _assistant_of(self, avec_voix=True):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class FakeVoice:
            def __init__(self):
                self.tue = False

            def say(self, _t):
                return True

            def go_quiet(self):
                self.tue = True

            def is_speaking(self):
                return False

        return AssistantSettings(name="Lucie", voice=FakeVoice() if avec_voix else None,
                           manners=Manners(active=True))

    def test_cutting_the_voice_stops_it_at_once(self):
        """Pressing it while it speaks must cut, not wait for the end."""
        lui = self._assistant_of()
        voice = lui.voice
        self._watcher(lui, (False, False))._apply_the_buttons(False, False)
        assert voice.tue

    def test_taking_the_voice_away_leaves_it_writing(self):
        lui = self._assistant_of()
        self._watcher(lui, (False, False))._apply_the_buttons(False, False)
        assert lui.voice is None
        assert lui.manners.active, "il participe toujours, sans se faire entendre"

    def test_giving_the_voice_back_loads_it_once(self):
        """Loading a model costs: it is done only when asked for."""
        lui = self._assistant_of(avec_voix=False)
        neuve = object()
        watcher = self._watcher(lui, (True, False), voix_neuve=neuve)
        watcher._apply_the_buttons(True, False)
        assert lui.voice is neuve

    def test_with_no_way_to_give_it_back_it_stays_silent(self):
        """No model installed: it takes part in writing, without complaining."""
        lui = self._assistant_of(avec_voix=False)
        self._watcher(lui, (True, False))._apply_the_buttons(True, False)
        assert lui.voice is None and lui.manners.active

    def test_the_initiative_can_be_taken_mid_meeting(self):
        """The button only took effect at the next meeting, which nobody could guess."""
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, True))
        assert not watcher.initiative, "livrée éteinte"
        watcher._apply_the_buttons(True, True)
        assert watcher.initiative

    def test_the_initiative_can_be_taken_back_too(self):
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, False))
        watcher.initiative = True
        watcher._apply_the_buttons(True, False)
        assert not watcher.initiative

    def test_without_the_initiative_it_does_not_ask_who_is_speaking(self):
        """The rule that makes it bearable: a word only when it is called."""
        lui = self._assistant_of()
        watcher = self._watcher(lui, (True, False))
        watcher._apply_the_buttons(True, False)
        assert watcher._voices_to_ask_about(now=600.0) == []

    def test_nothing_changes_when_nothing_changes(self):
        lui = self._assistant_of()
        voice = lui.voice
        self._watcher(lui, (True, True))._apply_the_buttons(True, True)
        assert lui.manners.active and lui.voice is voice and not voice.tue


class TestOnceTheMeetingEnds:
    """Clicking "end the meeting" must end it, the assistant included.

    The last slice is still transcribed, so nothing said at the very end is
    lost, but it is transcribed silently: an answer coming out of the speakers
    in a room that has just been told the meeting is over would be the one
    thing everybody remembers of the demonstration.
    """

    class FakeVoice:
        def __init__(self):
            self.tue = False
            self.said = []

        def say(self, text):
            self.said.append(text)
            return True

        def go_quiet(self):
            self.tue = True

        def is_speaking(self):
            return False

    def _assistant(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        return AssistantSettings(
            name="Lucie", voice=self.FakeVoice(), manners=Manners(active=True),
        )

    def _watcher(self, tmp_path, monkeypatch, written, lui):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        return watcher(
            tmp_path,
            transcriber=SliceTranscriber([[utterance(0.0, "Lucie, tu en penses quoi ?")]]),
            situer=lambda: where_in(tmp_path, written=written),
            assistant_of=lui,
        )

    def test_the_last_slice_is_still_transcribed(self, tmp_path, monkeypatch):
        lui = self._assistant()
        instance = self._watcher(tmp_path, monkeypatch, 20.0, lui)
        instance.last_pass(tmp_path)
        assert instance.traite == 20.0, "the closing audio is read"

    def test_she_does_not_answer_on_the_last_slice(self, tmp_path, monkeypatch):
        """Called by name in the last seconds: transcribed, not answered."""
        lui = self._assistant()
        appels = []
        lui.answer_aside = lambda opening, now: appels.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, 20.0, lui)
        instance.last_pass(tmp_path)
        assert appels == []

    def test_she_answers_on_an_ordinary_slice(self, tmp_path, monkeypatch):
        """The counter-proof: the same slice mid-meeting does reach her."""
        lui = self._assistant()
        appels = []
        lui.answer_aside = lambda opening, now: appels.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, 20.0, lui)
        instance.transcription_turn(where_in(tmp_path, written=20.0), tmp_path)
        assert len(appels) == 1

    def test_the_voice_is_cut_when_the_loop_ends(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        lui = self._assistant()
        voice = lui.voice
        watcher(tmp_path, assistant_of=lui).loop(
            still_running=lambda: False, since=lambda: 0.0, job=tmp_path,
            pause=lambda _: None,
        )
        assert voice.tue, "a sentence under way stops with the meeting"
        assert lui.stopped

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

    class Ecoute:
        """A transcriber that returns what was said, and counts its calls."""

        def __init__(self, texte="Lucie, tu en penses quoi ?"):
            self.texte = texte
            self.appels = 0

        def transcribe(self, audio, language, prompt_seed):
            self.appels += 1
            return [Utterance(span=Span(0.0, 3.0), text=self.texte)]

    def _lui(self):
        from greffier.application.take_part import AssistantSettings
        from greffier.domain.participation import Manners

        class Brain:
            def write_up(self, text):
                return "Je regarde."

        return AssistantSettings(name="Lucie", cerveau=Brain(),
                                 manners=Manners(active=True, creux_minimal=0.0))

    def _watcher(self, tmp_path, monkeypatch, lui, ecoute):
        monkeypatch.setattr(watch, "read_the_clipboard", lambda: "")
        monkeypatch.setattr(watch, "extract_slice",
                            lambda audio, start, end, dest: dest)
        return watcher(tmp_path, transcriber=ecoute, assistant_of=lui,
                       situer=lambda: where_in(tmp_path, written=8.0))

    def test_a_call_is_answered_before_the_slice(self, tmp_path, monkeypatch):
        lui, ecoute = self._lui(), self.Ecoute()
        dits = []
        lui.answer_aside = lambda opening, now: dits.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert len(dits) == 1
        assert ecoute.appels == 1

    def test_an_ordinary_sentence_costs_nothing_but_the_listening(
        self, tmp_path, monkeypatch
    ):
        """The model is not called for a sentence that does not name it."""
        lui = self._lui()
        ecoute = self.Ecoute("on se cale jeudi pour la recette")
        dits = []
        lui.answer_aside = lambda opening, now: dits.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert dits == []

    def test_the_same_call_is_not_answered_twice(self, tmp_path, monkeypatch):
        """The listening pass answers; the full slice must then keep quiet."""
        lui, ecoute = self._lui(), self.Ecoute()
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        if lui._job is not None:
            lui._job.join(timeout=5)
        dits = []
        lui.answer_aside = lambda opening, now: dits.append(opening)
        instance.assistant_turn(
            [utterance(0.0, "Lucie, tu en penses quoi ?")], 8.0
        )
        assert dits == [], "la tranche complète ne doit pas répéter la réponse"

    def test_it_does_not_listen_while_it_is_speaking(self, tmp_path, monkeypatch):
        lui, ecoute = self._lui(), self.Ecoute()
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)

        class Occupe:
            def is_alive(self):
                return True

        lui._job = Occupe()
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert ecoute.appels == 0

    def test_it_listens_at_its_own_pace(self, tmp_path, monkeypatch):
        """Every clipboard turn would cost 0.8 s of transcription every 2 s."""
        lui, ecoute = self._lui(), self.Ecoute()
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        instance.listening_turn(where_in(tmp_path, written=9.0), tmp_path)
        assert ecoute.appels == 1, "une seconde plus tard, on n'écoute pas encore"
        instance.listening_turn(where_in(tmp_path, written=12.0), tmp_path)
        assert ecoute.appels == 2

    def test_with_no_assistant_nothing_is_transcribed(self, tmp_path, monkeypatch):
        ecoute = self.Ecoute()
        instance = self._watcher(tmp_path, monkeypatch, None, ecoute)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert ecoute.appels == 0

    def test_an_assistant_switched_off_is_not_listened_for(
        self, tmp_path, monkeypatch
    ):
        from greffier.domain.participation import Manners

        lui, ecoute = self._lui(), self.Ecoute()
        lui.manners = Manners(active=False)
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)
        instance.listening_turn(where_in(tmp_path, written=8.0), tmp_path)
        assert ecoute.appels == 0

    def test_too_little_audio_is_not_read(self, tmp_path, monkeypatch):
        lui, ecoute = self._lui(), self.Ecoute()
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)
        instance.listening_turn(where_in(tmp_path, written=1.0), tmp_path)
        assert ecoute.appels == 0

    def test_the_loop_listens_between_two_slices(self, tmp_path, monkeypatch):
        """The whole point: it happens on the clipboard rhythm, not the slice."""
        lui, ecoute = self._lui(), self.Ecoute()
        dits = []
        lui.answer_aside = lambda opening, now: dits.append(opening)
        instance = self._watcher(tmp_path, monkeypatch, lui, ecoute)
        instance.slice_period = 30.0
        turns = {"n": 0}

        def still_running():
            turns["n"] += 1
            return turns["n"] <= 3

        instance.loop(still_running=still_running, since=lambda: 8.0, job=tmp_path,
                      pause=lambda _: None)
        assert dits, "elle a répondu sans attendre la tranche de trente secondes"
