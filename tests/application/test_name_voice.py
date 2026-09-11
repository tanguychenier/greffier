"""`voix_a_nommer` : quelles voix proposer à l'utilisateur, et lesquelles taire."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.application.name_voice import voices_to_name
from greffier.domain.meeting import StoredMeeting
from greffier.domain.models import Span, SpeakerTurn, Utterance


def reunion_type(**overrides) -> StoredMeeting:
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


class TestVoixANommer:
    def test_une_voix_courte_sans_indice_reste_ecartee(self):
        """Le comportement d'origine, préservé : un fragment sans rien pour le
        rattacher ne doit pas passer pour un participant."""
        meeting = reunion_type()
        assert "2" not in {v.voice for v in voices_to_name(meeting)}

    def test_une_proposition_sur_une_voix_courte_n_est_pas_perdue(self):
        """Le défaut corrigé : un prénom détecté dans une réponse brève doit
        survivre au filtre de durée, sans quoi il ne s'affiche jamais."""
        meeting = reunion_type(propositions={"2": "Kilian"})
        input = next(v for v in voices_to_name(meeting) if v.voice == "2")
        assert input.proposition == "Kilian"
        assert input.to_name

    def test_un_nom_deja_attribue_sur_une_voix_courte_n_est_pas_perdu(self):
        meeting = reunion_type(names={"2": "Kilian"})
        input = next(v for v in voices_to_name(meeting) if v.voice == "2")
        assert input.name == "Kilian"
        assert not input.to_name

    def test_une_voix_longue_reste_toujours_proposee(self):
        meeting = reunion_type()
        assert "1" in {v.voice for v in voices_to_name(meeting)}

    def test_la_part_relative_ignore_les_voix_courtes_reintroduites(self):
        """Réintroduire une voix courte ne doit pas diluer la part de celles
        qui dépassent déjà le seuil de matière."""
        meeting = reunion_type(propositions={"2": "Kilian"})
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


def nommage_factice(meeting):
    from greffier.application.name_voice import Naming

    store = FakeStore(meeting)
    return Naming(store=store, bank=FakeBank(), extractor=FakeExtractor())


class TestNommerReunitLesVoix:
    def test_deux_voix_du_meme_prenom_deviennent_une(self):
        """Le geste qu'on fait sans le savoir.

        Nommer « Marcel » une deuxième voix, c'est dire qu'elle est de Marcel,
        donc de la même personne. Sans réunion, le compte rendu annonçait deux
        Marcel, et une réunion réelle a demandé trente-six nommages à la main
        pour trois personnes présentes.
        """
        meeting = reunion_type(
            utterances=[Utterance(Span(0, 40), "bonjour", "1"),
                       Utterance(Span(60, 80), "oui", "2")],
            turns=[SpeakerTurn(Span(0, 40), "1"),
                   SpeakerTurn(Span(60, 80), "2")],
            names={"1": "Marcel"},
        )
        naming = nommage_factice(meeting)
        rendered = naming.name_voice("2026-08-24_reunion", "2", "Marcel")
        assert list(rendered.names.values()) == ["Marcel"]
        assert len(set(t.voice for t in rendered.turns)) == 1

    def test_la_voix_la_plus_fournie_garde_son_identifiant(self):
        """C'est son extrait qu'on réécoutera : autant que ce soit le plus long."""
        meeting = reunion_type(
            utterances=[Utterance(Span(0, 5), "oui", "petite"),
                       Utterance(Span(10, 90), "un long propos", "grande")],
            turns=[SpeakerTurn(Span(0, 5), "petite"),
                   SpeakerTurn(Span(10, 90), "grande")],
            names={"grande": "Marcel"},
        )
        rendered = nommage_factice(meeting).name_voice("2026-08-24_reunion", "petite", "Marcel")
        assert set(rendered.names) == {"grande"}

    def test_case_does_not_create_two_people(self):
        meeting = reunion_type(
            utterances=[Utterance(Span(0, 40), "a", "1"),
                       Utterance(Span(60, 80), "b", "2")],
            turns=[SpeakerTurn(Span(0, 40), "1"),
                   SpeakerTurn(Span(60, 80), "2")],
            names={"1": "Marcel"},
        )
        rendered = nommage_factice(meeting).name_voice("2026-08-24_reunion", "2", "marcel")
        assert list(rendered.names.values()) == ["Marcel"]


class TestNommerRefuseCeQuiNEnEstPas:
    def test_le_libelle_de_l_interface_n_entre_pas_en_banque(self):
        """La banque du poste portait « A nommer ». Plus jamais."""
        import pytest

        naming = nommage_factice(reunion_type())
        with pytest.raises(ValueError, match="pas un prénom"):
            naming.name_voice("2026-08-24_reunion", "1", "A nommer")

    def test_rien_n_est_verse_en_banque_quand_le_nom_est_refuse(self):
        import pytest

        meeting = reunion_type()
        naming = nommage_factice(meeting)
        with pytest.raises(ValueError):
            naming.name_voice("2026-08-24_reunion", "1", "?")
        assert naming.bank.ajouts == []


class TestOublier:
    def test_un_nom_pose_par_erreur_se_retire(self):
        """Le geste le plus coûteux de l'outil n'était pas défaisable."""
        meeting = reunion_type(names={"1": "Marcel"})
        rendered = nommage_factice(meeting).forget("2026-08-24_reunion", "1")
        assert rendered.names == {}

    def test_oublier_une_voix_sans_nom_le_dit(self):
        import pytest

        with pytest.raises(KeyError):
            nommage_factice(reunion_type()).forget("2026-08-24_reunion", "1")

    def test_une_proposition_s_oublie_aussi(self):
        meeting = reunion_type(propositions={"1": "Kilian"})
        rendered = nommage_factice(meeting).forget("2026-08-24_reunion", "1")
        assert rendered.propositions == {}
