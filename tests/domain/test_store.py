"""Sorting a file handed over: what it is, and what can be done with it.

Treating everything the same way would produce a catch-all that organises
nothing. A two-hour video sorted wrongly costs a transcription for nothing;
a document sorted as a meeting produces minutes of a text nobody spoke.
"""

import re
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greffier.domain.store import (
    MINIMUM_SOUND_SIZE,
    SOUNDS,
    TEXTS,
    TOOLED_TEXTS,
    VIDEOS,
    Destination,
    offer,
    summarise,
)

ALL = frozenset({"ffmpeg", "pdftotext", "textutil"})

#: Every suffix the store knows, a few it does not, and none at all.
any_suffix = st.sampled_from(
    [*sorted(SOUNDS | VIDEOS | TEXTS | TOOLED_TEXTS), ".csv", ".zip", ".WAV", ".Mp4", ""]
)
any_file = st.builds(
    lambda stem, suffix: Path(stem + suffix),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyzéè0123456789-_", min_size=1, max_size=12),
    any_suffix,
)
some_tools = st.frozensets(st.sampled_from(sorted(ALL)))
a_size = st.one_of(st.none(), st.integers(min_value=0, max_value=10**9))

#: mutmut 3 runs pytest twice in one process, the coverage pass then the
#: mutant, so a test method meets two `self` instances. Hypothesis fails it
#: for that alone, in 0.05 s, and the mutant dies of the health check rather
#: than of the rule: 49 false kills on this module before this line.
in_one_process = settings(suppress_health_check=[HealthCheck.differing_executors])


class TestSounds:
    def test_a_recording_becomes_a_meeting(self):
        propose = offer(Path("reunion.wav"), 50_000_000, ALL)
        assert propose.destination is Destination.MEETING
        assert propose.feasible
        assert propose.because == "enregistrement sonore"

    def test_the_common_formats_are_recognised(self):
        for the_suffix in (".wav", ".m4a", ".mp3", ".opus", ".flac"):
            assert offer(
                Path(f"x{the_suffix}"), 50_000_000, ALL
            ).destination is Destination.MEETING

    def test_too_short_a_sound_is_not_a_meeting(self):
        """Une notification système, un bip, un extrait."""
        propose = offer(Path("bip.wav"), MINIMUM_SOUND_SIZE - 1, ALL)
        assert propose.destination is Destination.UNKNOWN
        assert "trop court" in propose.because

    def test_a_sound_of_exactly_the_minimum_size_is_a_meeting(self):
        propose = offer(Path("court.wav"), MINIMUM_SOUND_SIZE, ALL)
        assert propose.destination is Destination.MEETING

    def test_too_short_a_sound_says_its_size_in_kilobytes(self):
        """103 000 bytes are 100.6 KiB: a figure that rounds to 101 only
        when the divisor is 1 024, so a wrong unit shows in the text."""
        propose = offer(Path("bip.wav"), 103_000, ALL)
        assert propose.because == "son trop court pour une réunion (101 Ko)"

    def test_the_threshold_stays_low(self):
        """A one-minute meeting already weighs 2 MB as WAV."""
        assert 50_000 <= MINIMUM_SOUND_SIZE <= 2_000_000


class TestVideos:
    def test_a_teams_recording_is_recognised(self):
        propose = offer(Path("Teams-2026-09-09.mp4"), 800_000_000, ALL)
        assert propose.destination is Destination.VIDEO
        assert propose.feasible
        assert propose.because == (
            "vidéo : la piste sonore sera extraite, l'image ne sert à rien ici"
        )

    def test_what_is_missing_is_named_rather_than_the_file_dropped(self):
        """Saying « ffmpeg would be needed » is more useful than making it vanish."""
        propose = offer(Path("x.mp4"), 10_000_000, frozenset())
        assert propose.destination is Destination.VIDEO
        assert not propose.feasible
        assert propose.blocked_by == "ffmpeg est introuvable"


class TestDocumentsToFile:
    def test_a_text_reads_with_nothing_installed(self):
        propose = offer(Path("compte-rendu.md"), 4_000, frozenset())
        assert propose.destination is Destination.CONTEXT
        assert propose.feasible, "aucun outil n'est requis"
        assert propose.because == "texte lisible tel quel"

    def test_a_pdf_asks_for_pdftotext(self):
        propose = offer(Path("x.pdf"), 2_000_000, frozenset())
        assert propose.destination is Destination.CONTEXT
        assert propose.because == "document pdf : son texte sera extrait"
        assert propose.blocked_by == "pdftotext est introuvable"
        assert offer(Path("x.pdf"), 2_000_000, frozenset({"pdftotext"})).feasible

    def test_an_office_document_asks_for_textutil(self):
        propose = offer(Path("x.docx"), 40_000, frozenset())
        assert propose.because == "document docx : son texte sera extrait"
        assert propose.blocked_by == "textutil est introuvable"
        assert offer(Path("x.docx"), 40_000, frozenset({"textutil"})).feasible


class TestWhatCannotBeFiled:
    def test_a_data_export_is_called_unknown(self):
        propose = offer(Path("export.csv"), 10_000, ALL)
        assert propose.destination is Destination.UNKNOWN
        assert propose.because == (
            "« .csv » n'est ni un son, ni une vidéo, ni un document texte"
        )

    def test_a_file_with_no_extension(self):
        propose = offer(Path("machin"), 1_000, ALL)
        assert propose.destination is Destination.UNKNOWN
        assert propose.because == (
            "« sans extension » n'est ni un son, ni une vidéo, ni un document texte"
        )

    def test_the_unknown_is_never_feasible(self):
        assert not offer(Path("x.zip"), 1_000, ALL).feasible


class TestWhateverTheFile:
    @in_one_process
    @given(file=any_file, size=a_size, tools=some_tools)
    def test_the_suggestion_is_about_the_file_handed_over(self, file, size, tools):
        """The window drops several files at once: each verdict has to name
        the file it judges, or the person cannot tell which one is refused."""
        assert offer(file, size, tools).file == file



class TestTheSummaryOfABatch:
    def test_it_says_what_the_batch_will_become(self):
        propositions = [
            offer(Path("a.wav"), 50_000_000, ALL),
            offer(Path("b.mp4"), 50_000_000, ALL),
            offer(Path("c.md"), 4_000, ALL),
        ]
        assert summarise(propositions) == "1 réunion, 1 vidéo, 1 contexte"

    def test_two_files_of_a_kind_are_counted_in_the_plural(self):
        propositions = [
            offer(Path("a.wav"), 50_000_000, ALL),
            offer(Path("b.mp4"), 50_000_000, ALL),
            offer(Path("c.wav"), 50_000_000, ALL),
        ]
        assert summarise(propositions) == "2 réunions, 1 vidéo"

    def test_context_is_the_folder_the_files_go_to_and_takes_no_plural(self):
        propositions = [offer(Path("a.md"), 4_000, ALL), offer(Path("b.txt"), 4_000, ALL)]
        assert summarise(propositions) == "2 contexte"

    def test_it_flags_what_is_waiting_for_a_tool(self):
        sentence = summarise([offer(Path("a.mp4"), 50_000_000, frozenset())])
        assert sentence == "1 vidéo, dont 1 en attente d'un outil"

    def test_nothing_waits_when_every_tool_is_there(self):
        sentence = summarise([offer(Path("a.mp4"), 50_000_000, ALL)])
        assert "attente" not in sentence

    def test_an_empty_batch_says_so(self):
        assert summarise([]) == "Aucun fichier."

    @in_one_process
    @given(files=st.lists(any_file, min_size=1, max_size=12), tools=some_tools)
    def test_the_counts_add_up_to_the_batch(self, files, tools):
        """The sentence is read before approving: every file has to be in
        one of its figures, and the files held back have to be told apart."""
        propositions = [offer(file, 50_000_000, tools) for file in files]
        sentence = summarise(propositions)
        counted = re.findall(r"(\d+) (?:réunion|vidéo|contexte|inconnu)s?(?:,|$)", sentence)
        assert sum(int(figure) for figure in counted) == len(files)
        held_back = sum(1 for p in propositions if p.blocked_by)
        if held_back:
            assert sentence.endswith(f", dont {held_back} en attente d'un outil")
        else:
            assert "dont" not in sentence

    @in_one_process
    @given(how_many=st.integers(min_value=2, max_value=40))
    def test_the_plural_mark_appears_from_two_on(self, how_many):
        propositions = [offer(Path(f"{i}.wav"), 50_000_000, ALL) for i in range(how_many)]
        assert summarise(propositions) == f"{how_many} réunions"

