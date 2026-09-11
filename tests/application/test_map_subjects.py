"""Extracting the points of a meeting: invent nothing, agree to nothing wrongly."""

import pytest

from greffier.application.map_subjects import UnreadableOutput, analyser, extract
from greffier.domain.board import Kind, Standing


class FakeWriter:
    def __init__(self, rendered: str) -> None:
        self.rendered = rendered
        self.recu = ""

    def write_up(self, transcription: str) -> str:
        self.recu = transcription
        return self.rendered


class TestReadingWhatTheWriterReturned:
    def test_a_clean_array_is_read(self):
        apports = analyser(
            '[{"texte": "Le PDF ne se régénère pas", "genre": "problème", '
            '"etat": "en discussion", "sous": ""}]'
        )
        assert len(apports) == 1
        assert apports[0].kind is Kind.PROBLEM
        assert apports[0].state is Standing.UNDER_DISCUSSION

    def test_a_code_fence_is_accepted(self):
        """Le rédacteur enrobe volontiers, malgré la consigne."""
        apports = analyser('```json\n[{"texte": "Un point"}]\n```')
        assert [a.text for a in apports] == ["Un point"]

    def test_chatter_around_the_array_is_tolerated(self):
        apports = analyser('Voici la liste :\n[{"texte": "Un point"}]\nVoilà.')
        assert [a.text for a in apports] == ["Un point"]

    def test_an_answer_with_no_array_raises(self):
        """A failure must not read as "nothing to add".

        Measured: the model answered in prose, asking whether that was the array
        expected, and the command announced "rien à ajouter".
        """
        with pytest.raises(UnreadableOutput, match="aucun tableau"):
            analyser("Je n'ai rien trouvé sur ce sujet.")

    def test_broken_json_raises(self):
        """Brackets present but the content invalid."""
        with pytest.raises(UnreadableOutput, match="invalide"):
            analyser('[{"texte": "incomplet", }]')

    def test_an_answer_cut_before_the_closing_bracket_raises(self):
        with pytest.raises(UnreadableOutput, match="aucun tableau"):
            analyser('[{"texte": "incomplet"')

    def test_an_empty_array_is_a_result_not_a_failure(self):
        assert analyser("[]") == []

    def test_one_broken_item_does_not_lose_the_others(self):
        apports = analyser('[{"texte": "Bon"}, "pas un objet", {"texte": "Aussi bon"}]')
        assert [a.text for a in apports] == ["Bon", "Aussi bon"]

    def test_an_item_with_no_text_is_dropped(self):
        assert analyser('[{"genre": "piste"}]') == []

    def test_the_list_is_capped(self):
        """An unreadable board serves nobody."""
        rendered = "[" + ",".join(f'{{"texte": "point {n}"}}' for n in range(40)) + "]"
        assert len(analyser(rendered, maximum=12)) == 12


class TestCarefulAboutTheStanding:
    """Presenting a spoken idea as a decision is the worst defect here."""

    def test_the_default_is_under_discussion(self):
        assert analyser('[{"texte": "Une idée"}]')[0].state is Standing.UNDER_DISCUSSION

    def test_an_unrecognised_standing_falls_back_to_under_discussion(self):
        apports = analyser('[{"texte": "Une idée", "etat": "peut-être"}]')
        assert apports[0].state is Standing.UNDER_DISCUSSION

    def test_overtaken_cannot_come_from_an_extraction(self):
        """Only a person marks a lead as overtaken."""
        apports = analyser('[{"texte": "Une piste", "etat": "dépassé"}]')
        assert apports[0].state is Standing.UNDER_DISCUSSION

    def test_agreed_is_honoured_when_it_is_explicit(self):
        apports = analyser('[{"texte": "Monter la recette", "etat": "acté"}]')
        assert apports[0].state is Standing.AGREED

    def test_an_unrecognised_kind_becomes_an_observation(self):
        assert analyser('[{"texte": "X", "genre": "truc"}]')[0].kind is Kind.OBSERVATION


class TestWhatIsAskedOfTheWriter:
    def test_the_subject_and_the_material_are_passed_on(self):
        writer = FakeWriter('[{"texte": "Un point"}]')
        extract(writer, "Oasis", "On a parlé d'Oasis longuement.")
        assert "Oasis" in writer.recu
        assert "On a parlé d'Oasis longuement." in writer.recu

    def test_the_guidance_is_not_repeated_inside_the_call(self):
        """It is carried by the writer, not by the caller.

        Repeated here, it arrived after the guidance for the minutes and the model
        followed the first.
        """
        writer = FakeWriter('[{"texte": "Un point"}]')
        extract(writer, "Oasis", "matière")
        assert "Tu extrais" not in writer.recu

    def test_empty_material_does_not_call_the_writer(self):
        writer = FakeWriter("[]")
        assert extract(writer, "Oasis", "   ") == []
        assert writer.recu == "", "aucun appel ne doit partir"

    def test_the_guidance_forbids_naming_people(self):
        from greffier.application.map_subjects import GUIDANCE

        aplati = " ".join(GUIDANCE.split())
        assert "ni nom de personne ni citation" in aplati

    def test_the_guidance_makes_doubt_fall_on_the_discussion_side(self):
        from greffier.application.map_subjects import GUIDANCE

        aplati = " ".join(GUIDANCE.split())
        assert "En cas de doute, « en discussion »" in aplati


class TestCompletingWithoutDuplicating:
    """The central defect: the board filled up with duplicates.

    Measured on the second publication: thirteen points became twenty-six, the
    writer having reworded "Pré-production du client en retard de deux versions"
    into "Pré-prod cliente en retard de deux versions".
    """

    def test_the_existing_labels_are_given_to_the_writer(self):
        writer = FakeWriter('[{"texte": "Un point"}]')
        extract(writer, "Oasis", "matière",
                 already=("Pré-production du client en retard de deux versions",))
        assert "Pré-production du client en retard" in writer.recu

    def test_it_is_asked_to_reuse_them_word_for_word(self):
        writer = FakeWriter("[]")
        extract(writer, "Oasis", "matière", already=("Un point existant",))
        assert "mot pour mot" in writer.recu

    def test_with_no_existing_board_nothing_is_added_to_the_prompt(self):
        writer = FakeWriter("[]")
        extract(writer, "Oasis", "matière")
        assert "Déjà sur la carte" not in writer.recu

    def test_the_guidance_says_not_to_reuse_them_wrongly(self):
        """Reprendre un libellé pour un point différent serait pire."""
        from greffier.application.map_subjects import GUIDANCE

        aplati = " ".join(GUIDANCE.split())
        assert "Ne le reprends que s'il s'agit vraiment du même point" in aplati
