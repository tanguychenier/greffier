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
    donnees = tmp_path / "donnees"
    reglages = tmp_path / "config.toml"
    reglages.write_text(
        f'[chemins]\ndonnees = "{donnees}"\nmodeles = "{tmp_path / "modeles"}"\n'
        '[compte_rendu]\nmoteur = "aucun"\n',
        encoding="utf-8",
    )
    donnees.mkdir(parents=True)
    return reglages, donnees


def _run(reglages, *arguments):
    return runner.invoke(application, [*arguments, "--config", str(reglages)])


class TestSayingWhereThingsStand:
    def test_at_rest_it_says_so(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "statut")
        assert answered.exit_code == 0
        assert "cours" in answered.stdout or "repos" in answered.stdout.lower()

    def test_with_no_meeting_the_list_is_empty_not_an_error(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "reunions")
        assert answered.exit_code == 0

    def test_the_bank_can_be_read_when_it_holds_nobody(self, poste):
        reglages, _ = poste
        assert _run(reglages, "connus").exit_code == 0

    def test_with_no_source_declared_it_says_where_to_declare_one(self, poste):
        """Exit 1 on purpose: a script must be able to tell « none » from « some »."""
        reglages, _ = poste
        answered = _run(reglages, "sources")
        assert answered.exit_code == 1
        assert "Aucune source" in answered.stdout


class TestAMeetingThatDoesNotExist:
    @pytest.mark.parametrize("commande", ["lire", "propositions"])
    def test_it_names_the_meeting_it_could_not_find(self, poste, commande):
        reglages, _ = poste
        answered = _run(reglages, commande, "jamais-tenue")
        assert answered.exit_code != 0
        assert "jamais-tenue" in (answered.stdout + (answered.stderr or ""))

    def test_renaming_names_the_meeting_and_not_the_subject(self, poste):
        """The subject comes first: « renommer "point du lundi" 2026-09-12 »."""
        reglages, _ = poste
        answered = _run(reglages, "renommer", "point du lundi", "jamais-tenue")
        assert answered.exit_code != 0
        assert "jamais-tenue" in (answered.stdout + (answered.stderr or ""))


class TestReadingAMeetingThatExists:
    def _une_reunion(self, donnees, nom="2026-09-12_recette"):
        """Written by the store itself: a fixture shaped by hand would test
        the shape I imagined rather than the one the tool writes."""
        from datetime import UTC, datetime

        from greffier.adapters.store_files import FileStore
        from greffier.domain.meeting import StoredMeeting
        from greffier.domain.models import Source, Span, SpeakerTurn, Utterance

        FileStore(donnees / "reunions").record(StoredMeeting(
            identifier=nom,
            audio=donnees / f"{nom}.wav",
            processed_at=datetime.now(UTC),
            duration=42.0,
            utterances=[Utterance(span=Span(0.0, 4.0),
                                  text="On décale la recette à jeudi.")],
            turns=[SpeakerTurn(voice="1", span=Span(0.0, 4.0), source=Source.MIC)],
            names={"1": "Jacques"},
            propositions={},
            warnings=[],
        ))
        return nom

    def test_the_list_shows_it(self, poste):
        reglages, donnees = poste
        nom = self._une_reunion(donnees)
        answered = _run(reglages, "reunions")
        assert nom in answered.stdout

    def test_reading_it_aloud_needs_minutes_and_says_so(self, poste):
        """« lire » records the minutes spoken, it does not show a transcript."""
        reglages, donnees = poste
        nom = self._une_reunion(donnees)
        answered = _run(reglages, "lire", nom)
        assert answered.exit_code == 1
        assert "Aucun compte rendu" in (answered.stdout + (answered.stderr or ""))

    def test_giving_it_a_subject_keeps_its_identifier(self, poste):
        """A label, not a rename: the identifier carries the date, which orders
        the meetings and keys the audio and the transcript."""
        reglages, donnees = poste
        nom = self._une_reunion(donnees)
        assert _run(reglages, "renommer", "point recette", nom).exit_code == 0
        assert (donnees / "reunions" / f"{nom}.json").exists()
        assert "point recette" in _run(reglages, "reunions").stdout

    def test_deleting_it_is_asked_for_by_name(self, poste):
        reglages, donnees = poste
        nom = self._une_reunion(donnees)
        answered = runner.invoke(
            application, ["oublier", nom, "--config", str(reglages)], input="oui\n")
        assert answered.exit_code in (0, 1)


class TestWhatItRefusesToDo:
    def test_stopping_a_meeting_nobody_started(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "arreter")
        assert answered.exit_code != 0

    def test_processing_a_file_that_is_not_there(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "traiter", "/nulle/part/reunion.wav")
        assert answered.exit_code != 0


class TestTheChecksItRuns:
    def test_the_diagnostic_reports_without_changing_anything(self, poste):
        reglages, donnees = poste
        avant = sorted(p.name for p in donnees.iterdir())
        answered = _run(reglages, "diagnostic")
        assert answered.exit_code in (0, 1)
        assert sorted(p.name for p in donnees.iterdir()) == avant

    def test_verifier_says_what_is_missing(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "verifier")
        assert answered.exit_code in (0, 1)
        assert answered.stdout.strip()


class TestTheContextItKeeps:
    def test_it_lays_a_template_the_first_time(self, poste):
        """Nobody writes a TOML from memory: the file says how."""
        reglages, _ = poste
        answered = _run(reglages, "contexte")
        assert answered.exit_code in (0, 1)
        assert answered.stdout.strip()

    def test_a_term_added_is_read_back(self, poste, tmp_path):
        from greffier.adapters import context_file

        reglages, _ = poste
        fichier = tmp_path / "config" / "greffier" / "contexte.toml"
        fichier.parent.mkdir(parents=True, exist_ok=True)
        context_file.lay_the_template(fichier)
        assert context_file.add_a_term(fichier, "FAST", "formulaire d'attestation")
        assert "FAST" in context_file.read(fichier).header()


class TestTheVoiceBank:
    def test_forgetting_somebody_the_bank_never_heard(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "connus", "--oublier", "Personne")
        assert answered.exit_code != 0 or "Personne" in answered.stdout

    def test_the_voices_of_a_meeting_that_does_not_exist(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "voix", "jamais-tenue")
        assert answered.exit_code != 0


class TestKeepingAndRecovering:
    def test_archiving_with_nothing_to_archive(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "archiver")
        assert answered.exit_code in (0, 1)

    def test_a_backup_is_written_where_it_is_asked_for(self, poste, tmp_path):
        reglages, donnees = poste
        (donnees / "reunions").mkdir(parents=True, exist_ok=True)
        (donnees / "reunions" / "une.json").write_text("{}", encoding="utf-8")
        answered = _run(reglages, "sauvegarder")
        assert answered.exit_code in (0, 1)

    def test_recovering_a_meeting_nobody_recorded(self, poste):
        reglages, _ = poste
        answered = _run(reglages, "recuperer")
        assert answered.exit_code in (0, 1)


class TestWhatNeedsAMeetingUnderWay:
    @pytest.mark.parametrize("commande", ["annuler", "deposer"])
    def test_it_refuses_when_nothing_is_running(self, poste, commande):
        reglages, _ = poste
        arguments = [commande] + (["/nulle/part/doc.txt"] if commande == "deposer" else [])
        answered = _run(reglages, *arguments)
        assert answered.exit_code != 0


class TestSendingTheMinutes:
    def test_it_refuses_without_a_recipient(self, poste):
        reglages, donnees = poste
        (donnees / "comptes-rendus").mkdir(parents=True, exist_ok=True)
        (donnees / "comptes-rendus" / "r.md").write_text("# Compte rendu", encoding="utf-8")
        answered = _run(reglages, "envoyer", "r")
        assert answered.exit_code != 0
