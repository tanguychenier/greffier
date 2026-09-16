"""What a meeting leaves for the ones that follow.

The voice bank already carried people from one meeting to the next; what was
decided and what stayed open did not. A second meeting on the same work started
from nothing, and the room said again what it had said the week before.
"""

from __future__ import annotations

from greffier.domain.memory import MAXIMUM_REMINDER, Trace, recalled, what_the_minutes_left

MINUTES = """# Compte rendu : point sur la recette

durée 39 s. Participants : Jacques, Sophie.

## Décisions

- La recette est décalée à jeudi prochain.
- Les utilisateurs seront prévenus mercredi.

## Actions

| Qui | Quoi | Quand |
|---|---|---|
| Sophie | Valider les écarts | jeudi |

## Points ouverts

- Validation fonctionnelle des deux anomalies : aucune date donnée.

## Détail par sujet

### Déploiement

Rien à signaler.
"""


class TestReadingWhatTheMinutesLeft:
    def test_the_decisions_are_read_from_the_minutes(self):
        decisions, _ = what_the_minutes_left(MINUTES)
        assert decisions == (
            "La recette est décalée à jeudi prochain.",
            "Les utilisateurs seront prévenus mercredi.",
        )

    def test_the_open_points_too(self):
        _, open_ones = what_the_minutes_left(MINUTES)
        assert open_ones == (
            "Validation fonctionnelle des deux anomalies : aucune date donnée.",
        )

    def test_a_table_is_not_a_list_of_decisions(self):
        """The actions are a table, and a row is not a bullet."""
        decisions, _ = what_the_minutes_left(MINUTES)
        assert not any("|" in point for point in decisions)

    def test_minutes_without_those_headings_leave_nothing(self):
        assert what_the_minutes_left("# Compte rendu\n\nRien de décidé.\n") == ((), ())

    def test_an_empty_text_is_not_an_error(self):
        assert what_the_minutes_left("") == ((), ())


class TestTheTitleOfARecalledMeeting:
    """Recalled as they come, every meeting starts with the same three words."""

    def test_the_words_every_set_of_minutes_carries_are_dropped(self):
        from greffier.domain.memory import short_title

        assert short_title("Compte rendu : point sur la recette") == "point sur la recette"
        assert short_title("Compte rendu de réunion — recette") == "recette"

    def test_a_title_that_says_something_is_left_alone(self):
        from greffier.domain.memory import short_title

        assert short_title("Point sur la recette") == "Point sur la recette"

    def test_a_title_that_is_only_that_prefix_is_kept_rather_than_emptied(self):
        from greffier.domain.memory import short_title

        assert short_title("Compte rendu") == "Compte rendu"


class TestWhatIsRecalled:
    def _trace(self, number: int, decision: str = "On garde jeudi.") -> Trace:
        return Trace(
            identifier=f"2026-09-{number:02d}_reunion",
            title=f"réunion {number}",
            held_on=f"2026-09-{number:02d}",
            people=("Jacques",),
            decisions=(decision,),
        )

    def test_a_meeting_that_left_nothing_is_not_recalled(self):
        nothing = Trace(identifier="2026-09-01_reunion", title="rien")
        assert nothing.empty
        assert recalled([nothing]) == ""

    def test_the_recalled_section_names_the_meeting_and_the_day(self):
        rendered = recalled([self._trace(12)])
        assert "réunion 12" in rendered and "2026-09-12" in rendered

    def test_it_tells_the_writer_not_to_pass_an_old_point_off_as_new(self):
        """The whole risk of recalling: minutes that report what nobody said."""
        rendered = recalled([self._trace(12)])
        assert "jamais un point ancien" in rendered

    def test_it_stops_at_a_meeting_boundary(self):
        """Half a decision recalled is worse than none: nothing says it was cut."""
        long_ones = [self._trace(j, "d" * 400) for j in range(1, 13)]
        rendered = recalled(long_ones, place=1000)
        assert len(rendered) < 1000 + 400
        assert not rendered.rstrip().endswith("d" * 10 + "…")
        assert rendered.count("Décidé") < len(long_ones)

    def test_nothing_at_all_gives_no_section(self):
        assert recalled([]) == ""

    def test_the_room_it_takes_is_bounded(self):
        assert MAXIMUM_REMINDER <= 2_000
