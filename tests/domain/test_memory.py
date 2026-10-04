"""What a meeting leaves for the ones that follow.

The voice bank already carried people from one meeting to the next; what was
decided and what stayed open did not. A second meeting on the same work started
from nothing, and the room said again what it had said the week before.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.memory import MAXIMUM_REMINDER, Trace, recalled, what_the_minutes_left

#: What the writer reads before the meetings themselves, word for word.
RECALLED_HEADER = (
    "[Ce que les réunions précédentes ont laissé]\n"
    "De la plus récente à la plus ancienne. N'y fais référence que si la "
    "réunion en cours y touche, et ne présente jamais un point ancien comme "
    "s'il venait d'être dit :\n"
)

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

    def test_a_heading_with_a_colon_is_the_same_heading(self):
        decisions, _ = what_the_minutes_left("## Décisions :\n\n- On garde jeudi.\n")
        assert decisions == ("On garde jeudi.",)

    def test_star_bullets_are_read_too(self):
        """The writer is a model: its bullets come as it pleases."""
        minutes = "## Décisions\n\n* On garde jeudi.\n* Les utilisateurs sont prévenus.\n"
        decisions, _ = what_the_minutes_left(minutes)
        assert decisions == ("On garde jeudi.", "Les utilisateurs sont prévenus.")

    def test_the_spacing_inside_a_point_is_tidied(self):
        decisions, _ = what_the_minutes_left("## Décisions\n\n- On  garde\tjeudi.\n")
        assert decisions == ("On garde jeudi.",)

    def test_a_point_keeps_its_first_letter_whatever_it_is(self):
        """Only the bullet marks go: a first name starting with X stays whole, even
        when the mark is glued to it.
        """
        decisions, _ = what_the_minutes_left(
            "## Décisions\n\n- Xavier valide les écarts.\n-Xavier prévient Sophie.\n"
        )
        assert decisions == ("Xavier valide les écarts.", "Xavier prévient Sophie.")

    def test_an_indented_bullet_loses_its_mark_like_the_others(self):
        """A sub-list under a decision: the model indents it, and the writer must not
        read « - » as the first word of the point.
        """
        minutes = "## Décisions\n\n- On garde jeudi.\n  - Les utilisateurs sont prévenus.\n"
        decisions, _ = what_the_minutes_left(minutes)
        assert decisions == ("On garde jeudi.", "Les utilisateurs sont prévenus.")


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


class TestHowATraceReads:
    """A few lines the writer can scan, in the words of the minutes themselves."""

    def test_a_full_trace_names_the_day_the_people_and_each_point_on_its_line(self):
        trace = Trace(
            identifier="2026-09-12_recette",
            title="Compte rendu : point sur la recette",
            held_on="2026-09-12",
            people=("Jacques", "Sophie"),
            decisions=("La recette est décalée à jeudi.", "Les utilisateurs seront prévenus."),
            open_points=("Validation des deux anomalies.",),
            documents=("cahier des charges", "planning"),
        )
        assert trace.rendered() == (
            "- point sur la recette (2026-09-12)\n"
            "  Présents : Jacques, Sophie\n"
            "  Décidé : La recette est décalée à jeudi.\n"
            "  Décidé : Les utilisateurs seront prévenus.\n"
            "  Resté ouvert : Validation des deux anomalies.\n"
            "  Documents fournis : cahier des charges, planning"
        )

    def test_a_trace_without_a_day_or_people_says_only_what_it_knows(self):
        trace = Trace(identifier="2026-09-12_recette", title="Compte rendu",
                      decisions=("On garde jeudi.",))
        assert trace.rendered() == "- Compte rendu\n  Décidé : On garde jeudi."

    def test_a_trace_without_a_title_is_named_by_its_identifier(self):
        trace = Trace(identifier="2026-09-12_recette", title="", decisions=("On garde jeudi.",))
        assert trace.rendered() == "- 2026-09-12_recette\n  Décidé : On garde jeudi."


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

    def test_the_section_reads_exactly_as_the_writer_receives_it(self):
        assert recalled([self._trace(12)]) == (
            RECALLED_HEADER
            + "- réunion 12 (2026-09-12)\n"
            "  Présents : Jacques\n"
            "  Décidé : On garde jeudi.\n\n"
        )

    def test_a_meeting_that_exactly_fits_is_recalled_and_in_one_character_less_room_it_is_not(self):
        trace = self._trace(12)
        room = len(trace.rendered()) + 1
        assert recalled([trace], place=room) != ""
        assert recalled([trace], place=room - 1) == ""

    def test_two_meetings_that_exactly_fill_the_room_are_both_recalled(self):
        first, second = self._trace(12), self._trace(11, "On prévient les utilisateurs.")
        room = len(first.rendered()) + 1 + len(second.rendered()) + 1
        assert recalled([first, second], place=room).count("Décidé") == 2
        assert recalled([first, second], place=room - 1).count("Décidé") == 1

    def test_an_empty_meeting_in_between_hides_nothing_older(self):
        nothing = Trace(identifier="2026-09-11_reunion", title="rien")
        rendered = recalled([self._trace(12), nothing, self._trace(10)])
        assert "réunion 12" in rendered and "réunion 10" in rendered

    @given(
        lengths=st.lists(st.integers(1, 60), min_size=1, max_size=4),
        fitting=st.integers(0, 4),
        slack=st.sampled_from([-1, 0, 1]),
    )
    def test_what_is_recalled_is_the_longest_run_of_recent_meetings_that_fits(
        self, lengths: list[int], fitting: int, slack: int
    ):
        """Cut by meeting, from the most recent, and never past the room given.

        The room is set at, one under and one over what the first `fitting`
        meetings take, so that the cut is exercised on both sides of the line.
        """
        traces = [self._trace(j + 1, "d" * n) for j, n in enumerate(lengths)]
        renderings = [trace.rendered() for trace in traces]
        place = len("\n".join(renderings[:min(fitting, len(traces))])) + 1 + slack
        kept = max(
            (n for n in range(len(traces) + 1) if len("\n".join(renderings[:n])) + 1 <= place),
            default=0,
        )
        expected = RECALLED_HEADER + "\n".join(renderings[:kept]) + "\n\n" if kept else ""
        assert recalled(traces, place=place) == expected
