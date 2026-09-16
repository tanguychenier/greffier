"""Handing the transcript to a player, a browser and a spreadsheet."""

from __future__ import annotations

import csv
import io

import pytest

from greffier.domain.export import (
    LINE_WIDTH,
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


class TestCuttingALineForAScreen:
    def test_a_short_turn_stays_one_line(self) -> None:
        assert wrap("D'accord.") == ["D'accord."]

    def test_a_long_turn_is_cut_on_words(self) -> None:
        lignes = wrap("La recette est prête, mais la signature électronique "
                       "attend encore le prestataire.")
        assert all(len(line) <= LINE_WIDTH for line in lignes)
        assert " ".join(lignes) == ("La recette est prête, mais la signature "
                                     "électronique attend encore le prestataire.")

    def test_a_word_longer_than_the_line_is_left_whole(self) -> None:
        # Broken, it is no longer the word that was said.
        adresse = "https://exemple.test/" + "x" * 60
        assert wrap(f"voir {adresse}") == ["voir", adresse]

    def test_nothing_said_is_no_block(self) -> None:
        assert blocks_of([said(0, 1, "   ")]) == []


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
        for one, other in zip(chunks, chunks[1:], strict=False):
            assert one.end == pytest.approx(other.start)

    def test_a_turn_too_short_for_its_blocks_overruns_rather_than_flashes(self) -> None:
        # Three blocks over two seconds would be unreadable.
        chunks = blocks_of([said(0, 2, " ".join(["mot"] * 60))])
        assert all(b.end - b.start >= 0.2 for b in chunks)
        assert chunks[-1].end > 2

    def test_the_turns_come_out_in_time_order(self) -> None:
        chunks = blocks_of([said(9, 10, "après"), said(1, 2, "avant")])
        assert [b.text for b in chunks] == ["avant", "après"]


class TestSubtitlesAPlayerReads:
    def test_the_shape_srt_expects(self) -> None:
        output_ = srt([said(1.5, 3.25, "D'accord.")], NAMES)
        assert output_.startswith("1\n00:00:01,500 --> 00:00:03,250\nSophie : D'accord.")

    def test_the_blocks_are_numbered_from_one_without_a_gap(self) -> None:
        output_ = srt([said(0, 4, "un"), said(5, 9, "deux")], NAMES)
        numeros = [line for line in output_.splitlines() if line.isdigit()]
        assert numeros == ["1", "2"]

    def test_a_voice_nobody_named_carries_no_prefix(self) -> None:
        assert "Sophie" not in srt([said(0, 1, "D'accord.", voice="v9")], NAMES)

    def test_past_an_hour_the_clock_still_holds(self) -> None:
        assert "01:00:01,000" in srt([said(3601, 3602, "encore")], NAMES)

    def test_a_millisecond_that_rounds_up_does_not_make_a_thousand(self) -> None:
        assert "00:00:02,000" in srt([said(0, 1.9996, "oui")], NAMES)


class TestSubtitlesABrowserReads:
    def test_it_begins_with_the_word_that_makes_it_a_vtt(self) -> None:
        assert vtt([said(0, 1, "oui")], NAMES).startswith("WEBVTT\n")

    def test_the_clock_uses_a_full_stop(self) -> None:
        assert "00:00:01.500 --> 00:00:03.250" in vtt([said(1.5, 3.25, "oui")], NAMES)

    def test_the_speaker_is_a_tag_and_not_more_text_to_read(self) -> None:
        assert "<v Sophie>oui" in vtt([said(0, 1, "oui")], NAMES)


class TestOneLinePerTurnForASpreadsheet:
    def test_the_columns_are_named(self) -> None:
        first_one = sheet([said(0, 1, "oui")], NAMES).splitlines()[0]
        assert first_one == "debut;fin;duree;voix;nom;confiance;texte"

    def test_a_turn_carries_its_times_its_voice_and_its_name(self) -> None:
        lignes = list(csv.reader(
            io.StringIO(sheet([said(1, 3.5, "D'accord.")], NAMES)), delimiter=";"
        ))
        assert lignes[1] == ["1.00", "3.50", "2.50", "v1", "Sophie", "", "D'accord."]

    def test_a_semicolon_in_what_was_said_does_not_make_a_column(self) -> None:
        lignes = list(csv.reader(
            io.StringIO(sheet([said(0, 1, "oui ; non")], NAMES)), delimiter=";"
        ))
        assert lignes[1][-1] == "oui ; non"


class TestAskingForAShape:
    @pytest.mark.parametrize("shape", ("srt", "vtt", "csv"))
    def test_each_known_shape_produces_something(self, shape: str) -> None:
        assert rendered(shape, [said(0, 1, "oui")], NAMES).strip()

    def test_an_unknown_shape_says_which_ones_exist(self) -> None:
        with pytest.raises(ValueError, match="srt"):
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
        lignes = [
            line for line in output_.splitlines()
            if line and not line.isdigit() and "-->" not in line
        ]
        assert all(len(line) <= LINE_WIDTH for line in lignes)

    def test_the_browser_format_keeps_the_name_out_of_the_text(self) -> None:
        output_ = vtt([said(0, 30, " ".join(["mot"] * 60), voice="v2")], NAMES)
        assert output_.count("<v Julien>") == output_.count("-->")
        assert "Julien :" not in output_


class TestHowSureTheModelWas:
    def test_the_figure_is_carried_into_the_spreadsheet(self) -> None:
        peu_sur = Utterance(span=Span(0, 1), text="bailleurs", voice="v1",
                            confidence=0.42)
        lignes = list(csv.reader(io.StringIO(sheet([peu_sur], NAMES)), delimiter=";"))
        assert lignes[1][5] == "0.42"

    def test_a_turn_nobody_judged_leaves_the_column_empty(self) -> None:
        # Empty, not zero: no figure is not a low figure, and a spreadsheet
        # would average a zero in.
        lignes = list(csv.reader(io.StringIO(sheet([said(0, 1, "oui")])), delimiter=";"))
        assert lignes[1][5] == ""
