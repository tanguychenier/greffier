"""`voix_a_nommer` : quelles voix proposer à l'utilisateur, et lesquelles taire."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.application.name_voice import voices_to_name
from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Span, SpeakerTurn, Utterance


def a_meeting(**overrides) -> StoredMeeting:
    defauts = dict(
        identifier="2026-08-24_reunion",
        audio=Path("/tmp/r.wav"),
        processed_at=datetime.now(UTC),
        duration=100.0,
        utterances=[Utterance(Span(0, 40), "bonjour à tous", "1"),
                   Utterance(Span(60, 65), "bref", "2")],
        turns=[SpeakerTurn(Span(0, 40), "1"), SpeakerTurn(Span(60, 65), "2")],
        names={},
        propositions={},
        warnings=[],
    )
    defauts.update(overrides)
    return StoredMeeting(**defauts)


class TestTheVoicesOfferedForNaming:
    def test_a_short_voice_with_no_clue_stays_out(self):
        """Le comportement d'origine, préservé : un fragment sans rien pour le
        rattacher ne doit pas passer pour un participant."""
        meeting = a_meeting()
        assert "2" not in {v.voice for v in voices_to_name(meeting)}

    def test_a_guess_on_a_short_voice_is_not_lost(self):
        """Le défaut corrigé : un prénom détecté dans une réponse brève doit
        survivre au filtre de durée, sans quoi il ne s'affiche jamais."""
        meeting = a_meeting(propositions={"2": "Kévin"})
        input = next(v for v in voices_to_name(meeting) if v.voice == "2")
        assert input.proposition == "Kévin"
        assert input.to_name

    def test_a_name_already_given_to_a_short_voice_is_not_lost(self):
        meeting = a_meeting(names={"2": "Kévin"})
        input = next(v for v in voices_to_name(meeting) if v.voice == "2")
        assert input.name == "Kévin"
        assert not input.to_name

    def test_a_long_voice_is_always_offered(self):
        meeting = a_meeting()
        assert "1" in {v.voice for v in voices_to_name(meeting)}

    def test_the_share_ignores_the_short_voices_brought_back_in(self):
        """Réintroduire une voix courte ne doit pas diluer la part de celles
        qui dépassent déjà le seuil de matière."""
        meeting = a_meeting(propositions={"2": "Kévin"})
        longue = next(v for v in voices_to_name(meeting) if v.voice == "1")
        assert longue.part == 1.0


class FakeStore:
    def __init__(self, meeting):
        self.meeting = meeting
        self.ecritures = 0

    def read(self, _identifier):
        return self.meeting

    def record(self, meeting):
        self.meeting = meeting
        self.ecritures += 1


class FakeBank:
    def __init__(self):
        self.ajouts = []

    def people(self):
        return []

    def record(self, name, voiceprint):
        self.ajouts.append(name)


class FakeExtractor:
    def extract_spans(self, _audio, intervalles):
        from greffier.domain.voiceprints import normalise

        return [normalise([1.0, 0.0], source_duration=i.duration) for i in intervalles]


def a_naming_setup(meeting):
    from greffier.application.name_voice import Naming

    store = FakeStore(meeting)
    return Naming(store=store, bank=FakeBank(), extractor=FakeExtractor())


class TestNamingJoinsTheVoices:
    def test_two_voices_of_one_first_name_become_one(self):
        """Le geste qu'on fait sans le savoir.

        Nommer « Michel » une deuxième voix, c'est dire qu'elle est de Michel,
        donc de la même personne. Sans réunion, le compte rendu annonçait deux
        Michel, et une réunion réelle a demandé trente-six nommages à la main
        pour trois personnes présentes.
        """
        meeting = a_meeting(
            utterances=[Utterance(Span(0, 40), "bonjour", "1"),
                       Utterance(Span(60, 80), "oui", "2")],
            turns=[SpeakerTurn(Span(0, 40), "1"),
                   SpeakerTurn(Span(60, 80), "2")],
            names={"1": "Michel"},
        )
        naming = a_naming_setup(meeting)
        rendered = naming.name_voice("2026-08-24_reunion", "2", "Michel")
        assert list(rendered.names.values()) == ["Michel"]
        assert len(set(t.voice for t in rendered.turns)) == 1

    def test_the_best_fed_voice_keeps_its_identifier(self):
        """C'est son extrait qu'on réécoutera : autant que ce soit le plus long."""
        meeting = a_meeting(
            utterances=[Utterance(Span(0, 5), "oui", "petite"),
                       Utterance(Span(10, 90), "un long propos", "grande")],
            turns=[SpeakerTurn(Span(0, 5), "petite"),
                   SpeakerTurn(Span(10, 90), "grande")],
            names={"grande": "Michel"},
        )
        rendered = a_naming_setup(meeting).name_voice("2026-08-24_reunion", "petite", "Michel")
        assert set(rendered.names) == {"grande"}

    def test_case_does_not_create_two_people(self):
        meeting = a_meeting(
            utterances=[Utterance(Span(0, 40), "a", "1"),
                       Utterance(Span(60, 80), "b", "2")],
            turns=[SpeakerTurn(Span(0, 40), "1"),
                   SpeakerTurn(Span(60, 80), "2")],
            names={"1": "Michel"},
        )
        rendered = a_naming_setup(meeting).name_voice("2026-08-24_reunion", "2", "michel")
        assert list(rendered.names.values()) == ["Michel"]


class TestNamingRefusesWhatIsNotAName:
    def test_a_label_of_the_window_does_not_enter_the_bank(self):
        """La banque du poste portait « A nommer ». Plus jamais."""
        import pytest

        naming = a_naming_setup(a_meeting())
        with pytest.raises(ValueError, match="pas un prénom"):
            naming.name_voice("2026-08-24_reunion", "1", "A nommer")

    def test_nothing_is_poured_into_the_bank_when_the_name_is_refused(self):
        import pytest

        meeting = a_meeting()
        naming = a_naming_setup(meeting)
        with pytest.raises(ValueError):
            naming.name_voice("2026-08-24_reunion", "1", "?")
        assert naming.bank.ajouts == []


class TestForgettingAName:
    def test_a_name_given_by_mistake_can_be_taken_back(self):
        """Le geste le plus coûteux de l'outil n'était pas défaisable."""
        meeting = a_meeting(names={"1": "Michel"})
        rendered = a_naming_setup(meeting).forget("2026-08-24_reunion", "1")
        assert rendered.names == {}

    def test_forgetting_an_unnamed_voice_says_so(self):
        import pytest

        with pytest.raises(KeyError):
            a_naming_setup(a_meeting()).forget("2026-08-24_reunion", "1")

    def test_a_guess_can_be_forgotten_too(self):
        meeting = a_meeting(propositions={"1": "Kévin"})
        rendered = a_naming_setup(meeting).forget("2026-08-24_reunion", "1")
        assert rendered.propositions == {}
