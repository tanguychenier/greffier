"""The thread published during the meeting, and the corrections that come back.

Two processes talk to each other through files: the one that listens publishes
what is said, the window drops its corrections in. All of it is covered here
with no audio, no model and no screen; only the doubles change.
"""

from __future__ import annotations

import json
from pathlib import Path

from greffier.application.follow import (
    KIND_CORRECTION,
    KIND_SPLIT,
    KIND_TURN,
    Follower,
    add,
    ask,
    files,
    position,
    read_from,
    replay,
    request_a_split,
)
from greffier.domain.channels import LOCAL_VOICE
from greffier.domain.live import LOCAL_NAME, Certainty, LiveThread
from greffier.domain.models import Person, Span, SpeakerTurn, Utterance, Voiceprint
from greffier.domain.voiceprints import normalise


def voiceprint(x: float, y: float, duration: float = 8.0) -> Voiceprint:
    return normalise([x, y, 0.0], source_duration=duration)


def utterance(start: float, end: float, text: str = "on cale la recette jeudi") -> Utterance:
    return Utterance(span=Span(start, end), text=text)


class StatedChannels:
    """Says in advance which passages come from the mic."""

    def __init__(self, local_spans: list[Span] | None = None) -> None:
        self.local_spans = local_spans or []

    def local_passages(self, audio: Path) -> list[Span]:
        return self.local_spans


class SequenceExtractor:
    """Returns the voiceprints prepared, and keeps what it was asked for."""

    def __init__(self, voiceprints: list[Voiceprint] | None = None) -> None:
        self.voiceprints = list(voiceprints or [])
        self.requests: list[list[Span]] = []

    def extract_spans(
        self, audio: Path, the_spans: list[Span]
    ) -> list[Voiceprint]:
        self.requests.append(the_spans)
        return [self.voiceprints.pop(0)] if self.voiceprints else []


class StatedSegmenter:
    """Says in advance where the speakers of the slice change."""

    def __init__(self, turns: list[SpeakerTurn] | None = None) -> None:
        self.turns_ = turns or []
        self.asked: list[Path] = []

    def turns(self, audio: Path) -> list[SpeakerTurn]:
        self.asked.append(audio)
        return self.turns_


class TogetherExtractor(SequenceExtractor):
    """Also reads several passages as one, and keeps what it was asked."""

    def __init__(self, voiceprints: list[Voiceprint] | None = None) -> None:
        super().__init__(voiceprints)
        self.together: list[list[Span]] = []

    def extract_together(self, audio: Path, the_spans: list[Span]) -> Voiceprint | None:
        self.together.append(the_spans)
        return self.voiceprints.pop(0) if self.voiceprints else None


class InMemoryBank:
    def __init__(self, known: list[Person] | None = None) -> None:
        self.known = list(known or [])
        self.received_ones: list[tuple[str, Voiceprint]] = []

    def people(self) -> list[Person]:
        return self.known

    def record(self, name: str, e: Voiceprint) -> Person:
        self.received_ones.append((name, e))
        person = Person(name=name, voiceprints=[e])
        self.known.append(person)
        return person


def follower(tmp_path: Path, **overrides: object) -> Follower:
    log, requests = files(tmp_path, "2026-08-27_10h00_reunion")
    defects: dict[str, object] = dict(
        thread=LiveThread(), log=log, requests=requests, channels=StatedChannels()
    )
    defects.update(overrides)
    return Follower(**defects)  # type: ignore[arg-type]


def lines_of(log: Path) -> list[dict[str, object]]:
    read_ones, _ = read_from(log)
    return read_ones


class TestWhereWeAreInTheAudio:
    def test_the_last_piece_is_the_one_being_followed(self, tmp_path: Path) -> None:
        chunks = [tmp_path / "a.wav", tmp_path / "b.wav"]
        where_in = position(chunks, lambda m: 600.0 if m.name == "a.wav" else 30.0)
        assert where_in is not None
        assert where_in.chunk.name == "b.wav"
        assert where_in.written == 30.0

    def test_the_earlier_pieces_give_the_time_in_the_meeting(
        self, tmp_path: Path
    ) -> None:
        # A pause cuts the recording into two files. Without the running total,
        # what follows would show up at the start of the meeting.
        chunks = [tmp_path / "a.wav", tmp_path / "b.wav"]
        where_in = position(chunks, lambda m: 600.0 if m.name == "a.wav" else 30.0)
        assert where_in is not None
        assert where_in.offset == 600.0
        assert where_in.overall == 630.0

    def test_a_piece_not_yet_written_is_ignored(self, tmp_path: Path) -> None:
        chunks = [tmp_path / "a.wav", tmp_path / "b.wav"]
        where_in = position(chunks, lambda m: 12.0 if m.name == "a.wav" else None)
        assert where_in is not None and where_in.chunk.name == "a.wav"

    def test_with_no_audio_there_is_no_position(self, tmp_path: Path) -> None:
        assert position([tmp_path / "a.wav"], lambda _m: None) is None
        assert position([], lambda _m: 10.0) is None


class TestReadingOnlyWhatIsNew:
    def test_only_what_was_appended_is_read_again(self, tmp_path: Path) -> None:
        # The window rereads four times a second: rereading an hour of meeting
        # every turn would cost for nothing.
        log = tmp_path / "fil.jsonl"
        add(log, [{"genre": KIND_TURN, "numero": 1}])
        premieres, where_in = read_from(log)
        assert len(premieres) == 1
        add(log, [{"genre": KIND_TURN, "numero": 2}])
        following_ones, _ = read_from(log, where_in)
        assert [x["numero"] for x in following_ones] == [2]

    def test_a_half_written_line_waits_for_the_next_time(self, tmp_path: Path) -> None:
        log = tmp_path / "fil.jsonl"
        whole_one = '{"genre": "tour", "numero": 1}\n'
        log.write_text(whole_one + '{"genre": "tou', encoding="utf-8")
        read_ones, where_in = read_from(log)
        assert [x["numero"] for x in read_ones] == [1]
        # The position stops at the last complete line: the rest is read once
        # it is whole.
        assert where_in == len(whole_one)

    def test_a_missing_log_makes_no_fuss(self, tmp_path: Path) -> None:
        assert read_from(tmp_path / "rien.jsonl") == ([], 0)


class TestPublishingWhatWasSaid:
    def test_every_sentence_becomes_a_line(self, tmp_path: Path) -> None:
        instance = follower(tmp_path)
        instance.take_in(
            tmp_path / "tranche.wav", [utterance(0, 4), utterance(4, 8)], offset=0.0
        )
        lines = lines_of(instance.log)
        assert [x["genre"] for x in lines] == [KIND_TURN, KIND_TURN]
        assert [x["numero"] for x in lines] == [1, 2]

    def test_the_mic_shows_you_without_asking_a_model(self, tmp_path: Path) -> None:
        extractor = SequenceExtractor()
        instance = follower(
            tmp_path,
            channels=StatedChannels([Span(0, 4)]),
            extractor=extractor,
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 4)], offset=0.0)
        assert instance.thread.turns[0].voice == LOCAL_VOICE
        assert instance.thread.label(LOCAL_VOICE) == LOCAL_NAME
        # No voiceprint taken: spending computation to confirm what the wiring
        # already establishes brings nothing.
        assert extractor.requests == []

    def test_the_voiceprint_is_taken_at_the_times_of_the_slice(self, tmp_path: Path) -> None:
        # The display runs on the meeting clock, the cut audio does not: taking
        # a print at 1802 s inside a 10 s slice would give nothing.
        extractor = SequenceExtractor([voiceprint(1, 0)])
        instance = follower(tmp_path, extractor=extractor)
        instance.take_in(tmp_path / "tranche.wav", [utterance(2, 9)], offset=1800.0)
        assert extractor.requests[0][0].start == 2.0
        assert instance.thread.turns[0].span.start == 1802.0

    def test_the_voiceprint_avoids_what_the_mic_captured(self, tmp_path: Path) -> None:
        # The transcription cuts at sentences, not at speaker changes: a remote
        # passage may carry the end of a local sentence. Taking the print over
        # the whole mixed two voices, and made one person two participants.
        extractor = SequenceExtractor([voiceprint(1, 0)])
        instance = follower(
            tmp_path,
            channels=StatedChannels([Span(9.5, 13.8)]),
            extractor=extractor,
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(13.2, 14.7)], offset=0.0)
        assert extractor.requests[0] == [Span(13.8, 14.7)]

    def test_a_sentence_already_shown_does_not_come_back(self, tmp_path: Path) -> None:
        # The slices overlap by 5 s so that a sentence astride stays whole in
        # one of the two.
        instance = follower(tmp_path)
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 8)], offset=0.0)
        instance.take_in(
            tmp_path / "t2.wav", [utterance(0, 8), utterance(8, 12)], offset=0.0
        )
        assert [t.number for t in instance.thread.turns] == [1, 2]
        assert instance.thread.turns[1].span.start == 8.0

    def test_a_voice_from_the_bank_is_named_on_the_first_sentence(
        self, tmp_path: Path
    ) -> None:
        marc = Person(name="Marc", voiceprints=[voiceprint(1, 0, duration=30)])
        instance = follower(
            tmp_path,
            thread=LiveThread(known=[marc]),
            extractor=SequenceExtractor([voiceprint(1, 0)]),
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], offset=0.0)
        assert lines_of(instance.log)[0]["nom"] == "Marc"

    def test_a_model_that_falls_over_does_not_stop_the_meeting(self, tmp_path: Path) -> None:
        class Broken:
            def extract_spans(self, audio: Path, the_spans: list[Span]):
                raise RuntimeError("BroadcastIterator::Init")

        instance = follower(tmp_path, extractor=Broken())
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], offset=0.0)
        # The sentence shows without a name, and is corrected in one click.
        assert len(instance.thread.turns) == 1


class TestASliceCutAtTheChangesOfSpeaker:
    """Two people in one slice used to come out as one voice, the one whose
    print dominated the ten seconds. With the turns of the slice, each gets
    a print of their own, read where they talk."""

    def test_each_speaker_of_the_slice_gets_a_voice(self, tmp_path: Path) -> None:
        extractor = TogetherExtractor([voiceprint(1, 0), voiceprint(0, 1)])
        instance = follower(
            tmp_path,
            extractor=extractor,
            segmenter=StatedSegmenter([
                SpeakerTurn(Span(0, 5), "0:0"), SpeakerTurn(Span(5, 10), "0:1"),
            ]),
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 5), utterance(5, 10)], offset=0.0)
        voices = [t.voice for t in instance.thread.turns]
        assert len(set(voices)) == 2
        assert extractor.together == [[Span(0, 5)], [Span(5, 10)]]

    def test_the_turns_are_read_on_the_slice_and_kept_on_the_meeting_clock(
        self, tmp_path: Path
    ) -> None:
        # The segmenter sees a file that starts at zero; the thread shows the
        # meeting's own clock. One offset, applied once.
        extractor = TogetherExtractor([voiceprint(1, 0)])
        segmenter = StatedSegmenter([SpeakerTurn(Span(2, 9), "0:0")])
        instance = follower(tmp_path, extractor=extractor, segmenter=segmenter)
        instance.take_in(tmp_path / "tranche.wav", [utterance(2, 9)], offset=1800.0)
        assert segmenter.asked == [tmp_path / "tranche.wav"]
        assert extractor.together == [[Span(2, 9)]]
        assert instance.thread.turns[0].span.start == 1802.0

    def test_the_print_leaves_out_what_the_mic_captured(self, tmp_path: Path) -> None:
        extractor = TogetherExtractor([voiceprint(1, 0)])
        instance = follower(
            tmp_path,
            channels=StatedChannels([Span(0, 2)]),
            extractor=extractor,
            segmenter=StatedSegmenter([SpeakerTurn(Span(0, 10), "0:0")]),
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(1.9, 10)], offset=0.0)
        assert extractor.together == [[Span(2, 10)]]

    def test_a_segmenter_that_falls_over_leaves_the_slice_whole(self, tmp_path: Path) -> None:
        class Broken:
            def turns(self, audio: Path) -> list[SpeakerTurn]:
                raise RuntimeError("onnxruntime")

        extractor = TogetherExtractor([voiceprint(1, 0)])
        instance = follower(tmp_path, extractor=extractor, segmenter=Broken())
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 5), utterance(5, 10)], offset=0.0)
        assert len({t.voice for t in instance.thread.turns}) == 1
        assert extractor.requests == [[Span(0, 10)]]

    def test_without_a_segmenter_nothing_changes(self, tmp_path: Path) -> None:
        extractor = TogetherExtractor([voiceprint(1, 0)])
        instance = follower(tmp_path, extractor=extractor)
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 5), utterance(5, 10)], offset=0.0)
        assert extractor.together == [] and extractor.requests == [[Span(0, 10)]]


class TestCorrectionsComingIn:
    def _a_thread(self, tmp_path: Path) -> Follower:
        instance = follower(
            tmp_path,
            extractor=SequenceExtractor([voiceprint(1, 0)]),
            bank=InMemoryBank(),
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], offset=0.0)
        return instance

    def test_a_correction_dropped_in_is_applied(self, tmp_path: Path) -> None:
        instance = self._a_thread(tmp_path)
        ask(instance.requests, number=1, name="Marc")
        done_ones = instance.apply_requests()
        assert [c.name for c in done_ones] == ["Marc"]
        assert instance.thread.label(instance.thread.turns[0].voice) == "Marc"

    def test_the_correction_is_confirmed_in_the_log(self, tmp_path: Path) -> None:
        # That is how the window knows its correction was taken, and how
        # any other open window learns it too.
        instance = self._a_thread(tmp_path)
        ask(instance.requests, number=1, name="Marc")
        instance.apply_requests()
        confirmations = [
            x for x in lines_of(instance.log) if x["genre"] == KIND_CORRECTION
        ]
        assert confirmations[0]["nom"] == "Marc"
        assert confirmations[0]["numeros"] == [1]

    def test_a_correction_pours_the_voiceprint_into_the_bank(self, tmp_path: Path) -> None:
        # The point of the whole exchange: correct once during the meeting, and
        # let the final minutes find the person on their own.
        bank = InMemoryBank()
        instance = follower(
            tmp_path,
            extractor=SequenceExtractor([voiceprint(1, 0)]),
            bank=bank,
        )
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], offset=0.0)
        ask(instance.requests, number=1, name="Marc")
        instance.apply_requests()
        assert [name for name, _ in bank.received_ones] == ["Marc"]

    def test_your_own_voice_never_enters_the_bank(self, tmp_path: Path) -> None:
        # The mic already identifies whoever is recording: storing their voice
        # as a participant's would bring nothing and expose it.
        bank = InMemoryBank()
        instance = follower(tmp_path, channels=StatedChannels([Span(0, 8)]), bank=bank)
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], offset=0.0)
        ask(instance.requests, number=1, name="Tanguy")
        instance.apply_requests()
        assert bank.received_ones == []

    def test_a_voice_corrected_too_early_is_learnt_once_it_has_enough(
        self, tmp_path: Path
    ) -> None:
        """The defect that emptied the voice bank.

        One corrects on the first sentence, which is the point, when the voiceprint
        has not yet gathered the material the threshold asks for. Refusing once and
        for all lost the correction: it showed on screen, then served neither the next
        meeting nor the minutes.
        """
        bank = InMemoryBank()
        instance = follower(
            tmp_path,
            extractor=SequenceExtractor(
                # 2.5 s: enough to found a voice, the measured floor being
                # 2.0 s, but not enough to pour it into the bank.
                [voiceprint(1, 0, duration=2.5), voiceprint(0.95, 0.31, duration=4.0)]
            ),
            bank=bank,
        )
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 2)], offset=0.0)
        ask(instance.requests, number=1, name="Sandy")
        instance.apply_requests()
        # Too little material to learn anything useful.
        assert bank.received_ones == []
        # The person speaks again: this time there is enough.
        instance.take_in(tmp_path / "t2.wav", [utterance(3, 9)], offset=0.0)
        assert [name for name, _ in bank.received_ones] == ["Sandy"]

    def test_a_voice_is_learnt_only_once(self, tmp_path: Path) -> None:
        bank = InMemoryBank()
        instance = follower(
            tmp_path,
            extractor=SequenceExtractor([voiceprint(1, 0), voiceprint(0.95, 0.31)]),
            bank=bank,
        )
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 8)], offset=0.0)
        ask(instance.requests, number=1, name="Sandy")
        instance.apply_requests()
        instance.take_in(tmp_path / "t2.wav", [utterance(9, 17)], offset=0.0)
        assert [name for name, _ in bank.received_ones] == ["Sandy"]

    def test_a_request_matching_nothing_is_ignored(self, tmp_path: Path) -> None:
        instance = self._a_thread(tmp_path)
        ask(instance.requests, number=99, name="Marc")
        ask(instance.requests, number=1, name="  ")
        assert instance.apply_requests() == []

    def test_a_request_is_applied_only_once(self, tmp_path: Path) -> None:
        instance = self._a_thread(tmp_path)
        ask(instance.requests, number=1, name="Marc")
        assert len(instance.apply_requests()) == 1
        assert instance.apply_requests() == []

    def test_the_sentences_that_follow_carry_the_corrected_name(self, tmp_path: Path) -> None:
        instance = follower(
            tmp_path,
            extractor=SequenceExtractor([voiceprint(1, 0), voiceprint(0.9, 0.44)]),
            bank=InMemoryBank(),
        )
        instance.take_in(tmp_path / "t1.wav", [utterance(0, 8)], offset=0.0)
        ask(instance.requests, number=1, name="Marc")
        instance.take_in(tmp_path / "t2.wav", [utterance(9, 17)], offset=0.0)
        assert lines_of(instance.log)[-1]["nom"] == "Marc"


class TestReplayingInOrderToShow:
    def test_the_thread_rebuilds_from_the_log(self, tmp_path: Path) -> None:
        instance = follower(tmp_path, extractor=SequenceExtractor([voiceprint(1, 0)]))
        instance.take_in(
            tmp_path / "t.wav", [utterance(0, 4, "bonjour"), utterance(4, 8)], offset=0.0
        )
        replayed = replay(lines_of(instance.log))
        assert [t.text for t in replayed.turns] == ["bonjour", "on cale la recette jeudi"]
        assert replayed.label(replayed.turns[0].voice) == "Voix 1"

    def test_a_correction_in_the_log_renames_the_past_sentences(
        self, tmp_path: Path
    ) -> None:
        instance = follower(
            tmp_path,
            extractor=SequenceExtractor([voiceprint(1, 0)]),
            bank=InMemoryBank(),
        )
        instance.take_in(tmp_path / "t.wav", [utterance(0, 8)], offset=0.0)
        ask(instance.requests, number=1, name="Marc")
        instance.apply_requests()
        replayed = replay(lines_of(instance.log))
        assert replayed.label(replayed.turns[0].voice) == "Marc"
        assert replayed.voice[replayed.turns[0].voice].certainty is Certainty.HUMAN

    def test_replaying_twice_does_not_duplicate_the_sentences(self, tmp_path: Path) -> None:
        # The window reads in pieces: an overlap must not show the same
        # sentence twice.
        instance = follower(tmp_path)
        instance.take_in(tmp_path / "t.wav", [utterance(0, 8)], offset=0.0)
        lines = lines_of(instance.log)
        thread = replay(lines)
        replay(lines, thread)
        assert len(thread.turns) == 1

    def test_a_damaged_line_does_not_stop_the_others_being_read(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "fil.jsonl"
        log.write_text(
            "ceci n'est pas du json\n"
            + json.dumps({"genre": KIND_TURN, "numero": 1, "debut": 0, "fin": 2,
                          "texte": "bonjour", "voix": "v1", "nom": None,
                          "certitude": "inconnue", "rang": 1})
            + "\n",
            encoding="utf-8",
        )
        assert len(replay(lines_of(log)).turns) == 1


class TestTwoFiles:
    def test_each_one_writes_into_its_own(self, tmp_path: Path) -> None:
        # No lock to take: the listener writes the log and reads the requests,
        # the window does the opposite.
        log, requests = files(tmp_path, "2026-08-27_10h00_reunion")
        assert log != requests
        assert log.parent == requests.parent


class TestSplittingAcrossTheTwoProcesses:
    """A split crosses both processes, the way a correction does.

    The window shows it at once, but the listening process holds the voiceprints:
    it alone can give them back to each voice, and what enters the voice bank
    depends on that.
    """

    def _two_joined_voices(self, tmp_path: Path) -> Follower:
        instance = follower(
            tmp_path,
            extractor=SequenceExtractor([voiceprint(1, 0), voiceprint(0, 1)]),
            bank=InMemoryBank(),
        )
        instance.take_in(
            tmp_path / "un.wav", [utterance(0, 8, "on cale la recette jeudi")],
            offset=0.0,
        )
        instance.take_in(
            tmp_path / "deux.wav", [utterance(9, 17, "le devis part demain matin")],
            offset=0.0,
        )
        assert len({t.voice for t in instance.thread.turns}) == 2, "deux voix distinctes"
        ask(instance.requests, number=1, name="Tanguy")
        ask(instance.requests, number=2, name="Tanguy")
        instance.apply_requests()
        assert len({t.voice for t in instance.thread.turns}) == 1, "réunies"
        return instance

    def test_a_split_dropped_in_is_applied(self, tmp_path: Path) -> None:
        instance = self._two_joined_voices(tmp_path)
        kept_one = instance.thread.turns[0].voice
        request_a_split(instance.requests, kept_one)
        instance.apply_requests()
        assert len({t.voice for t in instance.thread.turns}) == 2

    def test_the_split_is_confirmed_in_the_log(self, tmp_path: Path) -> None:
        # This is how any other open window, and a thread picked up after a
        # crash, learn that these two voices are not the same.
        instance = self._two_joined_voices(tmp_path)
        kept_one = instance.thread.turns[0].voice
        request_a_split(instance.requests, kept_one)
        instance.apply_requests()
        said_ones = [
            x for x in lines_of(instance.log) if x["genre"] == KIND_SPLIT
        ]
        assert len(said_ones) == 1
        assert said_ones[0]["de"] == kept_one
        assert said_ones[0]["numeros"] == [2]

    def test_a_replayed_thread_keeps_the_voices_apart(self, tmp_path: Path) -> None:
        """The point of it all: picking a thread up again does not remake the join."""
        instance = self._two_joined_voices(tmp_path)
        kept_one = instance.thread.turns[0].voice
        request_a_split(instance.requests, kept_one)
        instance.apply_requests()
        resumed = replay(lines_of(instance.log))
        assert len({t.voice for t in resumed.turns}) == 2
        assert resumed.split_apart, "la paire doit rester tenue à part"

    def test_every_voiceprint_goes_back_to_its_voice(self, tmp_path: Path) -> None:
        instance = self._two_joined_voices(tmp_path)
        kept_one = instance.thread.turns[0].voice
        request_a_split(instance.requests, kept_one)
        instance.apply_requests()
        accounts = {
            i: len(v.voiceprints)
            for i, v in instance.thread.voice.items()
            if v.voiceprints
        }
        assert sorted(accounts.values()) == [1, 1], accounts

    def test_splitting_what_absorbed_nothing_says_nothing(self, tmp_path: Path) -> None:
        instance = self._two_joined_voices(tmp_path)
        request_a_split(instance.requests, "voix-jamais-vue")
        instance.apply_requests()
        assert not [
            x for x in lines_of(instance.log) if x["genre"] == KIND_SPLIT
        ]


class TestHowFarAReplayedCorrectionReaches:
    """How far a correction reaches travels in the log; it is not deduced.

    The defect: the line carried only the turn numbers, and the replay inferred
    the reach from them. A "whole voice" correction made while the voice held a
    single turn therefore replayed as "only this sentence", and on picking the
    thread up again the later turns of that voice lost the name. Met for real: a
    thread of six hundred and forty-six turns picked up in the fiftieth minute.
    """

    def _log(self, tmp_path: Path, whole_voice: bool | None = None) -> Path:
        log, _ = files(tmp_path, "2026-09-10_10h10_reunion")
        correction: dict[str, object] = {
            "genre": KIND_CORRECTION, "nom": "Marc", "voix": "v1", "numeros": [1],
        }
        if whole_voice is not None:
            correction["toute_la_voix"] = whole_voice
        add(log, [
            {"genre": KIND_TURN, "numero": 1, "debut": 0.0, "fin": 8.0,
             "texte": "on cale la recette jeudi", "voix": "v1",
             "nom": None, "certitude": Certainty.UNKNOWN.value, "rang": 1},
            correction,
            {"genre": KIND_TURN, "numero": 2, "debut": 9.0, "fin": 17.0,
             "texte": "le devis part demain matin", "voix": "v1",
             "nom": None, "certitude": Certainty.UNKNOWN.value, "rang": 1},
        ])
        return log

    def test_the_whole_voice_covers_the_turns_that_come_after(
        self, tmp_path: Path
    ) -> None:
        resumed = replay(lines_of(self._log(tmp_path, True)))
        names = {resumed.label(t.voice) for t in resumed.turns}
        assert names == {"Marc"}, names

    def test_only_this_sentence_covers_only_the_sentence(
        self, tmp_path: Path
    ) -> None:
        resumed = replay(lines_of(self._log(tmp_path, False)))
        by_number = {t.number: resumed.label(t.voice) for t in resumed.turns}
        assert by_number[1] == "Marc"
        assert by_number[2] != "Marc"

    def test_a_log_from_before_stays_readable(self, tmp_path: Path) -> None:
        """Without the field: it falls back on the old deduction, for want of better."""
        resumed = replay(lines_of(self._log(tmp_path)))
        assert resumed.turns, "le journal doit rester relisible"


class TestIdentifiersAreNeverReused:
    """A thread picked up again must never hand out an identifier already taken.

    The defect, and it was silent: replaying the log wrote the voices "v1", "v2"…
    in directly, without advancing the counter. The next voice the thread founded
    was therefore called "v1" again and **overwrote** the existing entry: the
    turns of two people ended up under one identifier with nothing to say so.
    Every thread picked up again was affected, and one of them held six hundred
    and forty-six turns.
    """

    def _log_of_two_voices(self, tmp_path: Path) -> Path:
        log, _ = files(tmp_path, "2026-09-10_10h10_reunion")
        add(log, [
            {"genre": KIND_TURN, "numero": number, "debut": float(number * 10),
             "fin": float(number * 10 + 8), "texte": f"phrase {number}",
             "voix": f"v{number}", "nom": None,
             "certitude": Certainty.UNKNOWN.value, "rang": number}
            for number in (1, 2, 3)
        ])
        return log

    def test_the_counter_starts_after_the_last_voice_in_the_log(
        self, tmp_path: Path
    ) -> None:
        resumed = replay(lines_of(self._log_of_two_voices(tmp_path)))
        assert resumed._identifier() == "v4"

    def test_correcting_a_sentence_overwrites_no_voice(
        self, tmp_path: Path
    ) -> None:
        """The visible symptom: three voices replayed, one correction, still three
        distinct people, and not two turns under the same name.
        """
        resumed = replay(lines_of(self._log_of_two_voices(tmp_path)))
        earlier = {t.number: t.voice for t in resumed.turns}
        resumed.correct(2, "Marc", whole_voice=False)
        later = {t.number: t.voice for t in resumed.turns}
        assert later[1] == earlier[1], "la phrase 1 a changé de voix"
        assert later[3] == earlier[3], "la phrase 3 a changé de voix"
        assert len(set(later.values())) == 3, later


class TestARebuiltThreadShowsWhatTheListenerShows:
    """The window rebuilds the thread from the log; the listening process holds
    the live one. They must agree.

    Measured on a real ninety-minute meeting: three people out of nine were
    still shown twice at the end, because a correction made in the window names
    a voice like another one and the join that follows belongs to the listener.
    Replaying without joining namesakes showed both.
    """

    def _lines(self, *voice: tuple[int, str, str, int]):
        return [
            {"genre": "tour", "numero": n, "debut": float(n), "fin": float(n) + 2.0,
             "texte": "on cale la recette", "voix": v, "nom": name,
             "certitude": "humaine" if name else "inconnue", "rang": rang}
            for n, v, name, rang in voice
        ]

    def test_two_voices_of_one_name_become_one(self):
        from greffier.application.follow import replay

        thread = replay(self._lines(
            (1, "v1", "Bastien", 1), (2, "v2", "Bastien", 2), (3, "v3", "Lise", 3),
        ))
        the_names = sorted(v.name for v in thread.voice.values() if v.name)
        assert the_names == ["Bastien", "Lise", "Toi"]

    def test_the_turns_of_both_are_kept(self):
        from greffier.application.follow import replay

        thread = replay(self._lines(
            (1, "v1", "Bastien", 1), (2, "v2", "Bastien", 2),
        ))
        assert len(thread.turns) == 2
        assert len({t.voice for t in thread.turns}) == 1, "les deux tours vont à une voix"

    def test_a_number_the_log_shows_is_never_handed_out_again(self):
        from greffier.application.follow import replay

        thread = replay(self._lines((1, "v1", "", 11)))
        assert thread.last_rank >= 11

    def test_voices_of_different_names_stay_apart(self):
        from greffier.application.follow import replay

        thread = replay(self._lines(
            (1, "v1", "Bastien", 1), (2, "v2", "Lise", 2),
        ))
        assert len([v for v in thread.voice.values() if v.name]) == 3


class TestTheDoubtTravelsWithTheTurn:
    """Said the next day in the transcript, the doubt came too late: the
    live thread now carries the engine's figure, log and replay included."""

    def test_the_figure_is_logged_and_read_back(self, tmp_path: Path) -> None:
        instance = follower(tmp_path, extractor=SequenceExtractor([voiceprint(1, 0)]))
        heard = Utterance(span=Span(0, 8), text="on cale la recette jeudi", confidence=0.4)
        instance.take_in(tmp_path / "t.wav", [heard], offset=0.0)
        assert instance.thread.turns[0].confidence == 0.4
        assert lines_of(instance.log)[-1]["confiance"] == 0.4
        replayed = replay(lines_of(instance.log))
        assert replayed.turns[0].confidence == 0.4

    def test_a_turn_the_engine_did_not_judge_stays_unjudged(self, tmp_path: Path) -> None:
        instance = follower(tmp_path, extractor=SequenceExtractor([voiceprint(1, 0)]))
        instance.take_in(tmp_path / "t.wav", [utterance(0, 8)], offset=0.0)
        assert lines_of(instance.log)[-1]["confiance"] is None
        assert replay(lines_of(instance.log)).turns[0].confidence is None

    def test_a_meeting_rebuilt_from_the_thread_keeps_the_doubt(self, tmp_path: Path) -> None:
        from greffier.application.recover import from_the_thread
        from greffier.domain import doubt

        instance = follower(tmp_path, extractor=SequenceExtractor([voiceprint(1, 0)]))
        heard = Utterance(span=Span(0, 8), text="on cale la recette jeudi", confidence=0.4)
        instance.take_in(tmp_path / "t.wav", [heard], offset=0.0)
        rebuilt = from_the_thread("2026-09-12_10h00_perdue", lines_of(instance.log))
        assert doubt.is_unsure(rebuilt.utterances[0])
