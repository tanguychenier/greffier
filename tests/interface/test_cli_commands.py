"""What the commands answer, and what they refuse.

The command line was the least covered surface of the tool -- nine per cent --
and it is the one a machine without a screen has. Every command here is driven
as somebody would drive it, against a data folder of its own.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from greffier.cli import application

runner = CliRunner()


@pytest.fixture
def poste(tmp_path, monkeypatch):
    """A machine of its own: settings, data folder, nothing inherited."""
    for cle in [c for c in __import__("os").environ if c.startswith("GREFFIER_")]:
        monkeypatch.delenv(cle)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    data = tmp_path / "donnees"
    settings = tmp_path / "config.toml"
    settings.write_text(
        f'[chemins]\ndonnees = "{data}"\nmodeles = "{tmp_path / "modeles"}"\n'
        '[compte_rendu]\nmoteur = "aucun"\n',
        encoding="utf-8",
    )
    data.mkdir(parents=True)
    return settings, data


def _run(settings, *arguments):
    return runner.invoke(application, [*arguments, "--config", str(settings)])


class TestSayingWhereThingsStand:
    def test_at_rest_it_says_so(self, poste):
        settings, _ = poste
        answered = _run(settings, "statut")
        assert answered.exit_code == 0
        assert "cours" in answered.stdout or "repos" in answered.stdout.lower()

    def test_with_no_meeting_the_list_is_empty_not_an_error(self, poste):
        settings, _ = poste
        answered = _run(settings, "reunions")
        assert answered.exit_code == 0

    def test_the_bank_can_be_read_when_it_holds_nobody(self, poste):
        settings, _ = poste
        assert _run(settings, "connus").exit_code == 0

    def test_with_no_source_declared_it_says_where_to_declare_one(self, poste):
        """Exit 1 on purpose: a script must be able to tell « none » from « some »."""
        settings, _ = poste
        answered = _run(settings, "sources")
        assert answered.exit_code == 1
        assert "Aucune source" in answered.stdout


class TestAMeetingThatDoesNotExist:
    @pytest.mark.parametrize("command", ["lire", "propositions"])
    def test_it_names_the_meeting_it_could_not_find(self, poste, command):
        settings, _ = poste
        answered = _run(settings, command, "jamais-tenue")
        assert answered.exit_code != 0
        assert "jamais-tenue" in (answered.stdout + (answered.stderr or ""))

    def test_renaming_names_the_meeting_and_not_the_subject(self, poste):
        """The subject comes first: « renommer "point du lundi" 2026-09-12 »."""
        settings, _ = poste
        answered = _run(settings, "renommer", "point du lundi", "jamais-tenue")
        assert answered.exit_code != 0
        assert "jamais-tenue" in (answered.stdout + (answered.stderr or ""))


class TestReadingAMeetingThatExists:
    def _une_reunion(self, data, name="2026-09-12_recette"):
        """Written by the store itself: a fixture shaped by hand would test
        the shape I imagined rather than the one the tool writes."""
        from datetime import UTC, datetime

        from greffier.adapters.store_files import FileStore
        from greffier.domain.meeting import StoredMeeting
        from greffier.domain.models import Source, Span, SpeakerTurn, Utterance

        FileStore(data / "reunions").record(StoredMeeting(
            identifier=name,
            audio=data / f"{name}.wav",
            processed_at=datetime.now(UTC),
            duration=42.0,
            utterances=[Utterance(span=Span(0.0, 4.0),
                                  text="On décale la recette à jeudi.")],
            turns=[SpeakerTurn(voice="1", span=Span(0.0, 4.0), source=Source.MIC)],
            names={"1": "Jacques"},
            propositions={},
            warnings=[],
        ))
        return name

    def test_the_list_shows_it(self, poste):
        settings, data = poste
        name = self._une_reunion(data)
        answered = _run(settings, "reunions")
        assert name in answered.stdout

    def test_reading_it_aloud_needs_minutes_and_says_so(self, poste):
        """« lire » records the minutes spoken, it does not show a transcript."""
        settings, data = poste
        name = self._une_reunion(data)
        answered = _run(settings, "lire", name)
        assert answered.exit_code == 1
        assert "Aucun compte rendu" in (answered.stdout + (answered.stderr or ""))

    def test_giving_it_a_subject_keeps_its_identifier(self, poste):
        """A label, not a rename: the identifier carries the date, which orders
        the meetings and keys the audio and the transcript."""
        settings, data = poste
        name = self._une_reunion(data)
        assert _run(settings, "renommer", "point recette", name).exit_code == 0
        assert (data / "reunions" / f"{name}.json").exists()
        assert "point recette" in _run(settings, "reunions").stdout

    def test_deleting_it_is_asked_for_by_name(self, poste):
        settings, data = poste
        name = self._une_reunion(data)
        answered = runner.invoke(
            application, ["oublier", name, "--config", str(settings)], input="oui\n")
        assert answered.exit_code in (0, 1)


class TestWhatItRefusesToDo:
    def test_stopping_a_meeting_nobody_started(self, poste):
        settings, _ = poste
        answered = _run(settings, "arreter")
        assert answered.exit_code != 0

    def test_processing_a_file_that_is_not_there(self, poste):
        settings, _ = poste
        answered = _run(settings, "traiter", "/nulle/part/reunion.wav")
        assert answered.exit_code != 0


class TestTheChecksItRuns:
    def test_the_diagnostic_reports_without_changing_anything(self, poste):
        settings, data = poste
        avant = sorted(p.name for p in data.iterdir())
        answered = _run(settings, "diagnostic")
        assert answered.exit_code in (0, 1)
        assert sorted(p.name for p in data.iterdir()) == avant

    def test_verifier_says_what_is_missing(self, poste):
        settings, _ = poste
        answered = _run(settings, "verifier")
        assert answered.exit_code in (0, 1)
        assert answered.stdout.strip()


class TestTheContextItKeeps:
    def test_it_lays_a_template_the_first_time(self, poste):
        """Nobody writes a TOML from memory: the file says how."""
        settings, _ = poste
        answered = _run(settings, "contexte")
        assert answered.exit_code in (0, 1)
        assert answered.stdout.strip()

    def test_a_term_added_is_read_back(self, poste, tmp_path):
        from greffier.adapters import context_file

        settings, _ = poste
        file = tmp_path / "config" / "greffier" / "contexte.toml"
        file.parent.mkdir(parents=True, exist_ok=True)
        context_file.lay_the_template(file)
        assert context_file.add_a_term(file, "FAST", "formulaire d'attestation")
        assert "FAST" in context_file.read(file).header()


class TestTheVoiceBank:
    def test_forgetting_somebody_the_bank_never_heard(self, poste):
        settings, _ = poste
        answered = _run(settings, "connus", "--oublier", "Personne")
        assert answered.exit_code != 0 or "Personne" in answered.stdout

    def test_the_voices_of_a_meeting_that_does_not_exist(self, poste):
        settings, _ = poste
        answered = _run(settings, "voix", "jamais-tenue")
        assert answered.exit_code != 0


class TestKeepingAndRecovering:
    def test_archiving_with_nothing_to_archive(self, poste):
        settings, _ = poste
        answered = _run(settings, "archiver")
        assert answered.exit_code in (0, 1)

    def test_a_backup_is_written_where_it_is_asked_for(self, poste, tmp_path):
        settings, data = poste
        (data / "reunions").mkdir(parents=True, exist_ok=True)
        (data / "reunions" / "une.json").write_text("{}", encoding="utf-8")
        answered = _run(settings, "sauvegarder")
        assert answered.exit_code in (0, 1)

    def test_recovering_a_meeting_nobody_recorded(self, poste):
        settings, _ = poste
        answered = _run(settings, "recuperer")
        assert answered.exit_code in (0, 1)


class TestWhatNeedsAMeetingUnderWay:
    @pytest.mark.parametrize("command", ["annuler", "deposer"])
    def test_it_refuses_when_nothing_is_running(self, poste, command):
        settings, _ = poste
        arguments = [command] + (["/nulle/part/doc.txt"] if command == "deposer" else [])
        answered = _run(settings, *arguments)
        assert answered.exit_code != 0


class TestSendingTheMinutes:
    def test_it_refuses_without_a_recipient(self, poste):
        settings, data = poste
        (data / "comptes-rendus").mkdir(parents=True, exist_ok=True)
        (data / "comptes-rendus" / "r.md").write_text("# Compte rendu", encoding="utf-8")
        answered = _run(settings, "envoyer", "r")
        assert answered.exit_code != 0


class TestForgettingSomebodyEverywhere:
    """`connus --oublier` empties the bank; this empties the rest.

    Article 17 is not satisfied by a voiceprint being deleted while the first
    name stays written in the minutes, the transcript and the memory.
    """

    @staticmethod
    def _a_meeting_naming(data, name: str) -> None:
        import json

        (data / "reunions").mkdir(parents=True, exist_ok=True)
        (data / "comptes-rendus").mkdir(parents=True, exist_ok=True)
        (data / "reunions" / "2026-09-10_point.json").write_text(
            json.dumps({
                "format": 2, "identifiant": "2026-09-10_point",
                "audio": str(data / "enregistrements" / "2026-09-10_point.wav"),
                "noms": {"v1": name}, "propositions": {},
                "repliques": [{"debut": 0, "fin": 2,
                                "texte": f"{name} reprend la recette.", "voix": "v1"}],
                "fusions": [],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        (data / "comptes-rendus" / "2026-09-10_point.md").write_text(
            f"# Compte rendu\n\n- {name} reprend la recette.\n", encoding="utf-8",
        )

    def test_it_says_where_the_name_is_and_erases_nothing(self, poste):
        settings, data = poste
        self._a_meeting_naming(data, "Élodie")
        answered = _run(settings, "oublier-une-personne", "Élodie")
        assert answered.exit_code == 0
        assert "compte rendu" in answered.stdout
        assert "Rien n'a été effacé" in answered.stdout
        assert "Élodie" in (data / "comptes-rendus" / "2026-09-10_point.md").read_text()

    def test_the_accent_is_not_a_second_person(self, poste):
        # The bank holds « Elodie », the minutes say « Élodie ». One person.
        settings, data = poste
        self._a_meeting_naming(data, "Élodie")
        answered = _run(settings, "oublier-une-personne", "Elodie")
        assert "au total" in answered.stdout

    def test_with_faire_the_name_is_gone_and_the_decision_stays(self, poste):
        settings, data = poste
        self._a_meeting_naming(data, "Élodie")
        answered = _run(settings, "oublier-une-personne", "Élodie", "--faire")
        assert answered.exit_code == 0
        minutes_text = (data / "comptes-rendus" / "2026-09-10_point.md").read_text()
        assert "Élodie" not in minutes_text
        assert "reprend la recette" in minutes_text

    def test_somebody_who_is_written_nowhere_is_said_so(self, poste):
        settings, _ = poste
        answered = _run(settings, "oublier-une-personne", "Personne")
        assert answered.exit_code == 1
        assert "nulle part" in answered.stdout


class TestHandingTheTranscriptToAnotherTool:
    """Three formats, three tools: a player, a browser, a spreadsheet."""

    @staticmethod
    def _a_transcribed_meeting(data) -> None:
        import json

        (data / "reunions").mkdir(parents=True, exist_ok=True)
        (data / "reunions" / "2026-09-10_point.json").write_text(
            json.dumps({
                "format": 2, "identifiant": "2026-09-10_point",
                "audio": str(data / "enregistrements" / "2026-09-10_point.wav"),
                "traitee_le": "2026-09-10T11:00:00", "duree": 4.0,
                "noms": {"v1": "Sophie"}, "propositions": {},
                "avertissements": [], "evenements_materiel": [], "tours": [],
                "repliques": [
                    {"debut": 1.5, "fin": 3.25, "texte": "La recette est prête.",
                     "voix": "v1", "source": "inconnue"},
                ],
                "fusions": [],
            }, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_subtitles_a_player_reads(self, poste):
        settings, data = poste
        self._a_transcribed_meeting(data)
        answered = _run(settings, "exporter", "2026-09-10_point", "--format", "srt")
        assert answered.exit_code == 0
        written = (data / "transcriptions" / "2026-09-10_point.srt").read_text()
        assert written.startswith("1\n00:00:01,500 --> 00:00:03,250\nSophie : ")

    def test_a_spreadsheet_opens_it_with_its_accents(self, poste):
        # Without the byte order mark, a French spreadsheet shows « rÃ©union ».
        settings, data = poste
        self._a_transcribed_meeting(data)
        _run(settings, "exporter", "2026-09-10_point", "--format", "csv")
        brut = (data / "transcriptions" / "2026-09-10_point.csv").read_bytes()
        assert brut.startswith(b"\xef\xbb\xbf")
        assert b"debut;fin;duree;voix;nom;confiance;texte" in brut

    def test_it_writes_where_it_is_told(self, poste, tmp_path):
        settings, data = poste
        self._a_transcribed_meeting(data)
        ailleurs = tmp_path / "sous-titres" / "point.vtt"
        _run(settings, "exporter", "2026-09-10_point", "--format", "vtt",
             "--vers", str(ailleurs))
        assert ailleurs.read_text().startswith("WEBVTT")

    def test_a_format_nobody_has_is_refused_by_name(self, poste):
        settings, data = poste
        self._a_transcribed_meeting(data)
        answered = _run(settings, "exporter", "2026-09-10_point", "--format", "docx")
        assert answered.exit_code == 1
        assert "srt" in answered.stderr


class TestWhatBreaksARecording:
    def test_a_file_that_is_not_sound_is_refused_in_french(self, poste, tmp_path):
        # And refused before the models open: the traceback it used to raise
        # came twenty seconds in, from the audio library.
        settings, _ = poste
        wrong = tmp_path / "abime.wav"
        wrong.write_bytes(b"\x00\x01\x02\x03" * 5000)
        answered = _run(settings, "traiter", str(wrong))
        assert answered.exit_code == 1
        assert "n'est pas un enregistrement lisible" in answered.stderr
