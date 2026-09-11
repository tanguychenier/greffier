"""The thread published during the meeting, and the corrections that come back.

Two processes talk to each other through files: the one that listens publishes
what is said, the window drops its corrections in. All of it is covered here
with no audio, no model and no screen; only the doubles change.
"""

from __future__ import annotations

import json
from pathlib import Path

from greffier.application.follow import (
    GENRE_CORRECTION,
    GENRE_SEPARATION,
    GENRE_TOUR,
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
from greffier.domain.models import Person, Span, Utterance, Voiceprint
from greffier.domain.voiceprints import normalise


def voiceprint(x: float, y: float, duration: float = 8.0) -> Voiceprint:
    return normalise([x, y, 0.0], source_duration=duration)


def utterance(start: float, end: float, text: str = "on cale la recette jeudi") -> Utterance:
    return Utterance(span=Span(start, end), text=text)


class StatedChannels:
    """Dit d'avance quels passages viennent du micro."""

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
        self, audio: Path, intervalles: list[Span]
    ) -> list[Voiceprint]:
        self.requests.append(intervalles)
        return [self.voiceprints.pop(0)] if self.voiceprints else []


class InMemoryBank:
    def __init__(self, known: list[Person] | None = None) -> None:
        self.known = list(known or [])
        self.recues: list[tuple[str, Voiceprint]] = []

    def people(self) -> list[Person]:
        return self.known

    def record(self, name: str, e: Voiceprint) -> Person:
        self.recues.append((name, e))
        person = Person(name=name, voiceprints=[e])
        self.known.append(person)
        return person


def follower(tmp_path: Path, **overrides: object) -> Follower:
    log, requests = files(tmp_path, "2026-08-27_10h00_reunion")
    defauts: dict[str, object] = dict(
        thread=LiveThread(), log=log, requests=requests, channels=StatedChannels()
    )
    defauts.update(overrides)
    return Follower(**defauts)  # type: ignore[arg-type]


def lines_of(log: Path) -> list[dict[str, object]]:
    lues, _ = read_from(log)
    return lues


class TestWhereWeAreInTheAudio:
    def test_the_last_piece_is_the_one_being_followed(self, tmp_path: Path) -> None:
        chunks = [tmp_path / "a.wav", tmp_path / "b.wav"]
        where_in = position(chunks, lambda m: 600.0 if m.name == "a.wav" else 30.0)
        assert where_in is not None
        assert where_in.morceau.name == "b.wav"
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
        assert where_in is not None and where_in.morceau.name == "a.wav"

    def test_with_no_audio_there_is_no_position(self, tmp_path: Path) -> None:
        assert position([tmp_path / "a.wav"], lambda _m: None) is None
        assert position([], lambda _m: 10.0) is None


class TestReadingOnlyWhatIsNew:
    def test_only_what_was_appended_is_read_again(self, tmp_path: Path) -> None:
        # The window rereads four times a second: rereading an hour of meeting
        # every turn would cost for nothing.
        log = tmp_path / "fil.jsonl"
        add(log, [{"genre": GENRE_TOUR, "numero": 1}])
        premieres, where_in = read_from(log)
        assert len(premieres) == 1
        add(log, [{"genre": GENRE_TOUR, "numero": 2}])
        suivantes, _ = read_from(log, where_in)
        assert [x["numero"] for x in suivantes] == [2]

    def test_a_half_written_line_waits_for_the_next_time(self, tmp_path: Path) -> None:
        log = tmp_path / "fil.jsonl"
        entiere = '{"genre": "tour", "numero": 1}\n'
        log.write_text(entiere + '{"genre": "tou', encoding="utf-8")
        lues, where_in = read_from(log)
        assert [x["numero"] for x in lues] == [1]
        # The position stops at the last complete line: the rest is read once
        # it is whole.
        assert where_in == len(entiere)

    def test_a_missing_log_makes_no_fuss(self, tmp_path: Path) -> None:
        assert read_from(tmp_path / "rien.jsonl") == ([], 0)


class TestPublishingWhatWasSaid:
    def test_every_sentence_becomes_a_line(self, tmp_path: Path) -> None:
        instance = follower(tmp_path)
        instance.take_in(
            tmp_path / "tranche.wav", [utterance(0, 4), utterance(4, 8)], offset=0.0
        )
        lines = lines_of(instance.log)
        assert [x["genre"] for x in lines] == [GENRE_TOUR, GENRE_TOUR]
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
            def extract_spans(self, audio: Path, intervalles: list[Span]):
                raise RuntimeError("BroadcastIterator::Init")

        instance = follower(tmp_path, extractor=Broken())
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], offset=0.0)
        # La phrase s'affiche sans nom, et se corrige d'un clic.
        assert len(instance.thread.turns) == 1


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
        faites = instance.apply_requests()
        assert [c.name for c in faites] == ["Marc"]
        assert instance.thread.label(instance.thread.turns[0].voice) == "Marc"

    def test_the_correction_is_confirmed_in_the_log(self, tmp_path: Path) -> None:
        # C'est ainsi que la fenêtre sait que sa correction a été prise, et que
        # toute autre fenêtre ouverte l'apprend aussi.
        instance = self._a_thread(tmp_path)
        ask(instance.requests, number=1, name="Marc")
        instance.apply_requests()
        confirmations = [
            x for x in lines_of(instance.log) if x["genre"] == GENRE_CORRECTION
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
        assert [name for name, _ in bank.recues] == ["Marc"]

    def test_your_own_voice_never_enters_the_bank(self, tmp_path: Path) -> None:
        # The mic already identifies whoever is recording: storing their voice
        # as a participant's would bring nothing and expose it.
        bank = InMemoryBank()
        instance = follower(tmp_path, channels=StatedChannels([Span(0, 8)]), bank=bank)
        instance.take_in(tmp_path / "tranche.wav", [utterance(0, 8)], offset=0.0)
        ask(instance.requests, number=1, name="Tanguy")
        instance.apply_requests()
        assert bank.recues == []

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
        assert bank.recues == []
        # The person speaks again: this time there is enough.
        instance.take_in(tmp_path / "t2.wav", [utterance(3, 9)], offset=0.0)
        assert [name for name, _ in bank.recues] == ["Sandy"]

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
        assert [name for name, _ in bank.recues] == ["Sandy"]

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
        rejoue = replay(lines_of(instance.log))
        assert [t.text for t in rejoue.turns] == ["bonjour", "on cale la recette jeudi"]
        assert rejoue.label(rejoue.turns[0].voice) == "Voix 1"

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
        rejoue = replay(lines_of(instance.log))
        assert rejoue.label(rejoue.turns[0].voice) == "Marc"
        assert rejoue.voice[rejoue.turns[0].voice].certainty is Certainty.HUMAINE

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
            + json.dumps({"genre": GENRE_TOUR, "numero": 1, "debut": 0, "fin": 2,
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
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        assert len({t.voice for t in instance.thread.turns}) == 2

    def test_the_split_is_confirmed_in_the_log(self, tmp_path: Path) -> None:
        # This is how any other open window, and a thread picked up after a
        # crash, learn that these two voices are not the same.
        instance = self._two_joined_voices(tmp_path)
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        dites = [
            x for x in lines_of(instance.log) if x["genre"] == GENRE_SEPARATION
        ]
        assert len(dites) == 1
        assert dites[0]["de"] == gardee
        assert dites[0]["numeros"] == [2]

    def test_a_replayed_thread_keeps_the_voices_apart(self, tmp_path: Path) -> None:
        """The point of it all: picking a thread up again does not remake the join."""
        instance = self._two_joined_voices(tmp_path)
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        repris = replay(lines_of(instance.log))
        assert len({t.voice for t in repris.turns}) == 2
        assert repris.split_apart, "la paire doit rester tenue à part"

    def test_every_voiceprint_goes_back_to_its_voice(self, tmp_path: Path) -> None:
        instance = self._two_joined_voices(tmp_path)
        gardee = instance.thread.turns[0].voice
        request_a_split(instance.requests, gardee)
        instance.apply_requests()
        comptes = {
            i: len(v.voiceprints)
            for i, v in instance.thread.voice.items()
            if v.voiceprints
        }
        assert sorted(comptes.values()) == [1, 1], comptes

    def test_splitting_what_absorbed_nothing_says_nothing(self, tmp_path: Path) -> None:
        instance = self._two_joined_voices(tmp_path)
        request_a_split(instance.requests, "voix-jamais-vue")
        instance.apply_requests()
        assert not [
            x for x in lines_of(instance.log) if x["genre"] == GENRE_SEPARATION
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
            "genre": GENRE_CORRECTION, "nom": "Marc", "voix": "v1", "numeros": [1],
        }
        if whole_voice is not None:
            correction["toute_la_voix"] = whole_voice
        add(log, [
            {"genre": GENRE_TOUR, "numero": 1, "debut": 0.0, "fin": 8.0,
             "texte": "on cale la recette jeudi", "voix": "v1",
             "nom": None, "certitude": Certainty.UNKNOWN.value, "rang": 1},
            correction,
            {"genre": GENRE_TOUR, "numero": 2, "debut": 9.0, "fin": 17.0,
             "texte": "le devis part demain matin", "voix": "v1",
             "nom": None, "certitude": Certainty.UNKNOWN.value, "rang": 1},
        ])
        return log

    def test_the_whole_voice_covers_the_turns_that_come_after(
        self, tmp_path: Path
    ) -> None:
        repris = replay(lines_of(self._log(tmp_path, True)))
        names = {repris.label(t.voice) for t in repris.turns}
        assert names == {"Marc"}, names

    def test_only_this_sentence_covers_only_the_sentence(
        self, tmp_path: Path
    ) -> None:
        repris = replay(lines_of(self._log(tmp_path, False)))
        par_numero = {t.number: repris.label(t.voice) for t in repris.turns}
        assert par_numero[1] == "Marc"
        assert par_numero[2] != "Marc"

    def test_a_log_from_before_stays_readable(self, tmp_path: Path) -> None:
        """Without the field: it falls back on the old deduction, for want of better."""
        repris = replay(lines_of(self._log(tmp_path)))
        assert repris.turns, "le journal doit rester relisible"


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
            {"genre": GENRE_TOUR, "numero": number, "debut": float(number * 10),
             "fin": float(number * 10 + 8), "texte": f"phrase {number}",
             "voix": f"v{number}", "nom": None,
             "certitude": Certainty.UNKNOWN.value, "rang": number}
            for number in (1, 2, 3)
        ])
        return log

    def test_the_counter_starts_after_the_last_voice_in_the_log(
        self, tmp_path: Path
    ) -> None:
        repris = replay(lines_of(self._log_of_two_voices(tmp_path)))
        assert repris._identifier() == "v4"

    def test_correcting_a_sentence_overwrites_no_voice(
        self, tmp_path: Path
    ) -> None:
        """The visible symptom: three voices replayed, one correction, still three
        distinct people, and not two turns under the same name.
        """
        repris = replay(lines_of(self._log_of_two_voices(tmp_path)))
        avant = {t.number: t.voice for t in repris.turns}
        repris.correct(2, "Marc", whole_voice=False)
        apres = {t.number: t.voice for t in repris.turns}
        assert apres[1] == avant[1], "la phrase 1 a changé de voix"
        assert apres[3] == avant[3], "la phrase 3 a changé de voix"
        assert len(set(apres.values())) == 3, apres


class TestARebuiltThreadShowsWhatTheListenerShows:
    """The window rebuilds the thread from the log; the listening process holds
    the live one. They must agree.

    Measured on a real ninety-minute meeting: three people out of nine were
    still shown twice at the end, because a correction made in the window names
    a voice like another one and the join that follows belongs to the listener.
    Replaying without joining namesakes showed both.
    """

    def _lignes(self, *voix: tuple[int, str, str, int]):
        return [
            {"genre": "tour", "numero": n, "debut": float(n), "fin": float(n) + 2.0,
             "texte": "on cale la recette", "voix": v, "nom": nom,
             "certitude": "humaine" if nom else "inconnue", "rang": rang}
            for n, v, nom, rang in voix
        ]

    def test_two_voices_of_one_name_become_one(self):
        from greffier.application.follow import replay

        thread = replay(self._lignes(
            (1, "v1", "Bastien", 1), (2, "v2", "Bastien", 2), (3, "v3", "Lise", 3),
        ))
        noms = sorted(v.name for v in thread.voice.values() if v.name)
        assert noms == ["Bastien", "Lise", "Toi"]

    def test_the_turns_of_both_are_kept(self):
        from greffier.application.follow import replay

        thread = replay(self._lignes(
            (1, "v1", "Bastien", 1), (2, "v2", "Bastien", 2),
        ))
        assert len(thread.turns) == 2
        assert len({t.voice for t in thread.turns}) == 1, "les deux tours vont à une voix"

    def test_a_number_the_log_shows_is_never_handed_out_again(self):
        from greffier.application.follow import replay

        thread = replay(self._lignes((1, "v1", "", 11)))
        assert thread.last_rank >= 11

    def test_voices_of_different_names_stay_apart(self):
        from greffier.application.follow import replay

        thread = replay(self._lignes(
            (1, "v1", "Bastien", 1), (2, "v2", "Lise", 2),
        ))
        assert len([v for v in thread.voice.values() if v.name]) == 3
