"""Handing the transcript to a player, a browser and a spreadsheet."""

from __future__ import annotations

import csv
import io
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.export import (
    LINE_WIDTH,
    LINES_PER_BLOCK,
    blocks_of,
    rendered,
    sheet,
    srt,
    vtt,
    wrap,
)
from greffier.domain.models import Span, Utterance


def said(start: float, end: float, text: str, voice: str = "v1") -> Utterance:
    return Utterance(span=Span(start, end), text=text, voice=voice)


NAMES = {"v1": "Sophie", "v2": "Julien"}

# Words as a transcriber writes them, letters only so that `split()` gives
# them back whole, and never longer than the narrowest line asked for below.
WORDS = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyzéèàç'", min_size=1, max_size=12),
    min_size=1,
    max_size=40,
)
WIDTHS = st.integers(min_value=12, max_value=60)


class TestCuttingALineForAScreen:
    def test_a_short_turn_stays_one_line(self) -> None:
        assert wrap("D'accord.") == ["D'accord."]

    def test_a_long_turn_is_cut_on_words(self) -> None:
        lines = wrap("La recette est prête, mais la signature électronique "
                       "attend encore le prestataire.")
        assert all(len(line) <= LINE_WIDTH for line in lines)
        assert " ".join(lines) == ("La recette est prête, mais la signature "
                                     "électronique attend encore le prestataire.")

    def test_a_word_longer_than_the_line_is_left_whole(self) -> None:
        # Broken, it is no longer the word that was said.
        address = "https://exemple.test/" + "x" * 60
        assert wrap(f"voir {address}") == ["voir", address]

    def test_nothing_said_is_no_block(self) -> None:
        assert blocks_of([said(0, 1, "   ")]) == []

    @given(words=WORDS, width=WIDTHS)
    def test_a_line_takes_every_word_that_fits_and_not_one_more(
        self, words: list[str], width: int
    ) -> None:
        # Greedy on both sides: a word that still fits is never pushed to the
        # next line, and a line never passes the width by one character.
        lines = wrap(" ".join(words), width)
        assert all(len(line) <= width for line in lines)
        assert " ".join(lines) == " ".join(words)
        for line, following in pairwise(lines):
            assert len(line) + 1 + len(following.split()[0]) > width


class TestSharingATurnBetweenBlocks:
    def test_a_long_turn_becomes_several_blocks_in_order(self) -> None:
        long = " ".join(["mot"] * 60)
        chunks = blocks_of([said(0, 30, long)])
        assert len(chunks) > 1
        assert [b.start for b in chunks] == sorted(b.start for b in chunks)

    def test_the_blocks_cover_the_turn_and_do_not_overlap(self) -> None:
        chunks = blocks_of([said(10, 40, " ".join(["mot"] * 60))])
        assert chunks[0].start == 10
        assert chunks[-1].end == pytest.approx(40, abs=0.01)
        for one, other in pairwise(chunks):
            assert one.end == pytest.approx(other.start)

    def test_a_turn_too_short_for_its_blocks_overruns_rather_than_flashes(self) -> None:
        # Three blocks over two seconds would be unreadable.
        chunks = blocks_of([said(0, 2, " ".join(["mot"] * 60))])
        assert all(b.end - b.start >= 0.2 for b in chunks)
        assert chunks[-1].end > 2

    def test_the_turns_come_out_in_time_order(self) -> None:
        chunks = blocks_of([said(9, 10, "après"), said(1, 2, "avant")])
        assert [b.text for b in chunks] == ["avant", "après"]

    @given(words=WORDS, width=WIDTHS)
    def test_the_blocks_carry_each_wrapped_line_once_two_at_a_time(
        self, words: list[str], width: int
    ) -> None:
        text = " ".join(words)
        chunks = blocks_of([said(0, 10, text)], width=width)
        assert [line for block in chunks for line in block.lines] == wrap(text, width)
        assert all(1 <= len(block.lines) <= LINES_PER_BLOCK for block in chunks)

    def test_a_turn_with_nothing_said_does_not_end_the_subtitles(self) -> None:
        chunks = blocks_of([said(0, 1, "avant"), said(2, 3, "   "), said(4, 5, "après")])
        assert [b.text for b in chunks] == ["avant", "après"]


class TestSubtitlesAPlayerReads:
    def test_the_shape_srt_expects(self) -> None:
        output_ = srt([said(1.5, 3.25, "D'accord.")], NAMES)
        assert output_.startswith("1\n00:00:01,500 --> 00:00:03,250\nSophie : D'accord.")

    def test_the_blocks_are_numbered_from_one_without_a_gap(self) -> None:
        output_ = srt([said(0, 4, "un"), said(5, 9, "deux")], NAMES)
        numbers = [line for line in output_.splitlines() if line.isdigit()]
        assert numbers == ["1", "2"]

    def test_a_voice_nobody_named_carries_no_prefix(self) -> None:
        output_ = srt([said(0, 1, "D'accord.", voice="v9")], NAMES)
        assert output_ == "1\n00:00:00,000 --> 00:00:01,000\nD'accord.\n"

    def test_past_an_hour_the_clock_still_holds(self) -> None:
        assert "01:00:01,000 --> 01:00:02,000" in srt([said(3601, 3602, "encore")], NAMES)

    @given(
        hours=st.integers(min_value=0, max_value=99),
        minutes=st.integers(min_value=0, max_value=59),
        seconds=st.integers(min_value=0, max_value=59),
        thousandths=st.integers(min_value=0, max_value=999),
    )
    def test_the_clock_reads_hours_minutes_seconds_and_thousandths(
        self, hours: int, minutes: int, seconds: int, thousandths: int
    ) -> None:
        moment = hours * 3600 + minutes * 60 + seconds + thousandths / 1000
        timing = srt([said(moment, moment + 1, "oui")]).splitlines()[1]
        expected = f"{hours:02d}:{minutes:02d}:{seconds:02d},{thousandths:03d} -->"
        assert timing.startswith(expected)

    def test_below_a_second_the_thousandths_are_still_written(self) -> None:
        assert "00:00:00,500 --> 00:00:01,900" in srt([said(0.5, 1.9, "oui")])

    def test_a_moment_before_the_recording_began_reads_as_zero(self) -> None:
        # SRT has no negative time: a span placed before zero is clamped
        # rather than refused, and the file still opens.
        assert "00:00:00,000 --> 00:00:01,000" in srt([said(-0.5, 1, "oui")])

    def test_a_millisecond_that_rounds_up_does_not_make_a_thousand(self) -> None:
        assert "00:00:02,000" in srt([said(0, 1.9996, "oui")], NAMES)


class TestSubtitlesABrowserReads:
    def test_it_begins_with_the_word_that_makes_it_a_vtt(self) -> None:
        assert vtt([said(0, 1, "oui")], NAMES).startswith("WEBVTT\n")

    def test_the_clock_uses_a_full_stop(self) -> None:
        assert "00:00:01.500 --> 00:00:03.250" in vtt([said(1.5, 3.25, "oui")], NAMES)

    def test_the_speaker_is_a_tag_and_not_more_text_to_read(self) -> None:
        assert "<v Sophie>oui" in vtt([said(0, 1, "oui")], NAMES)

    def test_the_shape_a_browser_expects(self) -> None:
        # The header, one blank line, then each cue: its timing above its text.
        assert vtt([said(1.5, 3.25, "oui")], NAMES) == (
            "WEBVTT\n\n00:00:01.500 --> 00:00:03.250\n<v Sophie>oui\n"
        )

    def test_a_voice_nobody_named_gets_no_tag(self) -> None:
        assert vtt([said(0, 1, "oui", voice="v9")], NAMES) == (
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\noui\n"
        )


class TestOneLinePerTurnForASpreadsheet:
    def test_the_columns_are_named(self) -> None:
        first_one = sheet([said(0, 1, "oui")], NAMES).splitlines()[0]
        assert first_one == "debut;fin;duree;voix;nom;confiance;texte"

    def test_a_turn_carries_its_times_its_voice_and_its_name(self) -> None:
        lines = list(csv.reader(
            io.StringIO(sheet([said(1, 3.5, "D'accord.")], NAMES)), delimiter=";"
        ))
        assert lines[1] == ["1.00", "3.50", "2.50", "v1", "Sophie", "", "D'accord."]

    def test_a_semicolon_in_what_was_said_does_not_make_a_column(self) -> None:
        lines = list(csv.reader(
            io.StringIO(sheet([said(0, 1, "oui ; non")], NAMES)), delimiter=";"
        ))
        assert lines[1][-1] == "oui ; non"

    def test_the_turns_come_out_in_time_order(self) -> None:
        lines = list(csv.reader(
            io.StringIO(sheet([said(9, 10, "après"), said(1, 2, "avant")])), delimiter=";"
        ))
        assert [line[-1] for line in lines[1:]] == ["avant", "après"]

    def test_a_turn_without_a_voice_leaves_voice_and_name_empty(self) -> None:
        nobody = Utterance(span=Span(0, 1), text="oui")
        lines = list(csv.reader(io.StringIO(sheet([nobody], NAMES)), delimiter=";"))
        assert lines[1][3:5] == ["", ""]

    def test_a_voice_nobody_named_leaves_the_name_column_empty(self) -> None:
        lines = list(csv.reader(
            io.StringIO(sheet([said(0, 1, "oui", voice="v9")], NAMES)), delimiter=";"
        ))
        assert lines[1][3:5] == ["v9", ""]

    def test_the_lines_end_without_a_carriage_return(self) -> None:
        # csv's default is the Windows pair; the file ends its lines the way
        # the subtitles and the minutes do.
        output_ = sheet([said(0, 1, "oui"), said(2, 3, "non")])
        assert "\r" not in output_
        assert output_.endswith("non\n")


class TestAskingForAShape:
    @pytest.mark.parametrize("shape", ["srt", "vtt", "csv"])
    def test_each_known_shape_produces_something(self, shape: str) -> None:
        assert rendered(shape, [said(0, 1, "oui")], NAMES).strip()

    @pytest.mark.parametrize(("shape", "mark"), [
        ("srt", "Sophie : oui"), ("vtt", "<v Sophie>oui"), ("csv", ";v1;Sophie;"),
    ])
    def test_the_names_reach_every_shape(self, shape: str, mark: str) -> None:
        assert mark in rendered(shape, [said(0, 1, "oui")], NAMES)

    def test_an_unknown_shape_says_which_ones_exist(self) -> None:
        expected = r"^format inconnu : docx \(connus : srt, vtt, csv\)$"
        with pytest.raises(ValueError, match=expected):
            rendered("docx", [said(0, 1, "oui")], NAMES)

    def test_a_meeting_with_nothing_said_produces_a_file_all_the_same(self) -> None:
        # A spreadsheet with its header and no row is readable; a crash is not.
        assert sheet([]).strip() == "debut;fin;duree;voix;nom;confiance;texte"
        assert vtt([]).strip() == "WEBVTT"
        assert srt([]) == ""


class TestNamingTheSpeakerWithoutRepeatingOneself:
    def test_a_long_turn_names_its_speaker_once(self) -> None:
        # Five blocks, five « Julien : » is five times the name and four
        # fewer lines of what was actually said.
        output_ = srt([said(0, 30, " ".join(["mot"] * 60), voice="v2")], NAMES)
        assert output_.count("Julien :") == 1

    def test_the_name_comes_back_when_somebody_else_speaks(self) -> None:
        output_ = srt([
            said(0, 2, "un", voice="v1"),
            said(3, 5, "deux", voice="v2"),
            said(6, 8, "trois", voice="v1"),
        ], NAMES)
        assert output_.count("Sophie :") == 2
        assert output_.count("Julien :") == 1

    def test_the_same_speaker_twice_running_is_named_once(self) -> None:
        output_ = srt([
            said(0, 2, "un", voice="v1"), said(3, 5, "et puis deux", voice="v1"),
        ], NAMES)
        assert output_.count("Sophie :") == 1

    def test_the_name_is_counted_in_the_width_of_its_line(self) -> None:
        # « Sophie : » plus forty-two characters is fifty on screen, which is
        # what the line was before this.
        output_ = srt([said(0, 9, "La recette est prête depuis lundi, il manque "
                                  "la signature du prestataire.")], NAMES)
        lines = [
            line for line in output_.splitlines()
            if line and not line.isdigit() and "-->" not in line
        ]
        assert all(len(line) <= LINE_WIDTH for line in lines)

    def test_the_browser_format_keeps_the_name_out_of_the_text(self) -> None:
        output_ = vtt([said(0, 30, " ".join(["mot"] * 60), voice="v2")], NAMES)
        assert output_.count("<v Julien>") == output_.count("-->")
        assert "Julien :" not in output_

    def test_a_voice_nobody_named_leaves_who_empty(self) -> None:
        # Empty rather than None: `who` is a string, and whoever renders a
        # block prints it as it is.
        chunks = blocks_of([said(0, 1, "oui", voice="v9")], NAMES)
        assert chunks[0].who == ""


class TestHowSureTheModelWas:
    def test_the_figure_is_carried_into_the_spreadsheet(self) -> None:
        unsure = Utterance(span=Span(0, 1), text="bailleurs", voice="v1",
                            confidence=0.42)
        lines = list(csv.reader(io.StringIO(sheet([unsure], NAMES)), delimiter=";"))
        assert lines[1][5] == "0.42"

    def test_a_turn_nobody_judged_leaves_the_column_empty(self) -> None:
        # Empty, not zero: no figure is not a low figure, and a spreadsheet
        # would average a zero in.
        lines = list(csv.reader(io.StringIO(sheet([said(0, 1, "oui")])), delimiter=";"))
        assert lines[1][5] == ""
