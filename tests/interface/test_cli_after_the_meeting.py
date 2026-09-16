"""The commands that work on a meeting already kept, driven as a person would.

The writer and the sender are doubled where the command reaches for them:
what is covered is the command, its refusals and its messages, not the model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from greffier import cli
from greffier.cli import application

runner = CliRunner()


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine of its own: settings, data folder, nothing inherited."""
    for the_key in [c for c in __import__("os").environ if c.startswith("GREFFIER_")]:
        monkeypatch.delenv(the_key)
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


def _run(settings, *arguments, input=None):
    return runner.invoke(application, [*arguments, "--config", str(settings)], input=input)


def _out(answered):
    return answered.stdout + (answered.stderr or "")


def a_meeting(data, name="2026-09-12_10h00_recette", days_old=0, with_audio=False,
              turn_length=4.0):
    """Written by the store itself, the shape the tool writes."""
    from greffier.adapters.store_files import FileStore
    from greffier.domain.meeting import StoredMeeting
    from greffier.domain.models import Source, Span, SpeakerTurn, Utterance

    audio = data / "enregistrements" / f"{name}.wav"
    if with_audio:
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"RIFF" + b"\0" * 4000)
    FileStore(data / "reunions").record(StoredMeeting(
        identifier=name,
        audio=audio,
        processed_at=datetime.now(UTC) - timedelta(days=days_old),
        duration=42.0,
        utterances=[
            Utterance(span=Span(0.0, turn_length), text="On décale la recette à jeudi."),
            Utterance(span=Span(turn_length, 2 * turn_length),
                      text="Maud relance le partenaire lundi."),
        ],
        turns=[SpeakerTurn(voice="1", span=Span(0.0, turn_length), source=Source.MIC),
               SpeakerTurn(voice="2", span=Span(turn_length, 2 * turn_length),
                           source=Source.MIC)],
        names={"1": "Jacques"},
        propositions={"2": "Maud"},
        warnings=[],
    ))
    return name


def minutes_for(data, name, text="# Compte rendu : recette\n\n## Décisions\n\n- Recette jeudi.\n"):
    folder = data / "comptes-rendus"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(text, encoding="utf-8")
    return folder / f"{name}.md"


class FakeWriter:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def write_up(self, text):
        self.asked.append(text)
        return self.answer


class TestTheVoicesOfAMeeting:
    def test_the_voices_are_listed_with_their_state(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "voix", name)
        assert answered.exit_code == 0, _out(answered)
        assert "Jacques" in answered.stdout
        assert "Maud (à confirmer)" in answered.stdout
        assert "--accepter-propositions" in answered.stdout

    def test_naming_needs_both_the_voice_and_the_name(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--nommer", "2")
        assert answered.exit_code == 2
        assert "--nommer et --nom vont ensemble" in _out(answered)

    def test_a_voice_that_absorbed_nothing_cannot_be_split(self, machine, tmp_path):
        settings, data = machine
        # The voiceprint model is opened before the gesture, and only checked
        # for on opening: an empty file stands for it, splitting reads nothing.
        model = tmp_path / "modeles" / "diarisation" / "nemo_en_titanet_large.onnx"
        model.parent.mkdir(parents=True)
        model.touch()
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--separer", "1")
        assert answered.exit_code == 1
        assert "n'a absorbé aucune autre voix" in _out(answered)

    def test_without_the_voiceprint_model_a_gesture_says_so_not_a_traceback(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--separer", "1")
        assert answered.exit_code == 1
        assert "modèle d'empreintes introuvable" in _out(answered)
        assert "greffier verifier" in _out(answered)

    def test_an_excerpt_of_a_voice_nobody_heard_long_enough(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--ecouter", "9")
        assert answered.exit_code == 1
        assert "Aucun extrait pour la voix « 9 »" in _out(answered)


class TestWritingTheMinutesAgain:
    def test_without_a_writer_it_says_so(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "rediger", name)
        assert answered.exit_code != 0
        assert "rédacteur" in _out(answered).lower()

    def test_with_a_writer_the_minutes_are_written_from_what_was_kept(
        self, machine, monkeypatch
    ):
        settings, data = machine
        name = a_meeting(data)
        writer = FakeWriter("# Compte rendu : recette\n\n## Décisions\n\n- Jeudi.\n")
        monkeypatch.setattr(cli, "writer", lambda config: writer)
        answered = _run(settings, "rediger", name)
        assert answered.exit_code == 0, _out(answered)
        assert (data / "comptes-rendus" / f"{name}.md").read_text(encoding="utf-8").startswith(
            "# Compte rendu"
        )
        assert "On décale la recette à jeudi" in writer.asked[0]
        assert "Jacques" in writer.asked[0], "the names given follow the voices"


class TestTheTicketsOffered:
    def test_without_minutes_there_is_nothing_to_offer_from(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "tickets", name)
        assert answered.exit_code == 1
        assert "Aucun compte rendu" in _out(answered)

    def test_without_a_writer_it_says_so(self, machine):
        settings, data = machine
        name = a_meeting(data)
        minutes_for(data, name)
        answered = _run(settings, "tickets", name)
        assert answered.exit_code == 1
        assert "Aucun rédacteur" in _out(answered)

    def test_the_tickets_are_offered_not_created(self, machine, monkeypatch):
        settings, data = machine
        name = a_meeting(data)
        minutes_for(data, name)
        writer = FakeWriter(json.dumps([
            {"titre": "Relancer le partenaire", "assigne": "Maud", "echeance": "lundi"},
        ]))
        monkeypatch.setattr(cli, "writer", lambda config: writer)
        answered = _run(settings, "tickets", name)
        assert answered.exit_code == 0, _out(answered)
        assert "Relancer le partenaire" in answered.stdout
        assert "Maud · lundi" in answered.stdout
        written = (data / "tickets" / f"{name}.md").read_text(encoding="utf-8")
        assert "pas créés" in written

    def test_minutes_with_no_action_say_so(self, machine, monkeypatch):
        settings, data = machine
        name = a_meeting(data)
        minutes_for(data, name)
        monkeypatch.setattr(cli, "writer", lambda config: FakeWriter("[]"))
        answered = _run(settings, "tickets", name)
        assert "Aucune action décidée" in answered.stdout


class TestSendingTheMinutes:
    def test_without_minutes_nothing_can_leave(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "envoyer", name, "--a", "maud@example.fr")
        assert answered.exit_code == 1
        assert "Aucun compte rendu" in _out(answered)

    def test_something_that_is_not_an_address_is_refused(self, machine):
        settings, data = machine
        name = a_meeting(data)
        minutes_for(data, name)
        answered = _run(settings, "envoyer", name, "--a", "maud")
        assert answered.exit_code == 1
        assert "n'est pas une adresse" in _out(answered)

    def test_nothing_leaves_without_a_yes(self, machine, monkeypatch):
        settings, data = machine
        name = a_meeting(data)
        minutes_for(data, name)
        sent = []

        class Sender:
            def send(self, *arguments):
                sent.append(arguments)

        monkeypatch.setattr("greffier.wiring._sender", lambda config, require_recipient: Sender())
        answered = _run(settings, "envoyer", name, "--a", "maud@example.fr", input="n\n")
        assert answered.exit_code == 0
        assert "Rien n'a été envoyé" in answered.stdout
        assert sent == []

    def test_with_a_yes_it_is_sent_with_its_subject(self, machine, monkeypatch):
        settings, data = machine
        name = a_meeting(data)
        minutes_for(data, name)
        sent = []

        class Sender:
            def send(self, target, subject, body, pieces):
                sent.append((target, subject, pieces))

        monkeypatch.setattr("greffier.wiring._sender", lambda config, require_recipient: Sender())
        answered = _run(settings, "envoyer", name, "--a", "maud@example.fr", "--oui")
        assert answered.exit_code == 0, _out(answered)
        assert sent and sent[0][0] == "maud@example.fr"
        assert "recette" in sent[0][1].lower()
        assert "Décisions" in answered.stdout, "the sections are shown before sending"

    def test_a_sender_that_fails_is_reported(self, machine, monkeypatch):
        settings, data = machine
        name = a_meeting(data)
        minutes_for(data, name)

        class Sender:
            def send(self, *arguments):
                raise RuntimeError("serveur injoignable")

        monkeypatch.setattr("greffier.wiring._sender", lambda config, require_recipient: Sender())
        answered = _run(settings, "envoyer", name, "--a", "maud@example.fr", "--oui")
        assert answered.exit_code == 1
        assert "serveur injoignable" in _out(answered)


class TestRecoveringAMeetingFromItsThread:
    def _thread(self, data, name, lines):
        folder = data / "direct"
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / f"{name}.jsonl"
        log.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                       encoding="utf-8")
        return log

    def test_with_no_thread_at_all_it_says_where_it_looked(self, machine):
        settings, data = machine
        answered = _run(settings, "recuperer")
        assert answered.exit_code == 1
        assert "Aucun fil de direct" in _out(answered)

    def test_a_meeting_already_kept_is_not_rebuilt(self, machine):
        settings, data = machine
        name = a_meeting(data)
        self._thread(data, name, [{"genre": "tour", "numero": 1, "debut": 0.0, "fin": 2.0,
                                   "texte": "bonjour", "voix": "v1"}])
        answered = _run(settings, "recuperer", name)
        assert answered.exit_code == 1
        assert "est déjà une réunion" in _out(answered)

    def test_a_thread_with_words_becomes_a_meeting(self, machine):
        settings, data = machine
        name = "2026-09-12_11h00_perdue"
        self._thread(data, name, [
            {"genre": "tour", "numero": 1, "debut": 0.0, "fin": 3.0,
             "texte": "On décale la recette à jeudi prochain.", "voix": "v1", "nom": "Jacques"},
            {"genre": "tour", "numero": 2, "debut": 3.0, "fin": 6.0,
             "texte": "Maud relance le partenaire lundi.", "voix": "v2"},
        ])
        answered = _run(settings, "recuperer", name)
        assert answered.exit_code == 0, _out(answered)
        assert "reconstruite" in answered.stdout
        assert (data / "reunions" / f"{name}.json").exists()
        assert "« greffier rediger »" in answered.stdout

    def test_a_thread_with_no_words_is_no_meeting(self, machine):
        settings, data = machine
        name = "2026-09-12_11h00_vide"
        self._thread(data, name, [{"genre": "annonce", "texte": "Transcription en direct active."}])
        answered = _run(settings, "recuperer", name)
        assert answered.exit_code == 1
        assert "aucune parole" in _out(answered)


class TestTidyingTheRecordings:
    def test_with_nothing_old_there_is_nothing_to_tidy(self, machine):
        settings, data = machine
        a_meeting(data, with_audio=True)
        answered = _run(settings, "ranger")
        assert answered.exit_code == 0, _out(answered)
        assert "Rien à ranger" in answered.stdout

    def test_an_old_recording_is_named_before_anything_is_touched(self, machine, tmp_path):
        settings, data = machine
        settings.write_text(
            settings.read_text(encoding="utf-8")
            + "[retention]\ncompresser_apres_jours = 7\neffacer_apres_jours = 30\n",
            encoding="utf-8",
        )
        name = a_meeting(data, days_old=60, with_audio=True)
        answered = _run(settings, "ranger")
        assert answered.exit_code == 0, _out(answered)
        assert name in answered.stdout
        assert "seraient libérés" in answered.stdout
        assert (data / "enregistrements" / f"{name}.wav").exists(), "nothing touched"

    def test_an_invalid_rule_is_refused_by_name(self, machine):
        settings, data = machine
        settings.write_text(
            settings.read_text(encoding="utf-8")
            + "[retention]\ncompresser_apres_jours = 30\neffacer_apres_jours = 7\n",
            encoding="utf-8",
        )
        answered = _run(settings, "ranger")
        assert answered.exit_code == 1
        assert "règle de rétention invalide" in _out(answered)


class TestPublishingFilesIntoTheTool:
    def test_a_document_is_offered_to_the_context_not_to_the_meetings(self, machine, tmp_path):
        settings, _ = machine
        note = tmp_path / "glossaire.md"
        note.write_text("CASA : le comité d'architecture.\n", encoding="utf-8")
        answered = _run(settings, "deposer", str(note))
        assert answered.exit_code == 0, _out(answered)
        assert "glossaire.md" in answered.stdout
        assert "--faire" in answered.stdout, "nothing is done without it"

    def test_a_missing_file_is_named_and_nothing_else_stops(self, machine, tmp_path):
        settings, _ = machine
        answered = _run(settings, "deposer", str(tmp_path / "absent.wav"))
        assert answered.exit_code == 1
        assert "introuvable" in _out(answered)


def a_wav(path, seconds=2.0):
    """A real, silent wav: the command reads its header before anything heavy."""
    import numpy as np
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(int(16000 * seconds), dtype="int16"), 16000)
    return path


class TestProcessingARecording:
    """The chain is doubled: what is covered is the command around it, what
    it says of the voices, the names, the files written."""

    def _chain(self, monkeypatch, outcome_of):
        class Chain:
            writer = object()
            sender = None
            log = None

            def run_chain(self, audio, send=True, hardware_events=None, started_at=None,
                          ended_at=None):
                return outcome_of(audio)

        monkeypatch.setattr(cli, "wire_up", lambda config: Chain())

    def test_a_file_that_is_not_sound_is_refused_before_the_models(self, machine, tmp_path):
        settings, _ = machine
        not_sound = tmp_path / "notes.wav"
        not_sound.write_text("ceci n'est pas du son", encoding="utf-8")
        answered = _run(settings, "traiter", str(not_sound))
        assert answered.exit_code == 1
        assert "n'est pas un enregistrement lisible" in _out(answered)

    def test_the_voices_are_named_and_the_files_said(self, machine, tmp_path, monkeypatch):
        from greffier.application.process import Outcome
        from greffier.domain.models import Span, SpeakerTurn, Utterance

        settings, data = machine
        audio = a_wav(tmp_path / "2026-09-12_10h00_recette.wav")

        def outcome_of(path):
            outcome = Outcome(audio=path)
            outcome.utterances = [Utterance(Span(0, 30), "on décale la recette à jeudi", "1"),
                                  Utterance(Span(30, 60), "maud relance lundi", "2")]
            outcome.turns = [SpeakerTurn(Span(0, 30), "1"), SpeakerTurn(Span(30, 60), "2")]
            outcome.names = {"1": "Jacques"}
            outcome.propositions = {"2": "Maud"}
            outcome.warnings = ["Ton micro est resté muet une minute."]
            outcome.transcript_written = data / "transcriptions" / "x.txt"
            outcome.minutes_written = data / "comptes-rendus" / "x.md"
            return outcome

        self._chain(monkeypatch, outcome_of)
        answered = _run(settings, "traiter", str(audio), "--sans-envoi")
        assert answered.exit_code == 0, _out(answered)
        assert "⚠ Ton micro est resté muet" in answered.stdout
        assert "9 mots · 2 voix" in answered.stdout
        assert "Jacques" in answered.stdout
        assert "≈ Maud (à confirmer)" in answered.stdout
        assert "greffier voix 2026-09-12_10h00_recette" in answered.stdout
        assert "Compte rendu  :" in answered.stdout

    def test_a_chain_that_stops_says_why(self, machine, tmp_path, monkeypatch):
        from greffier.application.process import ChainStopped
        from greffier.domain.models import Phase

        settings, _ = machine
        audio = a_wav(tmp_path / "vide.wav")

        def outcome_of(path):
            raise ChainStopped(Phase.FAILURE, "Transcription quasi vide (3 mots).")

        self._chain(monkeypatch, outcome_of)
        answered = _run(settings, "traiter", str(audio))
        assert answered.exit_code == 1
        assert "Transcription quasi vide" in _out(answered)

    def test_during_a_meeting_it_refuses_unless_told_otherwise(
        self, machine, tmp_path, monkeypatch
    ):
        from greffier.application.record import RecorderState
        from greffier.domain.models import Phase

        settings, data = machine
        audio = a_wav(tmp_path / "autre.wav")
        state = RecorderState(phase=Phase.RECORDING, name="reunion", pid=1)
        monkeypatch.setattr("greffier.application.record.Recording.read", lambda self: state)
        answered = _run(settings, "traiter", str(audio))
        assert answered.exit_code == 1
        assert "quand-meme" in _out(answered) or "en cours" in _out(answered)


class TestTheAssemblyOfNotablePassages:
    def test_with_too_little_speech_there_is_no_assembly(self, machine):
        settings, data = machine
        name = a_meeting(data)
        answered = _run(settings, "montage", name, "--minutes", "0.05")
        assert answered.exit_code == 1
        assert "Pas assez de parole" in _out(answered)

    def test_the_passages_are_cut_from_the_recording(self, machine, monkeypatch):
        settings, data = machine
        name = a_meeting(data, with_audio=True, turn_length=30.0)
        cut = []
        monkeypatch.setattr(
            "greffier.application.render.assemble",
            lambda audio, passages, destination: cut.append((audio, passages, destination))
            or destination,
        )
        answered = _run(settings, "montage", name, "--minutes", "1")
        assert answered.exit_code == 0, _out(answered)
        assert cut and cut[0][2].name == f"{name}.m4a"
        assert "passages" in answered.stdout


class TestWhatTheToolKnowsOfTheSetting:
    def test_the_first_call_lays_the_file_and_says_so(self, machine):
        settings, _ = machine
        answered = _run(settings, "contexte")
        assert answered.exit_code == 0, _out(answered)
        assert "Fichier de contexte créé" in answered.stdout
        assert "Amorce de transcription" in answered.stdout

    def test_a_term_and_a_person_added_are_shown_with_the_prompt(self, machine):
        from greffier.adapters import context_file
        from greffier.adapters.configuration import Config

        settings, _ = machine
        _run(settings, "contexte")
        config = Config.load(settings)
        context_file.add_a_term(config.paths.context, "CASA", "comité d'architecture")
        context_file.add_a_person(config.paths.context, "Maud Riel", "présidente")
        answered = _run(settings, "contexte")
        assert "CASA" in answered.stdout
        assert "Maud Riel" in answered.stdout
        assert "2 terme(s), 1 personne(s)" in answered.stdout, "the template's own term counts"


class TestCreatingTheTicketsOffered:
    """The adapters existed and nothing called them: the tickets were offered
    in a file and typed again by hand. Only a source in writing, only with
    its token, never without a yes for each one."""

    def _registry(self, settings, right="écriture"):
        from greffier.adapters.configuration import Config

        config = Config.load(settings)
        config.paths.sources.parent.mkdir(parents=True, exist_ok=True)
        config.paths.sources.write_text(
            '[[sources]]\nnom = "recherche"\ngenre = "gitlab"\n'
            'adresse = "https://gitlab.example.fr"\nprojet = "equipe/outil"\n'
            f'droit = "{right}"\njeton = "GREFFIER_JETON_D_ESSAI"\n',
            encoding="utf-8",
        )

    def _offered(self, data, monkeypatch):
        name = a_meeting(data)
        minutes_for(data, name)
        writer = FakeWriter(json.dumps([
            {"titre": "Relancer le partenaire", "assigne": "Maud", "extrait": "on relance lundi"},
            {"titre": "Décaler la recette", "description": "à jeudi"},
        ]))
        monkeypatch.setattr(cli, "writer", lambda config: writer)
        return name

    def test_a_source_nobody_registered_is_refused_by_name(self, machine, monkeypatch):
        settings, data = machine
        name = self._offered(data, monkeypatch)
        answered = _run(settings, "tickets", name, "--creer", "suivi")
        assert answered.exit_code == 1
        assert "aucune source inscrite sous « suivi »" in _out(answered)

    def test_a_source_in_reading_only_creates_nothing(self, machine, monkeypatch):
        settings, data = machine
        name = self._offered(data, monkeypatch)
        self._registry(settings, right="lecture")
        answered = _run(settings, "tickets", name, "--creer", "recherche")
        assert answered.exit_code == 1
        assert "lecture seule" in _out(answered)

    def test_without_a_token_it_says_where_the_token_goes(self, machine, monkeypatch):
        settings, data = machine
        name = self._offered(data, monkeypatch)
        self._registry(settings)
        monkeypatch.delenv("GREFFIER_JETON_D_ESSAI", raising=False)
        answered = _run(settings, "tickets", name, "--creer", "recherche")
        assert answered.exit_code == 1
        assert "aucun jeton" in _out(answered) and "Sources d'entreprise" in _out(answered)

    def test_each_ticket_needs_its_own_yes(self, machine, monkeypatch):
        from greffier.adapters import gitlab_api

        settings, data = machine
        name = self._offered(data, monkeypatch)
        self._registry(settings)
        monkeypatch.setenv("GREFFIER_JETON_D_ESSAI", "secret")
        created = []

        def create(source, token, title, description=""):
            created.append((title, description))
            return gitlab_api.Ticket(len(created), title, "opened",
                                     f"https://gitlab.example.fr/i/{len(created)}")

        monkeypatch.setattr(gitlab_api, "create_a_ticket", create)
        answered = _run(settings, "tickets", name, "--creer", "recherche", input="y\nn\n")
        assert answered.exit_code == 0, _out(answered)
        assert [title for title, _ in created] == ["Relancer le partenaire"]
        assert "Extrait du compte rendu" in created[0][1]
        assert "✓ créé : https://gitlab.example.fr/i/1" in answered.stdout
        assert "1 ticket(s) créé(s), 1 laissé(s)" in answered.stdout

    def test_a_refusal_from_the_source_is_said_and_the_rest_goes_on(self, machine, monkeypatch):
        from greffier.adapters import gitlab_api

        settings, data = machine
        name = self._offered(data, monkeypatch)
        self._registry(settings)
        monkeypatch.setenv("GREFFIER_JETON_D_ESSAI", "secret")

        def refuses(source, token, title, description=""):
            raise gitlab_api.GitLabRefused("jeton refusé sur « recherche » (403)")

        monkeypatch.setattr(gitlab_api, "create_a_ticket", refuses)
        answered = _run(settings, "tickets", name, "--creer", "recherche", input="y\ny\n")
        assert answered.exit_code == 0
        assert _out(answered).count("jeton refusé") == 2
        assert "0 ticket(s) créé(s), 2 laissé(s)" in answered.stdout

    def test_without_the_option_nothing_is_created(self, machine, monkeypatch):
        from greffier.adapters import gitlab_api

        settings, data = machine
        name = self._offered(data, monkeypatch)
        self._registry(settings)
        monkeypatch.setenv("GREFFIER_JETON_D_ESSAI", "secret")
        monkeypatch.setattr(gitlab_api, "create_a_ticket",
                            lambda *a, **k: pytest.fail("created without being asked"))
        answered = _run(settings, "tickets", name)
        assert answered.exit_code == 0
