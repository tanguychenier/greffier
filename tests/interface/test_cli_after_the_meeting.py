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


def _run(settings, *arguments, input=None):
    return runner.invoke(application, [*arguments, "--config", str(settings)], input=input)


def _out(answered):
    return answered.stdout + (answered.stderr or "")


def a_meeting(data, name="2026-09-12_10h00_recette", days_old=0, with_audio=False):
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
            Utterance(span=Span(0.0, 4.0), text="On décale la recette à jeudi."),
            Utterance(span=Span(4.0, 8.0), text="Maud relance le partenaire lundi."),
        ],
        turns=[SpeakerTurn(voice="1", span=Span(0.0, 4.0), source=Source.MIC),
               SpeakerTurn(voice="2", span=Span(4.0, 8.0), source=Source.MIC)],
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
    def test_the_voices_are_listed_with_their_state(self, poste):
        settings, data = poste
        name = a_meeting(data)
        answered = _run(settings, "voix", name)
        assert answered.exit_code == 0, _out(answered)
        assert "Jacques" in answered.stdout
        assert "Maud (à confirmer)" in answered.stdout
        assert "--accepter-propositions" in answered.stdout

    def test_naming_needs_both_the_voice_and_the_name(self, poste):
        settings, data = poste
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--nommer", "2")
        assert answered.exit_code == 2
        assert "--nommer et --nom vont ensemble" in _out(answered)

    def test_a_voice_that_absorbed_nothing_cannot_be_split(self, poste, tmp_path):
        settings, data = poste
        # The voiceprint model is opened before the gesture, and only checked
        # for on opening: an empty file stands for it, splitting reads nothing.
        model = tmp_path / "modeles" / "diarisation" / "nemo_en_titanet_large.onnx"
        model.parent.mkdir(parents=True)
        model.touch()
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--separer", "1")
        assert answered.exit_code == 1
        assert "n'a absorbé aucune autre voix" in _out(answered)

    def test_without_the_voiceprint_model_a_gesture_says_so_not_a_traceback(self, poste):
        settings, data = poste
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--separer", "1")
        assert answered.exit_code == 1
        assert "modèle d'empreintes introuvable" in _out(answered)
        assert "greffier verifier" in _out(answered)

    def test_an_excerpt_of_a_voice_nobody_heard_long_enough(self, poste):
        settings, data = poste
        name = a_meeting(data)
        answered = _run(settings, "voix", name, "--ecouter", "9")
        assert answered.exit_code == 1
        assert "Aucun extrait pour la voix « 9 »" in _out(answered)


class TestWritingTheMinutesAgain:
    def test_without_a_writer_it_says_so(self, poste):
        settings, data = poste
        name = a_meeting(data)
        answered = _run(settings, "rediger", name)
        assert answered.exit_code != 0
        assert "rédacteur" in _out(answered).lower()

    def test_with_a_writer_the_minutes_are_written_from_what_was_kept(
        self, poste, monkeypatch
    ):
        settings, data = poste
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
    def test_without_minutes_there_is_nothing_to_offer_from(self, poste):
        settings, data = poste
        name = a_meeting(data)
        answered = _run(settings, "tickets", name)
        assert answered.exit_code == 1
        assert "Aucun compte rendu" in _out(answered)

    def test_without_a_writer_it_says_so(self, poste):
        settings, data = poste
        name = a_meeting(data)
        minutes_for(data, name)
        answered = _run(settings, "tickets", name)
        assert answered.exit_code == 1
        assert "Aucun rédacteur" in _out(answered)

    def test_the_tickets_are_offered_not_created(self, poste, monkeypatch):
        settings, data = poste
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

    def test_minutes_with_no_action_say_so(self, poste, monkeypatch):
        settings, data = poste
        name = a_meeting(data)
        minutes_for(data, name)
        monkeypatch.setattr(cli, "writer", lambda config: FakeWriter("[]"))
        answered = _run(settings, "tickets", name)
        assert "Aucune action décidée" in answered.stdout


class TestSendingTheMinutes:
    def test_without_minutes_nothing_can_leave(self, poste):
        settings, data = poste
        name = a_meeting(data)
        answered = _run(settings, "envoyer", name, "--a", "maud@example.fr")
        assert answered.exit_code == 1
        assert "Aucun compte rendu" in _out(answered)

    def test_something_that_is_not_an_address_is_refused(self, poste):
        settings, data = poste
        name = a_meeting(data)
        minutes_for(data, name)
        answered = _run(settings, "envoyer", name, "--a", "maud")
        assert answered.exit_code == 1
        assert "n'est pas une adresse" in _out(answered)

    def test_nothing_leaves_without_a_yes(self, poste, monkeypatch):
        settings, data = poste
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

    def test_with_a_yes_it_is_sent_with_its_subject(self, poste, monkeypatch):
        settings, data = poste
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

    def test_a_sender_that_fails_is_reported(self, poste, monkeypatch):
        settings, data = poste
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

    def test_with_no_thread_at_all_it_says_where_it_looked(self, poste):
        settings, data = poste
        answered = _run(settings, "recuperer")
        assert answered.exit_code == 1
        assert "Aucun fil de direct" in _out(answered)

    def test_a_meeting_already_kept_is_not_rebuilt(self, poste):
        settings, data = poste
        name = a_meeting(data)
        self._thread(data, name, [{"genre": "tour", "numero": 1, "debut": 0.0, "fin": 2.0,
                                   "texte": "bonjour", "voix": "v1"}])
        answered = _run(settings, "recuperer", name)
        assert answered.exit_code == 1
        assert "est déjà une réunion" in _out(answered)

    def test_a_thread_with_words_becomes_a_meeting(self, poste):
        settings, data = poste
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

    def test_a_thread_with_no_words_is_no_meeting(self, poste):
        settings, data = poste
        name = "2026-09-12_11h00_vide"
        self._thread(data, name, [{"genre": "annonce", "texte": "Transcription en direct active."}])
        answered = _run(settings, "recuperer", name)
        assert answered.exit_code == 1
        assert "aucune parole" in _out(answered)


class TestTidyingTheRecordings:
    def test_with_nothing_old_there_is_nothing_to_tidy(self, poste):
        settings, data = poste
        a_meeting(data, with_audio=True)
        answered = _run(settings, "ranger")
        assert answered.exit_code == 0, _out(answered)
        assert "Rien à ranger" in answered.stdout

    def test_an_old_recording_is_named_before_anything_is_touched(self, poste, tmp_path):
        settings, data = poste
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

    def test_an_invalid_rule_is_refused_by_name(self, poste):
        settings, data = poste
        settings.write_text(
            settings.read_text(encoding="utf-8")
            + "[retention]\ncompresser_apres_jours = 30\neffacer_apres_jours = 7\n",
            encoding="utf-8",
        )
        answered = _run(settings, "ranger")
        assert answered.exit_code == 1
        assert "règle de rétention invalide" in _out(answered)


class TestPublishingFilesIntoTheTool:
    def test_a_document_is_offered_to_the_context_not_to_the_meetings(self, poste, tmp_path):
        settings, _ = poste
        note = tmp_path / "glossaire.md"
        note.write_text("CASA : le comité d'architecture.\n", encoding="utf-8")
        answered = _run(settings, "deposer", str(note))
        assert answered.exit_code == 0, _out(answered)
        assert "glossaire.md" in answered.stdout
        assert "--faire" in answered.stdout, "nothing is done without it"

    def test_a_missing_file_is_named_and_nothing_else_stops(self, poste, tmp_path):
        settings, _ = poste
        answered = _run(settings, "deposer", str(tmp_path / "absent.wav"))
        assert answered.exit_code == 1
        assert "introuvable" in _out(answered)
