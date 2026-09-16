"""The context of a working setting: what a model cannot guess."""

import pytest

from greffier.domain.context import (
    PROMPT_MAXIMUM,
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
    """What decides the spelling during the transcription.

    Measured on 2026-09-09 on a real meeting: "déploiement" returned as
    "exploitement", "emploi du temps" returned as "emploi fictif". Those words are
    nowhere in what a model has learnt.
    """

    def test_terms_and_names_are_in_it_together(self):
        context = Context(
            terms=(Term("CASA"),),
            attendees_=(Speaker_("Katell"),),
        )
        prompt_seed = context.prompt_seed()
        assert "CASA" in prompt_seed
        assert "Katell" in prompt_seed

    def test_the_meaning_does_not_clutter_the_seed(self):
        """The transcriber does not reason: giving it definitions drowns it."""
        prompt_seed = Context(terms=(Term("OTP", "mot de passe à usage unique"),)).prompt_seed()
        assert "OTP" in prompt_seed
        assert "usage unique" not in prompt_seed

    def test_an_empty_context_produces_no_seed(self):
        assert Context().prompt_seed() == ""

    def test_the_seed_fits_what_the_model_accepts(self):
        """whisper tronque au-delà de 224 jetons, sans prévenir."""
        context = Context(terms=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        assert len(context.prompt_seed()) <= PROMPT_MAXIMUM

    def test_what_does_not_fit_is_named(self):
        context = Context(terms=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        assert context.set_aside(), "il faut pouvoir avertir plutôt que tronquer en silence"

    def test_no_term_is_cut_in_half(self):
        """A spelling cut in half teaches a wrong one: worse than nothing."""
        context = Context(terms=tuple(Term(f"terme-{n:03d}") for n in range(200)))
        for word in context.prompt_seed().split("Vocabulaire : ")[1].rstrip(".").split(", "):
            assert word.startswith("terme-") and len(word) == len("terme-000")

    def test_a_repeated_term_counts_once(self):
        prompt_seed = Context(terms=(Term("OTP"), Term("OTP"))).prompt_seed()
        assert prompt_seed.count("OTP") == 1


class TestTheHeaderForTheWriter:
    """What the writer receives: the spellings **and** their meanings."""

    def test_the_meanings_are_given_to_the_writer(self):
        header = Context(terms=(Term("OTP", "mot de passe à usage unique"),)).header()
        assert "mot de passe à usage unique" in header

    def test_the_writer_is_asked_not_to_recite_the_glossary(self):
        header = Context(terms=(Term("OTP"),)).header()
        assert "que ceux dont il est question" in header

    def test_a_role_does_not_allow_lending_someone_a_position(self):
        header = Context(attendees_=(Speaker_("Sophie", "cheffe de projet"),)).header()
        assert "jamais d'après son rôle" in header

    def test_an_empty_context_says_nothing(self):
        assert Context().header() == ""


class TestJoiningTwoContexts:
    """The context of the machine, completed by that of one meeting."""

    def test_the_more_precise_one_wins(self):
        general = Context(terms=(Term("OTP", "ancien sens"),))
        precise = Context(terms=(Term("OTP", "mot de passe à usage unique"),))
        fondu = general.join(precise)
        assert len(fondu.terms) == 1
        assert fondu.terms[0].meaning == "mot de passe à usage unique"

    def test_case_creates_no_duplicate(self):
        fondu = Context(terms=(Term("Casa"),)).join(Context(terms=(Term("CASA"),)))
        assert len(fondu.terms) == 1

    def test_the_two_sources_complete_each_other(self):
        fondu = Context(terms=(Term("CASA"),)).join(Context(terms=(Term("OTP"),)))
        assert {t.spelling for t in fondu.terms} == {"CASA", "OTP"}

    def test_joining_changes_neither_of_the_two(self):
        general = Context(terms=(Term("CASA"),))
        general.join(Context(terms=(Term("OTP"),)))
        assert len(general.terms) == 1


class TestTheExpectedPeople:
    """What the prompt gains from carrying the expected people.

    Measured on a meeting carrying seven rare terms: eleven occurrences out of
    fifteen come back without the prompt, fifteen out of fifteen with it.
    « backlog » became « bâcle », « Kanban » became « cambans ». A first name
    announced before the meeting has no voice in the bank yet: without the
    prompt, it is the first word the model replaces.
    """

    def test_an_expected_person_reaches_the_seed(self):
        seed = Context(terms=(Term("OTP"),)).prompt_seed(["Solène"])
        assert "Solène" in seed and "OTP" in seed

    def test_nobody_expected_changes_nothing(self):
        alone = Context(terms=(Term("OTP"),))
        assert alone.prompt_seed([]) == alone.prompt_seed()

    def test_a_blank_name_is_not_carried(self):
        seed = Context(terms=(Term("OTP"),)).prompt_seed(["  ", ""])
        assert seed == Context(terms=(Term("OTP"),)).prompt_seed()

    def test_the_glossary_is_served_first(self):
        """The bank fills up on its own and would push out what was chosen."""
        expected = [f"Personne{n:03}" for n in range(200)]
        seed = Context(terms=(Term("Copernic"),)).prompt_seed(expected)
        assert "Copernic" in seed

    def test_what_did_not_fit_can_be_said(self):
        expected = [f"Personne{n:03}" for n in range(200)]
        set_aside = Context(terms=(Term("Copernic"),)).set_aside(expected)
        assert "Copernic" not in set_aside
        assert len(set_aside) > 0

    def test_an_expected_person_already_declared_is_carried_once(self):
        seed = Context(attendees_=(Speaker_("Solène"),)).prompt_seed(["Solène"])
        assert seed.count("Solène") == 1
