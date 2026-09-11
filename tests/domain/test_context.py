"""Le contexte du milieu : ce qu'un modèle ne peut pas deviner."""

import pytest

from greffier.domain.context import (
    AMORCE_MAXIMUM,
    Context,
    Speaker_,
    Term,
)


class TestATerm:
    def test_an_acronym_carries_its_meaning_for_the_writer(self):
        assert Term("OTP", "mot de passe à usage unique").gloss == (
            "OTP (mot de passe à usage unique)"
        )

    def test_with_no_meaning_the_term_stays_bare(self):
        assert Term("CASA").gloss == "CASA"

    def test_a_term_with_no_spelling_is_refused(self):
        with pytest.raises(ValueError, match="sans écriture"):
            Term("   ")


class TestThePromptSeed:
    """Ce qui décide de l'orthographe pendant la transcription.

    Mesuré le 2026-09-09 sur une réunion réelle : « déploiement » rendu
    « exploitement », « emploi du temps » rendu « emploi fictif ». Ces mots ne
    sont nulle part dans ce qu'un modèle a appris.
    """

    def test_terms_and_names_are_in_it_together(self):
        context = Context(
            termes=(Term("CASA"),),
            intervenants=(Speaker_("Kerann"),),
        )
        prompt_seed = context.prompt_seed()
        assert "CASA" in prompt_seed
        assert "Kerann" in prompt_seed

    def test_the_meaning_does_not_clutter_the_seed(self):
        """Le transcripteur ne raisonne pas : lui donner des définitions le noie."""
        prompt_seed = Context(termes=(Term("OTP", "mot de passe à usage unique"),)).prompt_seed()
        assert "OTP" in prompt_seed
        assert "usage unique" not in prompt_seed

    def test_an_empty_context_produces_no_seed(self):
        assert Context().prompt_seed() == ""

    def test_the_seed_fits_what_the_model_accepts(self):
        """whisper tronque au-delà de 224 jetons, sans prévenir."""
        context = Context(termes=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        assert len(context.prompt_seed()) <= AMORCE_MAXIMUM

    def test_what_does_not_fit_is_named(self):
        context = Context(termes=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        assert context.ecartes(), "il faut pouvoir avertir plutôt que tronquer en silence"

    def test_no_term_is_cut_in_half(self):
        """Une écriture coupée apprend une orthographe fausse : pire que rien."""
        context = Context(termes=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        for word in context.prompt_seed().split("Vocabulaire : ")[1].rstrip(".").split(", "):
            assert word.startswith("terme-") and len(word) == len("terme-000")

    def test_a_repeated_term_counts_once(self):
        prompt_seed = Context(termes=(Term("OTP"), Term("OTP"))).prompt_seed()
        assert prompt_seed.count("OTP") == 1


class TestTheHeaderForTheWriter:
    """Ce que le rédacteur reçoit : les écritures **et** leur sens."""

    def test_the_meanings_are_given_to_the_writer(self):
        header = Context(termes=(Term("OTP", "mot de passe à usage unique"),)).header()
        assert "mot de passe à usage unique" in header

    def test_the_writer_is_asked_not_to_recite_the_glossary(self):
        header = Context(termes=(Term("OTP"),)).header()
        assert "que ceux dont il est question" in header

    def test_a_role_does_not_allow_lending_someone_a_position(self):
        header = Context(intervenants=(Speaker_("Sophie", "cheffe de projet"),)).header()
        assert "jamais d'après son rôle" in header

    def test_an_empty_context_says_nothing(self):
        assert Context().header() == ""


class TestJoiningTwoContexts:
    """Le contexte du poste, complété par celui d'une réunion précise."""

    def test_the_more_precise_one_wins(self):
        general = Context(termes=(Term("OTP", "ancien sens"),))
        precis = Context(termes=(Term("OTP", "mot de passe à usage unique"),))
        fondu = general.join(precis)
        assert len(fondu.termes) == 1
        assert fondu.termes[0].sens == "mot de passe à usage unique"

    def test_case_creates_no_duplicate(self):
        fondu = Context(termes=(Term("Casa"),)).join(Context(termes=(Term("CASA"),)))
        assert len(fondu.termes) == 1

    def test_the_two_sources_complete_each_other(self):
        fondu = Context(termes=(Term("CASA"),)).join(Context(termes=(Term("OTP"),)))
        assert {t.ecriture for t in fondu.termes} == {"CASA", "OTP"}

    def test_joining_changes_neither_of_the_two(self):
        general = Context(termes=(Term("CASA"),))
        general.join(Context(termes=(Term("OTP"),)))
        assert len(general.termes) == 1
