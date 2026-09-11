"""La chaîne de traitement, jouée avec des doublures.

Aucun audio, aucun modèle, aucun réseau : on vérifie l'enchaînement et les
garde-fous, pas whisper. Les doublures tiennent en quelques lignes parce que les
ports sont des `Protocol` — rien à hériter.
"""

import subprocess
from pathlib import Path

import pytest

from greffier.application.process import (
    MOTS_MINIMUM,
    Chain,
    ChainStopped,
)
from greffier.domain.models import Person, Phase, Span, SpeakerTurn, Utterance

AUDIO = Path("/tmp/reunion.wav")


class FakeRecorder:
    def __init__(self, levels=(-30.0, -35.0)):
        self._levels = list(levels)
        self.prepares = []

    def start_recording(self, destination):
        return 4242

    def stop_recording(self, processus):
        pass

    def prepare_transcript(self, audio, destination):
        # Le double ne normalise rien : il rend l'audio tel quel, ce qui suffit
        # à vérifier que la chaîne transcrit bien ce qu'on lui a préparé.
        self.prepares.append(audio)
        return audio

    def wire_up(self, chunks, destination):
        return destination

    def levels(self, audio):
        return self._levels


class FakeTranscriber:
    def __init__(self, utterances):
        self.utterances = utterances
        self.amorce_recue = None

    def transcribe(self, audio, language, prompt_seed):
        self.amorce_recue = prompt_seed
        return list(self.utterances)


class FakeDiariser:
    def __init__(self, turns):
        self._turns = turns

    def segment(self, audio, people):
        return list(self._turns)


class FakeWriter:
    def __init__(self):
        self.recu = None

    def write_up(self, transcription):
        self.recu = transcription
        return "# Compte rendu\n\nTout va bien."


class FakeSender:
    def __init__(self):
        self.envois = []

    def send(self, recipient, subject, corps, pieces):
        self.envois.append((recipient, subject, corps))


class FakeStateLog:
    def __init__(self):
        self.phases = []

    def publish(self, phase, message=""):
        self.phases.append(phase)


def utterance(start, end, text):
    return Utterance(span=Span(start, end), text=text)


def turn(start, end, voice):
    return SpeakerTurn(span=Span(start, end), voice=voice)


BAVARDAGE = [
    utterance(0, 5, "Bonjour à tous, moi c'est Tanguy, on commence par le point recette."),
    utterance(6, 12, "La recette est décalée à jeudi, il reste deux anomalies bloquantes."),
    utterance(13, 20, "Merci Tanguy. De mon côté le déploiement est prêt depuis lundi."),
    utterance(21, 28, "On valide donc jeudi, et on prévient les utilisateurs mercredi soir."),
]
TURNS = [turn(0, 12, "1"), turn(13, 20, "2"), turn(21, 28, "1")]


def chain(**overrides):
    defauts = dict(
        audio_recorder=FakeRecorder(),
        transcriber=FakeTranscriber(BAVARDAGE),
        diariser=FakeDiariser(TURNS),
        writer=FakeWriter(),
    )
    defauts.update(overrides)
    return Chain(**defauts)


class TestTheGuardRails:
    def test_a_silent_recording_stops_everything(self):
        """Le bug du 2026-08-20 : sans ça, un CR était fabriqué puis envoyé."""
        processing = chain(audio_recorder=FakeRecorder(levels=(-120.0, -120.0)))
        with pytest.raises(ChainStopped) as stop:
            processing.run_chain(AUDIO)
        assert stop.value.phase is Phase.ECHEC
        assert "muet" in stop.value.because

    def test_an_empty_transcription_is_not_written_up(self):
        transcriber = FakeTranscriber([utterance(0, 2, "Bonjour.")])
        writer = FakeWriter()
        processing = chain(transcriber=transcriber, writer=writer)
        with pytest.raises(ChainStopped, match="quasi vide"):
            processing.run_chain(AUDIO)
        assert writer.recu is None, "le rédacteur ne doit pas être appelé"

    def test_a_count_of_people_the_audio_contradicts_is_flagged(self):
        """Annoncer un nombre force exactement autant de groupes, en silence.

        Le 2026-09-09, « 4 participants » traînait dans la configuration d'un
        poste et la réunion en comptait davantage : deux personnes ont été
        confondues sans que rien ne le dise.
        """
        processing = chain()
        processing.people = 9
        outcome = processing.run_chain(AUDIO)
        assert any("9 participants sont annoncés" in a for a in outcome.warnings)

    def test_a_count_that_fits_says_nothing(self):
        processing = chain()
        processing.people = len(chain().run_chain(AUDIO).significant_voices())
        outcome = processing.run_chain(AUDIO)
        assert not any("annoncés" in a for a in outcome.warnings)

    def test_with_no_count_given_there_is_nothing_to_contradict(self):
        outcome = chain().run_chain(AUDIO)
        assert not any("annoncés" in a for a in outcome.warnings)

    def test_the_word_threshold_stays_low_but_not_zero(self):
        assert 0 < MOTS_MINIMUM <= 50

    def test_a_silent_mic_warns_without_blocking(self):
        processing = chain(audio_recorder=FakeRecorder(levels=(-120.0, -30.0)))
        outcome = processing.run_chain(AUDIO)
        assert any("micro" in a for a in outcome.warnings)
        assert outcome.minutes

    def test_no_system_sound_warns_without_blocking(self):
        processing = chain(audio_recorder=FakeRecorder(levels=(-30.0, -120.0)))
        outcome = processing.run_chain(AUDIO)
        assert any("système" in a for a in outcome.warnings)


class TestTheChainOfPhases:
    def test_the_phases_follow_one_another(self):
        log = FakeStateLog()
        chain(log=log).run_chain(AUDIO)
        assert log.phases[0] == Phase.TRANSCRIPTION.value
        assert Phase.LOCUTEURS.value in log.phases
        assert log.phases[-1] == Phase.TERMINE.value

    def test_the_vocabulary_reaches_the_transcriber(self):
        transcriber = FakeTranscriber(BAVARDAGE)
        processing = chain(transcriber=transcriber)
        processing.prompt_seed = "Vocabulaire : Copernic."
        processing.run_chain(AUDIO)
        assert transcriber.amorce_recue == "Vocabulaire : Copernic."

    def test_with_no_writer_the_transcription_is_still_there(self):
        outcome = chain(writer=None).run_chain(AUDIO)
        assert outcome.utterances and outcome.minutes == ""

    def test_the_sending_happens_only_with_a_recipient(self):
        sender = FakeSender()
        processing = chain(sender=sender)
        assert processing.run_chain(AUDIO).envoye is False
        processing.recipient = "moi@exemple.fr"
        assert processing.run_chain(AUDIO).envoye is True
        assert sender.envois[0][0] == "moi@exemple.fr"

    def test_it_can_process_without_sending(self):
        sender = FakeSender()
        processing = chain(sender=sender)
        processing.recipient = "moi@exemple.fr"
        outcome = processing.run_chain(AUDIO, send=False)
        assert outcome.minutes and not outcome.envoye and not sender.envois


class TestGivingTheVoicesTheirNames:
    def test_every_utterance_gets_the_dominant_voice(self):
        outcome = chain().run_chain(AUDIO)
        assert [r.voice for r in outcome.utterances] == ["1", "1", "2", "1"]

    def test_introducing_oneself_names_the_speaker(self):
        """« moi c'est Tanguy » désigne celui qui parle."""
        outcome = chain().run_chain(AUDIO)
        assert outcome.names["1"] == "Tanguy"

    def test_the_trade_vocabulary_is_not_taken_for_a_first_name(self):
        transcriber = FakeTranscriber([
            utterance(0, 6, "Merci Copernic pour la démonstration de ce matin, c'était clair."),
            utterance(7, 14, "On enchaîne sur le sujet suivant, à savoir la reprise des données."),
            utterance(15, 22, "Très bien, je note que la reprise démarre la semaine prochaine."),
        ])
        processing = chain(transcriber=transcriber)
        processing.not_first_names = frozenset({"copernic"})
        outcome = processing.run_chain(AUDIO)
        assert "Copernic" not in outcome.names.values()
        assert "Copernic" not in outcome.propositions.values()

    def test_the_rendered_transcription_carries_names_and_times(self):
        writer = FakeWriter()
        chain(writer=writer).run_chain(AUDIO)
        assert "[Tanguy]" in writer.recu
        assert "00:00" in writer.recu
        # Une voix sans nom reste identifiée, jamais inventée.
        assert "[Personne 2]" in writer.recu


class FakeExtractor:
    """Rend une empreinte par intervalle, dictée par la voix attendue."""

    def __init__(self, vectors):
        self.vectors = vectors
        self.appels = []

    def extract_spans(self, audio, intervalles):
        from greffier.domain.voiceprints import normalise

        self.appels.append(list(intervalles))
        # Un vecteur par intervalle, et non celui du premier appliqué à tous :
        # le vrai extracteur lit chaque extrait. Les rendre solidaires faisait
        # passer un appel groupé pour une seule et même voix.
        return [
            normalise(self.vectors[(i.start, i.end)], source_duration=i.duration)
            for i in intervalles
        ]


class FakeBank:
    def __init__(self, people):
        self._people = people
        self.ajouts = []

    def people(self):
        return list(self._people)

    def record(self, name, voiceprint):
        self.ajouts.append(name)


class TestTheVoiceBank:
    def test_a_known_voice_is_named_without_anyone_naming_it(self):
        """Le cœur du besoin : « Josiane » et non « Personne 2 »."""
        from greffier.domain.voiceprints import normalise

        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        bank = FakeBank([Person("Josiane", [normalise([0.02, 1.0, 0.0])])])
        processing = chain(extractor=FakeExtractor(vectors), bank=bank)
        outcome = processing.run_chain(AUDIO)
        assert outcome.names["2"] == "Josiane"

    def test_a_disagreement_between_bank_and_meeting_is_flagged(self):
        """La banque a été validée par un humain : elle prime, mais on le dit."""
        from greffier.domain.voiceprints import normalise

        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        bank = FakeBank([Person("Marcel", [normalise([1.0, 0.02, 0.0])])])
        processing = chain(extractor=FakeExtractor(vectors), bank=bank)
        outcome = processing.run_chain(AUDIO)
        assert outcome.names["1"] == "Marcel"
        assert any("Marcel" in a and "Tanguy" in a for a in outcome.warnings)

    def test_an_empty_bank_gets_in_the_way_of_nothing(self):
        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        processing = chain(extractor=FakeExtractor(vectors), bank=FakeBank([]))
        assert processing.run_chain(AUDIO).names["1"] == "Tanguy"


class TestReadingTheOutcome:
    def test_fragments_are_not_participants(self):
        """La segmentation laisse une traîne de fragments d'une seconde."""
        outcome = chain().run_chain(AUDIO)
        outcome.turns = outcome.turns + [turn(29, 29.5, "bruit")]
        assert "bruit" in outcome.speaking_time()
        assert "bruit" not in outcome.significant_voices()

    def test_speaking_time_runs_from_the_most_talkative_down(self):
        outcome = chain().run_chain(AUDIO)
        durees = list(outcome.speaking_time().values())
        assert durees == sorted(durees, reverse=True)


class TestHowMuchToTrustIt:
    def test_the_coverage_says_what_is_missing(self):
        """25 s de texte sur 28 s de parole : seules les respirations manquent."""
        outcome = chain().run_chain(AUDIO)
        assert outcome.coverage == pytest.approx(25 / 28, abs=0.01)

    def test_a_hole_in_the_transcription_is_spotted(self):
        transcriber = FakeTranscriber([
            utterance(0, 10, "On commence par le point sur la recette de la semaine."),
            utterance(120, 130, "Voilà, je crois qu'on a fait le tour des sujets prévus."),
        ])
        diariser = FakeDiariser([turn(0, 10, "1"), turn(120, 130, "2")])
        outcome = chain(transcriber=transcriber, diariser=diariser).run_chain(AUDIO)
        gaps = outcome.gaps(minimum=8)
        assert any(t.duration > 100 for t in gaps)

    def test_the_writer_is_warned_of_what_is_missing(self):
        """Sans cet en-tête, le compte rendu présente comme complet un texte
        qui ne l'est pas."""
        from greffier.application.render import reliability_header

        transcriber = FakeTranscriber([
            utterance(0, 10, "On commence par le point sur la recette de la semaine."),
            utterance(120, 130, "Voilà, je crois qu'on a fait le tour des sujets prévus."),
        ])
        diariser = FakeDiariser([turn(0, 10, "1"), turn(120, 130, "2")])
        writer = FakeWriter()
        chain(transcriber=transcriber, diariser=diariser,
               writer=writer).run_chain(AUDIO)
        assert "Fiabilité de la transcription" in writer.recu
        assert "ne comble" in writer.recu
        assert reliability_header(chain().run_chain(AUDIO)) == "", \
            "une transcription complète ne doit pas être affublée d'un avertissement"


class TestTheContextHeader:
    """La date de la réunion, dite au rédacteur.

    Sans elle, le rédacteur prend la date du traitement : une réunion du 25
    s'est retrouvée datée du 26 dans un compte rendu réel.
    """

    def test_the_date_and_time_come_from_the_file_name(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-08-25_14h33_reunion-essai-reel")
        assert "25 août 2026" in header
        assert "14 h 33" in header

    def test_the_writer_is_asked_not_to_use_today_s_date(self) -> None:
        from greffier.application.render import context_header

        assert "jamais celle du jour" in context_header("2026-01-09_09h05_point")

    def test_the_month_is_in_french_without_leaning_on_the_locale(self) -> None:
        from greffier.application.render import context_header

        assert "9 janvier 2026" in context_header("2026-01-09_09h05_point")
        assert "1 décembre 2025" in context_header("2025-12-01_08h00_point")

    def test_the_length_is_given_in_hours_and_minutes(self) -> None:
        from greffier.application.render import context_header

        assert "durée 1 h 00." in context_header("2026-08-25_14h33_x", 3606)
        assert "durée 2 h 05." in context_header("2026-08-25_14h33_x", 7500)

    def test_a_short_meeting_is_said_in_minutes(self) -> None:
        from greffier.application.render import context_header

        assert "durée 12 min." in context_header("2026-08-25_14h33_x", 720)

    def test_a_date_with_no_time_stays_valid(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-08-25_import-telephone")
        assert "25 août 2026" in header
        assert " h " not in header.split("2026")[1].split(".")[0]

    def test_the_end_time_follows_from_the_length(self) -> None:
        """Demandé à l'usage : le compte rendu doit dire début et fin."""
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_reunion", 1020.0)
        assert "de 16 h 46 à 17 h 03" in header

    def test_the_clock_times_win_over_the_transcribed_length(self) -> None:
        """Ce que l'enregistrement a retenu vaut mieux que ce qu'on déduit.

        Le 2026-09-09, une réunion arrêtée à 10 h 37 était annoncée « de 10 h 05
        à 10 h 32 » : la fin se déduisait de la durée transcrite, qui s'arrête au
        dernier mot prononcé, et la réunion s'était terminée sur cinq minutes de
        silence. Un compte rendu envoyé à des tiers ne peut pas se tromper de
        cinq minutes sur l'heure de fin.
        """
        from datetime import datetime

        from greffier.application.render import context_header

        # Datées dans le fuseau du poste : c'est l'heure que la personne a lue
        # sur sa montre qui doit figurer au compte rendu. L'état, lui, les garde
        # en UTC, et l'entête les y ramène.
        header = context_header(
            "2026-09-09_10h05_reunion",
            1620.0,  # la transcription s'arrête à 10 h 32
            started_at=datetime(2026, 9, 9, 10, 5).astimezone(),
            ended_at=datetime(2026, 9, 9, 10, 37).astimezone(),
        )
        assert "de 10 h 05 à 10 h 37" in header
        assert "10 h 32" not in header
        assert "durée 32 min" in header

    def test_with_no_clock_times_the_end_is_still_deduced(self) -> None:
        """Les réunions déjà sur le disque n'ont pas ces heures : rien ne casse."""
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_reunion", 1020.0)
        assert "de 16 h 46 à 17 h 03" in header

    def test_the_notice_about_recording_is_dictated(self) -> None:
        """Une mention légale n'est pas matière à style : un modèle qui la
        reformule la rend inexploitable, on ne peut plus la chercher."""
        from greffier.application.render import disclosure_header

        header = disclosure_header("rien")
        assert "telle quelle" in header
        assert "n'a pas été tracée" in header

    def test_the_notice_follows_what_was_actually_done(self) -> None:
        from greffier.application.render import disclosure_header

        assert "informés" in disclosure_header("annoncé")
        assert "accord" in disclosure_header("accord")

    def test_an_unknown_value_claims_no_consent(self) -> None:
        from greffier.application.render import disclosure_header

        assert "n'a pas été tracée" in disclosure_header("peut-être")

    def test_the_writer_receives_the_notice(self) -> None:
        writer = FakeWriter()
        processing = chain(writer=writer)
        processing.disclosure = "annoncé"
        processing.run_chain(AUDIO)
        assert "Mention sur l'enregistrement" in writer.recu

    def test_the_named_participants_are_listed(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_x", 600.0,
                                 names=["Pascal", "Cédric"], voices_heard=2)
        assert "Participants : Pascal, Cédric." in header

    def test_the_unnamed_voices_are_counted_apart(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_x", 600.0,
                                 names=["Pascal"], voices_heard=3)
        assert "Pascal, et 2 voix non nommées." in header

    def test_with_no_name_at_all_it_says_how_many_people(self) -> None:
        """Constaté : un compte rendu ne disait pas du tout qui était présent."""
        from greffier.application.render import context_header

        header = context_header("2026-09-02_17h04_x", 190.0, voices_heard=3)
        assert "3 personnes ont parlé, aucune nommée." in header

    def test_the_line_is_dictated_word_for_word(self) -> None:
        """Deux comptes rendus du même jour la formataient différemment."""
        from greffier.application.render import context_header

        assert "telle quelle" in context_header("2026-09-02_17h04_x", 190.0)

    def test_a_name_with_no_date_invents_nothing(self) -> None:
        from greffier.application.render import context_header

        assert context_header("import-sans-date") == ""

    def test_a_length_of_zero_is_not_announced(self) -> None:
        from greffier.application.render import context_header

        assert "Durée" not in context_header("2026-08-25_14h33_x", 0)


class TestTheHardwareHeader:
    """Un branchement en cours de réunion change ce que le compte rendu peut dire."""

    def test_with_no_event_nothing_is_added(self) -> None:
        from greffier.application.render import hardware_header

        assert hardware_header([]) == ""

    def test_every_reading_is_carried_over(self) -> None:
        from greffier.application.render import hardware_header

        header = hardware_header(["casque branché", "casque débranché"])
        assert "- casque branché" in header
        assert "- casque débranché" in header

    def test_the_writer_is_warned_an_exchange_may_be_one_way(self) -> None:
        # C'est le vrai risque : la voix de la personne qui enregistre manque au
        # début, et le compte rendu présente comme complet un échange dont il
        # n'a entendu qu'un côté.
        from greffier.application.render import hardware_header

        header = hardware_header(["casque branché en cours de réunion"])
        assert "un seul côté" in header
        assert "recollés" in header


class TestALengthAPersonCanRead:
    def test_under_a_minute_the_seconds_are_given(self) -> None:
        # « 0 min » serait faux : un extrait de trente secondes existe, et le
        # rédacteur doit savoir qu'il n'a qu'un extrait.
        from greffier.application.render import context_header

        assert "30 s" in context_header("extrait", 30.5)

    def test_a_file_with_no_date_announces_no_date(self) -> None:
        # Sinon le compte rendu s'ouvre sur « Date non précisée ».
        from greffier.application.render import context_header

        header = context_header("import-telephone", 720)
        assert "Date" not in header
        assert "12 min" in header

    def test_with_neither_date_nor_length_nothing_is_said(self) -> None:
        from greffier.application.render import context_header

        assert context_header("import-telephone", 0) == ""


class TestLevellingTheAudioFirst:
    """Un signal faible ne donne pas une transcription pauvre, il en invente une.

    Mesuré sur un enregistrement réel de treize secondes, micro à -43 dB : le
    modèle a rendu « Merci d'avoir regardé cette vidéo ! » là où la personne
    disait « Test, test de réunion ». Le même fichier normalisé rend la bonne
    phrase, donc la chaîne prépare l'audio avant de le transcrire.
    """

    def test_the_audio_is_prepared_before_being_transcribed(self, tmp_path):
        audio_recorder = FakeRecorder()
        processing = chain(audio_recorder=audio_recorder)
        audio = tmp_path / "reunion.wav"
        audio.write_bytes(b"RIFF----WAVEfmt ")
        processing.run_chain(audio, send=False)
        assert audio_recorder.prepares == [audio]


class TestTheChainKeepsTheMeeting:
    """Une réunion traitée doit laisser des traces, quel que soit l'appelant.

    Constaté en usage réel le 2026-09-02 : terminée depuis la fenêtre, une
    réunion était transcrite, son compte rendu rédigé et envoyé par courriel,
    puis **rien n'était écrit** — aucune ligne dans la liste des réunions,
    aucun moyen de nommer une voix après coup, aucun compte rendu à relire.
    L'écriture n'existait que dans la commande en ligne.
    """

    def test_the_master_file_is_written(self, tmp_path):
        deposees = []

        class SpyStore:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

        outcome = chain(store=SpyStore()).run_chain(AUDIO)
        assert deposees, "la chaîne doit déposer la réunion"
        assert outcome.fichier_maitre == tmp_path / "reunions/essai.json"

    def test_the_transcription_and_the_minutes_are_written(self, tmp_path):
        outcome = chain(
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
        ).run_chain(AUDIO)
        assert outcome.transcript_written is not None
        assert outcome.transcript_written.exists()
        assert outcome.compte_rendu_ecrit is not None
        assert outcome.compte_rendu_ecrit.read_text(encoding="utf-8")

    def test_it_is_kept_before_sending(self, tmp_path):
        """Un serveur de courriel indisponible ne doit rien faire perdre.

        L'exception remontait autrefois : les fichiers étaient bien gardés,
        mais la chaîne s'arrêtait là et la dernière phase publiée restait
        « envoi ». Elle va désormais jusqu'au bout et dit pourquoi — voir
        `TestUnEnvoiQuiEchoue`.
        """

        class FallingSender:
            def send(self, *_args, **_options):
                raise RuntimeError("serveur injoignable")

        processing = chain(
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
            sender=FallingSender(),
            recipient="moi@exemple.fr",
        )
        outcome = processing.run_chain(AUDIO)
        assert (tmp_path / "comptes-rendus").exists(), "le compte rendu survit à l'envoi"
        assert outcome.envoye is False
        assert any("injoignable" in a for a in outcome.warnings)

    def test_it_is_kept_before_writing_up(self, tmp_path):
        """Un rédacteur qui expire ne doit pas faire perdre la transcription.

        Le 2026-09-09, le rédacteur a dépassé son délai sur une réunion de
        32 minutes : la transcription et l'attribution des voix, déjà faites et
        justes, ont disparu avec l'exception, et rien ne permettait de
        reprendre. Le cas « aucun rédacteur » était protégé, le cas « le
        rédacteur échoue » ne l'était pas.
        """

        class TimingOutWriter:
            def write_up(self, transcription):
                raise subprocess.TimeoutExpired(cmd="redacteur", timeout=900)

        deposees = []

        class SpyStore:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

        processing = chain(
            writer=TimingOutWriter(),
            store=SpyStore(),
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
        )
        with pytest.raises(subprocess.TimeoutExpired):
            processing.run_chain(AUDIO)

        assert deposees, "la réunion doit être déposée avant la rédaction"
        assert deposees[0].utterances, "la transcription doit y être"
        assert deposees[0].turns, "l'attribution des voix doit y être"
        transcription = tmp_path / "transcriptions" / f"{AUDIO.stem}.txt"
        assert transcription.exists(), "la transcription lisible survit"
        assert not (tmp_path / "comptes-rendus").exists(), "aucun compte rendu tronqué"

    def test_the_meeting_takes_its_subject_from_the_minutes(self, tmp_path):
        """Demandé à l'usage : « 2026-09-09_10h05_reunion » ne dit rien.

        Le rédacteur a écrit son titre après avoir lu toute la transcription :
        personne n'est mieux placé pour nommer la réunion.
        """
        class TitlingWriter:
            def write_up(self, transcription):
                return "# Compte rendu : point d'avancement des projets\n\nTexte."

        deposees = []

        class SpyStore:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

            def read(self, identifier):
                raise FileNotFoundError(identifier)

        chain(writer=TitlingWriter(), store=SpyStore()).run_chain(AUDIO)
        assert deposees[-1].subject == "point d'avancement des projets"

    def test_a_subject_typed_by_hand_survives_reprocessing(self, tmp_path):
        """Une correction que la chaîne écraserait ne servirait à rien."""
        from datetime import UTC, datetime

        from greffier.domain.meeting import StoredMeeting

        class TitlingWriter:
            def write_up(self, transcription):
                return "# Compte rendu : titre automatique\n\nTexte."

        deposees = []

        class StoreWithSubject:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

            def read(self, identifier):
                return StoredMeeting(
                    identifier=identifier, audio=AUDIO,
                    processed_at=datetime.now(UTC), duration=1.0,
                    utterances=[], turns=[], names={}, propositions={},
                    warnings=[], subject="Point Oasis",
                )

        chain(writer=TitlingWriter(), store=StoreWithSubject()).run_chain(AUDIO)
        assert deposees[-1].subject == "Point Oasis"

    def test_with_no_folder_the_chain_still_works(self):
        """Les tests d'intégration s'en servent en mémoire, sans rien écrire."""
        outcome = chain().run_chain(AUDIO)
        assert outcome.transcript_written is None
        assert outcome.compte_rendu_ecrit is None

    def test_with_no_writer_the_meeting_is_kept(self, tmp_path):
        """Le cas de qui ne veut rien laisser sortir du poste.

        « Aucun — s'arrêter à la transcription attribuée » est un choix offert
        par l'assistant, et « --sans-compte-rendu » le prend pour un traitement.
        Le retour anticipé passait alors avant l'écriture : la transcription et
        l'attribution des voix étaient perdues à la seconde où elles étaient
        prêtes, alors que la commande proposait dans la foulée de nommer les
        voix d'une réunion qu'aucun dépôt ne connaissait.
        """
        deposees = []

        class SpyStore:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

        outcome = chain(
            writer=None,
            store=SpyStore(),
            dossier_transcriptions=tmp_path / "transcriptions",
        ).run_chain(AUDIO)

        assert deposees, "la réunion doit être déposée même sans compte rendu"
        assert outcome.transcript_written is not None
        assert outcome.transcript_written.exists()

    def test_with_no_writer_no_minutes_are_written(self, tmp_path):
        """Garder la réunion ne doit pas fabriquer un compte rendu vide."""
        outcome = chain(
            writer=None,
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
        ).run_chain(AUDIO)

        assert outcome.compte_rendu_ecrit is None
        assert not (tmp_path / "comptes-rendus").exists()
        assert outcome.fichier_maitre is None


class TestTheChannelsInARoom:
    """Le silence de la boucle système ne veut pas dire la même chose partout."""

    def test_a_meeting_in_a_room_raises_no_alarm(self):
        """Le micro de table entend tout le monde : il n'y a rien à signaler.

        Annoncer « seule ta voix est transcrite » y était faux, et le rédacteur
        lit ces avertissements — lui laisser croire qu'il manque du monde lui
        fait écrire un compte rendu prudent sur une transcription complète.
        """
        from greffier.application.process import AVERTISSEMENT_SANS_BOUCLE, Outcome

        outcome = Outcome(audio=AUDIO)
        outcome.warnings.append(AVERTISSEMENT_SANS_BOUCLE)
        outcome.turns = [
            SpeakerTurn(Span(0, 40), "0"),
            SpeakerTurn(Span(40, 90), "1"),
        ]
        chain()._preciser_les_canaux(outcome)
        assert outcome.warnings == []

    def test_one_voice_with_no_loopback_is_flagged(self):
        """Là, une visio mal branchée a bien pu perdre tout le monde."""
        from greffier.application.process import AVERTISSEMENT_SANS_BOUCLE, Outcome

        outcome = Outcome(audio=AUDIO)
        outcome.warnings.append(AVERTISSEMENT_SANS_BOUCLE)
        outcome.turns = [SpeakerTurn(Span(0, 90), "0")]
        chain()._preciser_les_canaux(outcome)
        assert len(outcome.warnings) == 1
        assert "visio" in outcome.warnings[0]

    def test_the_provisional_message_never_survives(self):
        """Il n'est pas fait pour être lu : c'est une marque, pas une phrase."""
        from greffier.application.process import AVERTISSEMENT_SANS_BOUCLE, Outcome

        for turns in ([SpeakerTurn(Span(0, 90), "0")],
                      [SpeakerTurn(Span(0, 40), "0"),
                       SpeakerTurn(Span(40, 90), "1")]):
            outcome = Outcome(audio=AUDIO)
            outcome.warnings.append(AVERTISSEMENT_SANS_BOUCLE)
            outcome.turns = turns
            chain()._preciser_les_canaux(outcome)
            assert AVERTISSEMENT_SANS_BOUCLE not in outcome.warnings

    def test_with_no_mark_nothing_is_added(self):
        from greffier.application.process import Outcome

        outcome = Outcome(audio=AUDIO)
        outcome.turns = [SpeakerTurn(Span(0, 90), "0")]
        chain()._preciser_les_canaux(outcome)
        assert outcome.warnings == []


class TestNamesakesAfterTheMeeting:
    """Deux voix reconnues sous le même nom n'en font qu'une.

    Le défaut, mesuré sur une réunion réelle de 1 h 42 : la chaîne concluait
    « Lise » sur neuf voix distinctes, dont huit d'un seul tour. Le compte
    rendu annonçait « et 9 voix non nommées » et huit participants de trop.

    Les vecteurs sont choisis pour tenir le cas exactement : les deux voix sont
    à 0,700 l'une de l'autre, donc **sous** le seuil de recollage, et à 0,92 de
    la personne en banque, donc toutes deux reconnues. Le recollage par
    empreinte ne peut rien ici ; le nom, lui, le dit.
    """

    #: 0,700 entre elles, 0,92 de Josiane chacune.
    VECTORS = {
        (0.0, 12.0): [1.0, 0.0, 0.0],
        (21.0, 28.0): [1.0, 0.0, 0.0],
        (13.0, 20.0): [0.7, 0.714, 0.0],
    }

    def _outcome(self):
        from greffier.domain.voiceprints import normalise

        bank = FakeBank([Person("Josiane", [normalise([0.92, 0.39, 0.0])])])
        processing = chain(extractor=FakeExtractor(self.VECTORS), bank=bank)
        return processing.run_chain(AUDIO)

    def test_one_voice_only_carries_the_name(self):
        outcome = self._outcome()
        assert list(outcome.names.values()) == ["Josiane"], outcome.names

    def test_the_best_fed_voice_keeps_the_turns(self):
        """Dix-neuf secondes contre sept : c'est le meilleur extrait des deux."""
        outcome = self._outcome()
        gardee = next(iter(outcome.names))
        assert {t.voice for t in outcome.turns} == {gardee}

    def test_the_utterances_follow(self):
        """Sinon le compte rendu attribue encore à une voix qui n'existe plus."""
        outcome = self._outcome()
        gardee = next(iter(outcome.names))
        portees = {r.voice for r in outcome.utterances if r.voice is not None}
        assert portees == {gardee}, portees

    def test_two_distinct_people_stay_two(self):
        """Le garde-fou : la règle ne doit pas tout replier sur une voix."""
        from greffier.domain.voiceprints import normalise

        bank = FakeBank([
            Person("Josiane", [normalise([1.0, 0.02, 0.0])]),
            Person("Marcel", [normalise([0.02, 1.0, 0.0])]),
        ])
        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (21.0, 28.0): [1.0, 0.0, 0.0],
                    (13.0, 20.0): [0.0, 1.0, 0.0]}
        outcome = chain(
            extractor=FakeExtractor(vectors), bank=bank
        ).run_chain(AUDIO)
        assert sorted(outcome.names.values()) == ["Josiane", "Marcel"]


class TestWhenTheSendingFails:
    """Un envoi qui échoue ne doit pas emporter la chaîne.

    Le 2026-09-10, une réunion de 1 h 42 est restée figée sur la phase
    « envoi » deux heures durant. Tout était déjà sur le disque — la
    transcription, les voix, le compte rendu, gardés avant l'envoi
    justement pour cela — mais l'exception remontait, la phase suivante
    n'était jamais publiée, et l'échec ne se rapportait que par une fenêtre
    modale que personne n'a vue.
    """

    class FallingSender:
        def send(self, recipient, subject, corps, pieces):
            raise PermissionError("macOS refuse de piloter Outlook.")

    def _outcome(self, log):
        processing = chain(
            sender=self.FallingSender(),
            recipient="tanguy@example.org",
            log=log,
        )
        return processing.run_chain(AUDIO)

    def test_the_chain_goes_to_the_end(self):
        log = FakeStateLog()
        self._outcome(log)
        assert log.phases[-1] == Phase.TERMINE.value, log.phases

    def test_the_sending_phase_is_not_the_last_one_left(self):
        """C'est elle qui mentait : « Envoi du compte rendu… », pour toujours."""
        log = FakeStateLog()
        self._outcome(log)
        assert Phase.ENVOI.value in log.phases
        assert log.phases[-1] != Phase.ENVOI.value

    def test_the_reason_is_said(self):
        outcome = self._outcome(FakeStateLog())
        assert any("Outlook" in a for a in outcome.warnings), outcome.warnings
        assert any("greffier envoyer" in a for a in outcome.warnings)

    def test_the_minutes_are_not_announced_as_sent(self):
        assert self._outcome(FakeStateLog()).envoye is False

    def test_the_minutes_are_there_all_the_same(self):
        assert self._outcome(FakeStateLog()).minutes


class TestTheParticipantsLine:
    """La première ligne du compte rendu, celle que tout le monde lit.

    Les deux défauts, sur la réunion du 2026-09-10 : « et 9 voix non nommées »
    là où huit de ces neuf étaient la même personne — corrigé par la réunion
    des homonymes — et un accord de verbe qui écrivait « 1 personne ont parlé »
    en tête d'un compte rendu envoyé par courriel.
    """

    def _line(self, names, heard: int) -> str:
        from greffier.application.render import context_header

        return context_header(
            "2026-09-10_10h10_reunion", 6120.0, names=names, voices_heard=heard
        )

    def test_one_anonymous_voice_is_said_in_the_singular(self):
        line = self._line(["Pascal", "Bastien"], 3)
        assert "et 1 voix non nommée." in line
        assert "non nommées" not in line

    def test_several_anonymous_voices_in_the_plural(self):
        assert "et 3 voix non nommées." in self._line(["Pascal"], 4)

    def test_all_named_leaves_nothing_trailing(self):
        line = self._line(["Pascal", "Bastien"], 2)
        assert "Participants : Pascal, Bastien." in line
        assert "non nomm" not in line

    def test_one_unnamed_person_agrees_the_verb(self):
        """« 1 personne ont parlé » s'écrivait tel quel."""
        line = self._line([], 1)
        assert "1 personne a parlé, non nommée." in line
        assert "ont parlé" not in line

    def test_several_unnamed_people_agree_the_verb(self):
        line = self._line([], 4)
        assert "4 personnes ont parlé" in line

    def test_a_repeated_name_counts_once(self):
        """La réunion des homonymes le fait en amont ; la ligne ne doit pas
        le défaire si un nom arrive deux fois."""
        line = self._line(["Lise", "Lise", "Pascal"], 3)
        assert "Participants : Lise, Pascal, et 1 voix non nommée." in line


class TestTheFloorBeforeNamingAVoice:
    """La banque ne doit pas nommer quelqu'un sur trois secondes de parole.

    Mesuré sur la réunion du 2026-09-10 : « Sophie » a été posée sur une voix
    de **3,1 secondes**, et Sophie n'était pas dans la pièce. La même banque a
    nommé neuf fragments d'une seule Lise, entre 2,5 et 8,1 secondes chacun.

    Une étiquette fausse dans un compte rendu est pire qu'une voix sans nom :
    on la croit. Le fil du direct portait déjà ce plancher ; la chaîne d'après
    réunion ne l'avait pas.
    """

    def _outcome_of(self, seconde_duree: float):
        from greffier.domain.voiceprints import normalise

        vecteurs = {(0.0, 12.0): [1.0, 0.0, 0.0], (21.0, 28.0): [1.0, 0.0, 0.0],
                    (13.0, 13.0 + seconde_duree): [0.02, 1.0, 0.0]}
        turns = [turn(0, 12, "1"), turn(13, 13 + seconde_duree, "2"),
                 turn(21, 28, "1")]
        bank = FakeBank([Person("Josiane", [normalise([0.02, 1.0, 0.0])])])
        return chain(
            extractor=FakeExtractor(vecteurs), bank=bank,
            diariser=FakeDiariser(turns),
        ).run_chain(AUDIO)

    def test_a_voice_of_three_seconds_is_not_named(self):
        assert "Josiane" not in self._outcome_of(3.0).names.values()

    def test_the_same_voice_is_named_once_it_has_enough(self):
        """Le plancher ne doit pas empêcher de reconnaître qui parle vraiment."""
        assert self._outcome_of(9.0).names.get("2") == "Josiane"

    def test_the_floor_is_six_seconds(self):
        """Le double du seuil du calibrage. Changé, la mesure est à refaire."""
        from greffier.application.process import MATERIAL_TO_RECOGNISE

        assert MATERIAL_TO_RECOGNISE == 6.0

    def test_just_under_the_floor_does_not_pass(self):
        assert "Josiane" not in self._outcome_of(5.9).names.values()

    def test_just_over_it_passes(self):
        assert self._outcome_of(6.1).names.get("2") == "Josiane"


class TestTheInstructionsReachTheWriter:
    """La chaîne doit poser les consignes de la séance devant le rédacteur.

    Le défaut : elles étaient écrites dans la conversation, gardées sur le
    disque, et la chaîne ne les lisait pas. Dix-sept messages perdus sur une
    réunion de 1 h 42, dont « Il n'y a pas de sophie dans la réunion ».
    """

    CONSIGNES = [
        "Il n'y a pas de sophie dans la réunion",
        "Pascal n'a pas dit booting, mais blue team",
    ]

    def _writer(self, consignes):
        writer = FakeWriter()
        chain(writer=writer, instructions=lambda _i: consignes).run_chain(AUDIO)
        return writer.recu

    def test_the_instructions_are_in_front_of_the_writer(self):
        transcription = self._writer(self.CONSIGNES)
        assert "Il n'y a pas de sophie" in transcription
        assert "blue team" in transcription

    def test_they_come_before_the_rest_of_the_header(self):
        """Une correction humaine l'emporte sur ce que la transcription croit."""
        transcription = self._writer(self.CONSIGNES)
        assert transcription.index("Consignes données") < transcription.index(
            "Mention sur l'enregistrement"
        )

    def test_with_no_instruction_nothing_is_added(self):
        assert "Consignes données" not in self._writer([])

    def test_an_unreadable_conversation_does_not_cost_the_minutes(self):
        """Le compte rendu vaut plus qu'un en-tête."""
        def tombe(_identifier):
            raise OSError("fichier illisible")

        writer = FakeWriter()
        outcome = chain(writer=writer, instructions=tombe).run_chain(AUDIO)
        assert outcome.minutes, "le compte rendu doit être écrit quand même"
        assert "Consignes données" not in writer.recu

    def test_with_no_reader_of_instructions_the_chain_runs(self):
        """Le port est facultatif : la ligne de commande peut ne pas le brancher."""
        writer = FakeWriter()
        chain(writer=writer).run_chain(AUDIO)
        assert "Consignes données" not in writer.recu
