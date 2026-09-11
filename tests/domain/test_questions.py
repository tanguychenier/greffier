"""Ce sur quoi l'outil a le droit de demander — et surtout ce sur quoi il se taît.

Une file de questions qui pose une question par phrase ne se lit pas : elle se
ferme. Les faux positifs mesurés sur le vocabulaire réel du poste sont donc
verrouillés ici, au même titre que les vrais.
"""

import pytest

from greffier.domain.questions import (
    QUESTIONS_MAXIMUM,
    Questioner,
    Reason,
    distance,
    tolerance,
)


class TestTheEditDistance:
    def test_two_identical_words_are_at_zero(self):
        assert distance("backlog", "backlog") == 0

    def test_a_transposition_counts_for_one(self):
        """Une transcription inverse des lettres : c'est le même mot.

        Sans cela « bakclog »/« backlog » valait 2, au même rang que
        « point »/« sprint », et aucun seuil ne pouvait séparer les deux cas.
        """
        assert distance("bakclog", "backlog") == 1

    def test_one_letter_more_counts_for_one(self):
        assert distance("ouasis", "oasis") == 1

    def test_two_unrelated_words_stay_far_apart(self):
        assert distance("point", "sprint") == 2


class TestHowMuchIsTolerated:
    def test_a_short_term_accepts_one_difference(self):
        assert tolerance("sprint") == 1

    def test_a_long_term_accepts_two(self):
        assert tolerance("infrastructure") == 2


class TestWhatRaisesAQuestion:
    def test_a_mangled_term_is_picked_up(self):
        questions = Questioner(known=("backlog",)).examine("Le bakclog est plein.")
        assert len(questions) == 1
        assert questions[0].expected == "backlog"
        assert questions[0].heard == "bakclog"
        assert questions[0].motif is Reason.NEAR_TERM

    def test_a_compound_term_is_read_word_by_word(self):
        """« mrege » ne rencontrait jamais « merge request » et passait inaperçu."""
        questions = Questioner(known=("merge request",)).examine("La mrege request.")
        assert questions and questions[0].expected == "merge"

    def test_the_question_says_what_it_heard(self):
        """Une question sans sa raison ressemble à un caprice : on n'y répond pas."""
        question = Questioner(known=("Oasis",)).examine("Point sur Ouasis.")[0]
        assert "Ouasis" in question.text
        assert "Oasis" in question.text


class TestWhatMustRaiseNothing:
    def test_an_everyday_word_does_not_become_a_term(self):
        """Mesuré : « point » et « sprint » sont à 2 et n'ont aucun rapport."""
        assert Questioner(known=("sprint",)).examine("On reprend le point.") == []

    def test_a_term_transcribed_right_asks_nothing(self):
        assert Questioner(known=("backlog",)).examine("Le backlog est trié.") == []

    def test_a_merely_unknown_word_is_no_signal(self):
        """Une réunion en contient des dizaines, tous légitimes."""
        assert Questioner(known=("backlog",)).examine("On parle de Kubernetes.") == []

    def test_short_words_are_dropped(self):
        """« CR » et « OR » sont à 1 et n'ont aucun rapport."""
        assert Questioner(known=("prod",)).examine("Le brod du truc.") == []

    def test_the_same_question_is_not_asked_twice(self):
        questioner = Questioner(known=("backlog",))
        assert questioner.examine("Le bakclog est plein.")
        assert questioner.examine("Le bakclog encore.") == []

    def test_the_tool_ends_up_going_quiet(self):
        """Au-delà d'un certain nombre, il noierait qui travaille."""
        known = tuple(f"terme{n:03d}" for n in range(40))
        questioner = Questioner(known=known)
        sentence = " ".join(f"terme{n:03d}x" for n in range(40))
        assert len(questioner.examine(sentence)) <= QUESTIONS_MAXIMUM


class TestAPluralIsNotAMangling:
    """Trois questions sur quatre étaient de cette nature, et absurdes.

    Relevé sur une réunion réelle : « J'ai entendu "bailleurs". Fallait-il
    comprendre "bailleur" ? », « J'ai entendu "pre-prod". Fallait-il comprendre
    "pré-prod" ? ». Un écart de un, donc sous le seuil, donc posé — et sans
    objet, puisque la réponse est déjà connue et qu'elle ne corrige rien. Le
    coût n'est pas la question : c'est qu'on cesse de lire les autres.
    """

    @pytest.mark.parametrize("heard,connu", [
        ("bailleurs", "bailleur"),
        ("serveurs", "serveur"),
        ("recettes", "recette"),
        ("pre-prod", "pré-prod"),
        ("PRE-PROD", "pré-prod"),
        ("Backlog", "backlog"),
        ("sprints", "sprint"),
    ])
    def test_no_question_about_a_variant(self, heard, connu):
        from greffier.domain.questions import Questioner

        assert Questioner(known=[connu]).examine(f"on parle du {heard}") == []

    @pytest.mark.parametrize("heard,connu", [
        ("Ouasis", "Oasis"),
        ("bakclog", "backlog"),
        ("Coppernic", "Copernic"),
    ])
    def test_a_real_mangling_is_still_picked_up(self, heard, connu):
        """La correction ne doit pas emporter ce pour quoi l'outil existe."""
        from greffier.domain.questions import Questioner

        asked = Questioner(known=[connu]).examine(f"on parle de {heard}")
        assert len(asked) == 1 and asked[0].expected == connu

    def test_the_exact_term_raises_nothing(self):
        from greffier.domain.questions import Questioner

        assert Questioner(known=["Oasis"]).examine("on parle d'Oasis") == []


class TestTheCanonicalForm:
    """Elle ne sert qu'à se taire, jamais à identifier."""

    def test_it_strips_what_does_not_change_the_word(self):
        from greffier.domain.questions import canonical_form

        assert canonical_form("Pré-Prods") == canonical_form("pre prod")

    def test_it_does_not_confuse_two_distinct_terms(self):
        from greffier.domain.questions import canonical_form

        assert canonical_form("Oasis") != canonical_form("Ouasis")


class TestWhatRecursIsNoAccident:
    """Une déformation ne se répète pas à l'identique.

    Le modèle rend « s'enature » une fois, pas trois. Un mot français revient,
    et c'est ce qui sépare « marge », qui est un mot, de « merve », qui n'en est
    pas un — sans avoir besoin d'un dictionnaire que le domaine n'a pas.
    """

    def test_a_word_heard_twice_is_no_longer_asked_about(self):
        from greffier.domain.questions import Questioner

        questioner = Questioner(known=["merge"])
        questioner.examine("il reste de la marge sur ce sprint")
        questioner.examine("on garde cette marge pour la dette")
        questioner.examine("la marge sert à absorber les retours")
        # La première occurrence a pu poser sa question ; les suivantes, non.
        assert len(questioner.asked) <= 1

    def test_a_term_already_transcribed_right_silences_its_neighbours(self):
        """Si le modèle sait écrire « merge », il n'a pas déformé ici."""
        from greffier.domain.questions import Questioner

        questioner = Questioner(known=["merge"])
        questioner.examine("j'ai fait le merge ce matin")
        assert questioner.examine("il reste de la marge") == []

    def test_a_lone_mangling_is_still_picked_up(self):
        from greffier.domain.questions import Questioner

        asked = Questioner(known=["signature"]).examine(
            "la s'enature n'est pas passée")
        assert len(asked) == 1 and asked[0].expected == "signature"


class TestADerivedWord:
    """Un terme précédé d'un préfixe est un autre mot, pas une faute."""

    @pytest.mark.parametrize("heard,connu", [
        ("rétablissements", "établissement"),
        ("reprod", "prod"),
        ("déploiement", "ploiement"),
    ])
    def test_a_derived_word_raises_nothing(self, heard, connu):
        from greffier.domain.questions import derived_word

        assert derived_word(heard, connu)

    def test_the_elision_counts(self):
        """« ré- » devant une voyelle donne « rétablissement ».

        Sans elle, le cas qui a motivé la règle passait au travers.
        """
        from greffier.domain.questions import derived_word

        assert derived_word("rétablissement", "établissement")

    @pytest.mark.parametrize("heard,connu", [
        ("Ouasis", "Oasis"),
        ("merde", "merge"),
        ("bakclog", "backlog"),
    ])
    def test_a_mangling_is_not_a_derived_word(self, heard, connu):
        from greffier.domain.questions import derived_word

        assert not derived_word(heard, connu)

    def test_a_false_positive_costs_only_a_silence(self):
        """« recette » passe pour « re » + « cette », et c'est assumé.

        La règle ne sert qu'à se taire : ne pas poser une question coûte moins
        qu'en poser une absurde, et « cette » n'a rien à faire dans un
        vocabulaire métier.
        """
        from greffier.domain.questions import derived_word

        assert derived_word("recette", "cette")
