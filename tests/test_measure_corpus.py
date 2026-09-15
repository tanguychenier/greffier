"""The three figures of `tools/measure_corpus.py`, on cases small enough to count by hand."""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "tools"))

from measure_corpus import (  # noqa: E402
    Sentence,
    attribution,
    normalise,
    rare_terms,
    terms_found,
    truth_by_text,
    truth_by_time,
    word_error_rate,
)


class TestReadingBothSidesTheSameWay:
    def test_case_punctuation_and_fillers_do_not_count(self):
        assert normalise("Euh, Bonjour à TOUS !") == ["bonjour", "à", "tous"]

    def test_the_reference_s_spaced_apostrophes_are_glued_back(self):
        assert normalise("tu l' avais mal fait") == ["tu", "l'avais", "mal", "fait"]

    def test_the_reference_s_liaison_underscores_are_spaces(self):
        assert normalise("tout_le monde") == ["tout", "le", "monde"]

    def test_a_typographic_apostrophe_reads_like_a_plain_one(self):
        assert normalise("j’ai") == normalise("j'ai")


class TestWordErrorRate:
    def test_identical_texts_have_no_error(self):
        words = normalise("le compte rendu est prêt")
        assert word_error_rate(words, words) == 0.0

    def test_one_substitution_in_five_words_is_twenty_percent(self):
        reference = normalise("le compte rendu est prêt")
        hypothesis = normalise("le conte rendu est prêt")
        assert word_error_rate(reference, hypothesis) == 0.2

    def test_a_missing_word_counts_as_much_as_a_wrong_one(self):
        reference = normalise("le compte rendu est prêt")
        assert word_error_rate(reference, normalise("le rendu est prêt")) == 0.2


class TestRareTerms:
    def test_a_long_word_used_once_is_rare_and_a_short_or_repeated_one_is_not(self):
        words = normalise("le backlog du backlog et la planification et le kanban")
        assert rare_terms(words) == {"planification"}

    def test_found_counts_the_terms_the_hypothesis_carries(self):
        terms = {"planification", "copernic"}
        assert terms_found(terms, normalise("la planification de copernic")) == (2, 2)
        assert terms_found(terms, normalise("la planification de cornic")) == (1, 2)


def _timed_turns():
    return [
        {"speaker": "A", "start": 0.0, "end": 10.0, "text": "a"},
        {"speaker": "B", "start": 10.0, "end": 20.0, "text": "b"},
        {"speaker": "A", "start": 20.0, "end": 30.0, "text": "a"},
    ]


class TestTruthFromTimings:
    def test_a_sentence_takes_the_speaker_under_it(self):
        sentences = [Sentence(1.0, 4.0, "x", "v1"), Sentence(12.0, 15.0, "y", "v2")]
        assert truth_by_time(sentences, _timed_turns()) == ["A", "B"]

    def test_a_sentence_over_silence_has_no_truth(self):
        assert truth_by_time([Sentence(40.0, 45.0, "x", "v1")], _timed_turns()) == [None]

    def test_a_sentence_split_evenly_between_two_speakers_has_no_truth(self):
        assert truth_by_time([Sentence(5.0, 15.0, "x", "v1")], _timed_turns()) == [None]


class TestTruthFromText:
    def test_a_sentence_takes_the_speaker_of_the_words_it_lands_on(self):
        turns = [
            {"speaker": "Président", "text": "Mes chers collègues, je vous souhaite la bienvenue."},
            {"speaker": "Témoin", "text": "Je m'appelle Élina Dumont et j'ai cinquante-huit ans."},
        ]
        sentences = [
            Sentence(0.0, 3.0, "mes chers collègues je vous souhaite la bienvenue", "v1"),
            Sentence(3.0, 6.0, "je m'appelle Élina Dumont, j'ai 58 ans", "v2"),
        ]
        assert truth_by_text(sentences, turns).truths == ["Président", "Témoin"]

    def test_a_sentence_the_minutes_do_not_carry_has_no_truth(self):
        turns = [{"speaker": "Président", "text": "Mes chers collègues, bienvenue."}]
        sentences = [Sentence(0.0, 3.0, "pour cette dernière audition avant la pause", "v1")]
        aligned = truth_by_text(sentences, turns)
        assert aligned.truths == [None]
        assert aligned.covered == []

    def test_the_covered_region_is_the_part_of_the_minutes_that_was_heard(self):
        before = " ".join(f"avant{i}" for i in range(300))
        heard = " ".join(f"entendu{i}" for i in range(300))
        after = " ".join(f"apres{i}" for i in range(300))
        turns = [
            {"speaker": "A", "text": before},
            {"speaker": "B", "text": heard},
            {"speaker": "C", "text": after},
        ]
        sentences = [Sentence(0.0, 3.0, heard, "v1")]
        covered = truth_by_text(sentences, turns).covered
        assert covered == normalise(heard)


class TestCoveredRegion:
    def test_the_region_is_where_matches_are_dense_not_where_the_last_stray_word_fell(self):
        from measure_corpus import covered_region

        dense = [position for position in range(500, 1500) if position % 3 != 0]
        strays = [2100, 2450, 2800, 2999]
        assert covered_region(dense + strays, 3000) == (500, 1500)

    def test_nothing_matched_covers_nothing(self):
        from measure_corpus import covered_region

        assert covered_region([], 3000) == (0, 0)


class TestAttribution:
    def test_a_voice_is_the_person_it_mostly_carries(self):
        sentences = [
            Sentence(0, 10, "", "v1"),
            Sentence(10, 20, "", "v1"),
            Sentence(20, 30, "", "v1"),
            Sentence(30, 40, "", "v2"),
            Sentence(40, 50, "", None),
        ]
        truths = ["A", "A", "B", "B", "A"]
        result = attribution(sentences, truths)
        assert (result.right, result.wrong, result.no_opinion) == (3, 1, 1)
        assert result.judged == 5
        assert result.accuracy == 0.6
        assert (result.voices, result.scraps, result.people) == (2, 0, 2)

    def test_a_voice_under_ten_seconds_is_a_scrap_not_an_attendee(self):
        sentences = [Sentence(0, 30, "", "v1"), Sentence(30, 31, "", "v2")]
        result = attribution(sentences, ["A", "A"])
        assert (result.voices, result.scraps) == (1, 1)

    def test_sentences_without_truth_are_not_judged(self):
        result = attribution([Sentence(0, 1, "", "v1")], [None])
        assert result.judged == 0
        assert result.accuracy == 0.0
