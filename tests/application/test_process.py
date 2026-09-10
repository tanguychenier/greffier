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


class EnregistreurFactice:
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


class TranscripteurFactice:
    def __init__(self, utterances):
        self.utterances = utterances
        self.amorce_recue = None

    def transcribe(self, audio, language, prompt_seed):
        self.amorce_recue = prompt_seed
        return list(self.utterances)


class DiariseurFactice:
    def __init__(self, turns):
        self._turns = turns

    def segment(self, audio, people):
        return list(self._turns)


class RedacteurFactice:
    def __init__(self):
        self.recu = None

    def write_up(self, transcription):
        self.recu = transcription
        return "# Compte rendu\n\nTout va bien."


class ExpediteurFactice:
    def __init__(self):
        self.envois = []

    def send(self, recipient, subject, corps, pieces):
        self.envois.append((recipient, subject, corps))


class JournalFactice:
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


def chaine(**overrides):
    defauts = dict(
        audio_recorder=EnregistreurFactice(),
        transcriber=TranscripteurFactice(BAVARDAGE),
        diariser=DiariseurFactice(TURNS),
        writer=RedacteurFactice(),
    )
    defauts.update(overrides)
    return Chain(**defauts)


class TestGardeFous:
    def test_un_enregistrement_muet_arrete_tout(self):
        """Le bug du 2026-08-20 : sans ça, un CR était fabriqué puis envoyé."""
        processing = chaine(audio_recorder=EnregistreurFactice(levels=(-120.0, -120.0)))
        with pytest.raises(ChainStopped) as arret:
            processing.run_chain(AUDIO)
        assert arret.value.phase is Phase.ECHEC
        assert "muet" in arret.value.because

    def test_une_transcription_vide_n_est_pas_redigee(self):
        transcriber = TranscripteurFactice([utterance(0, 2, "Bonjour.")])
        writer = RedacteurFactice()
        processing = chaine(transcriber=transcriber, writer=writer)
        with pytest.raises(ChainStopped, match="quasi vide"):
            processing.run_chain(AUDIO)
        assert writer.recu is None, "le rédacteur ne doit pas être appelé"

    def test_un_nombre_de_participants_qui_contredit_l_audio_est_signale(self):
        """Annoncer un nombre force exactement autant de groupes, en silence.

        Le 2026-09-09, « 4 participants » traînait dans la configuration d'un
        poste et la réunion en comptait davantage : deux personnes ont été
        confondues sans que rien ne le dise.
        """
        processing = chaine()
        processing.people = 9
        outcome = processing.run_chain(AUDIO)
        assert any("9 participants sont annoncés" in a for a in outcome.warnings)

    def test_un_nombre_juste_ne_dit_rien(self):
        processing = chaine()
        processing.people = len(chaine().run_chain(AUDIO).significant_voices())
        outcome = processing.run_chain(AUDIO)
        assert not any("annoncés" in a for a in outcome.warnings)

    def test_sans_nombre_annonce_il_n_y_a_rien_a_contredire(self):
        outcome = chaine().run_chain(AUDIO)
        assert not any("annoncés" in a for a in outcome.warnings)

    def test_le_seuil_de_mots_reste_bas_mais_non_nul(self):
        assert 0 < MOTS_MINIMUM <= 50

    def test_un_micro_muet_avertit_sans_bloquer(self):
        processing = chaine(audio_recorder=EnregistreurFactice(levels=(-120.0, -30.0)))
        outcome = processing.run_chain(AUDIO)
        assert any("micro" in a for a in outcome.warnings)
        assert outcome.minutes

    def test_aucun_son_systeme_avertit_sans_bloquer(self):
        processing = chaine(audio_recorder=EnregistreurFactice(levels=(-30.0, -120.0)))
        outcome = processing.run_chain(AUDIO)
        assert any("système" in a for a in outcome.warnings)


class TestEnchainement:
    def test_les_phases_se_suivent(self):
        log = JournalFactice()
        chaine(log=log).run_chain(AUDIO)
        assert log.phases[0] == Phase.TRANSCRIPTION.value
        assert Phase.LOCUTEURS.value in log.phases
        assert log.phases[-1] == Phase.TERMINE.value

    def test_le_vocabulaire_est_transmis_au_transcripteur(self):
        transcriber = TranscripteurFactice(BAVARDAGE)
        processing = chaine(transcriber=transcriber)
        processing.prompt_seed = "Vocabulaire : Copernic."
        processing.run_chain(AUDIO)
        assert transcriber.amorce_recue == "Vocabulaire : Copernic."

    def test_sans_redacteur_la_transcription_reste_disponible(self):
        outcome = chaine(writer=None).run_chain(AUDIO)
        assert outcome.utterances and outcome.minutes == ""

    def test_l_envoi_n_a_lieu_qu_avec_un_destinataire(self):
        sender = ExpediteurFactice()
        processing = chaine(sender=sender)
        assert processing.run_chain(AUDIO).envoye is False
        processing.recipient = "moi@exemple.fr"
        assert processing.run_chain(AUDIO).envoye is True
        assert sender.envois[0][0] == "moi@exemple.fr"

    def test_on_peut_traiter_sans_envoyer(self):
        sender = ExpediteurFactice()
        processing = chaine(sender=sender)
        processing.recipient = "moi@exemple.fr"
        outcome = processing.run_chain(AUDIO, send=False)
        assert outcome.minutes and not outcome.envoye and not sender.envois


class TestAttributionDesVoix:
    def test_chaque_replique_recoit_la_voix_dominante(self):
        outcome = chaine().run_chain(AUDIO)
        assert [r.voice for r in outcome.utterances] == ["1", "1", "2", "1"]

    def test_l_auto_presentation_nomme_le_locuteur(self):
        """« moi c'est Tanguy » désigne celui qui parle."""
        outcome = chaine().run_chain(AUDIO)
        assert outcome.names["1"] == "Tanguy"

    def test_le_vocabulaire_metier_n_est_pas_pris_pour_un_prenom(self):
        transcriber = TranscripteurFactice([
            utterance(0, 6, "Merci Copernic pour la démonstration de ce matin, c'était clair."),
            utterance(7, 14, "On enchaîne sur le sujet suivant, à savoir la reprise des données."),
            utterance(15, 22, "Très bien, je note que la reprise démarre la semaine prochaine."),
        ])
        processing = chaine(transcriber=transcriber)
        processing.not_first_names = frozenset({"copernic"})
        outcome = processing.run_chain(AUDIO)
        assert "Copernic" not in outcome.names.values()
        assert "Copernic" not in outcome.propositions.values()

    def test_la_transcription_rendue_porte_les_noms_et_les_horaires(self):
        writer = RedacteurFactice()
        chaine(writer=writer).run_chain(AUDIO)
        assert "[Tanguy]" in writer.recu
        assert "00:00" in writer.recu
        # Une voix sans nom reste identifiée, jamais inventée.
        assert "[Personne 2]" in writer.recu


class ExtracteurFactice:
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


class BanqueFactice:
    def __init__(self, people):
        self._people = people
        self.ajouts = []

    def people(self):
        return list(self._people)

    def record(self, name, voiceprint):
        self.ajouts.append(name)


class TestBanqueDeVoix:
    def test_une_voix_connue_est_nommee_sans_qu_on_la_nomme(self):
        """Le cœur du besoin : « Josiane » et non « Personne 2 »."""
        from greffier.domain.voiceprints import normalise

        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        bank = BanqueFactice([Person("Josiane", [normalise([0.02, 1.0, 0.0])])])
        processing = chaine(extractor=ExtracteurFactice(vectors), bank=bank)
        outcome = processing.run_chain(AUDIO)
        assert outcome.names["2"] == "Josiane"

    def test_un_desaccord_entre_banque_et_reunion_est_signale(self):
        """La banque a été validée par un humain : elle prime, mais on le dit."""
        from greffier.domain.voiceprints import normalise

        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        bank = BanqueFactice([Person("Michel", [normalise([1.0, 0.02, 0.0])])])
        processing = chaine(extractor=ExtracteurFactice(vectors), bank=bank)
        outcome = processing.run_chain(AUDIO)
        assert outcome.names["1"] == "Michel"
        assert any("Michel" in a and "Tanguy" in a for a in outcome.warnings)

    def test_une_banque_vide_ne_gene_pas(self):
        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        processing = chaine(extractor=ExtracteurFactice(vectors), bank=BanqueFactice([]))
        assert processing.run_chain(AUDIO).names["1"] == "Tanguy"


class TestLectureDuResultat:
    def test_les_fragments_ne_sont_pas_des_participants(self):
        """La segmentation laisse une traîne de fragments d'une seconde."""
        outcome = chaine().run_chain(AUDIO)
        outcome.turns = outcome.turns + [turn(29, 29.5, "bruit")]
        assert "bruit" in outcome.speaking_time()
        assert "bruit" not in outcome.significant_voices()

    def test_le_temps_de_parole_va_du_plus_bavard_au_moins(self):
        outcome = chaine().run_chain(AUDIO)
        durees = list(outcome.speaking_time().values())
        assert durees == sorted(durees, reverse=True)


class TestFiabilite:
    def test_la_couverture_dit_ce_qui_manque(self):
        """25 s de texte sur 28 s de parole : seules les respirations manquent."""
        outcome = chaine().run_chain(AUDIO)
        assert outcome.coverage == pytest.approx(25 / 28, abs=0.01)

    def test_un_trou_de_transcription_est_repere(self):
        transcriber = TranscripteurFactice([
            utterance(0, 10, "On commence par le point sur la recette de la semaine."),
            utterance(120, 130, "Voilà, je crois qu'on a fait le tour des sujets prévus."),
        ])
        diariser = DiariseurFactice([turn(0, 10, "1"), turn(120, 130, "2")])
        outcome = chaine(transcriber=transcriber, diariser=diariser).run_chain(AUDIO)
        gaps = outcome.gaps(minimum=8)
        assert any(t.duration > 100 for t in gaps)

    def test_le_redacteur_est_prevenu_de_ce_qui_manque(self):
        """Sans cet en-tête, le compte rendu présente comme complet un texte
        qui ne l'est pas."""
        from greffier.application.render import reliability_header

        transcriber = TranscripteurFactice([
            utterance(0, 10, "On commence par le point sur la recette de la semaine."),
            utterance(120, 130, "Voilà, je crois qu'on a fait le tour des sujets prévus."),
        ])
        diariser = DiariseurFactice([turn(0, 10, "1"), turn(120, 130, "2")])
        writer = RedacteurFactice()
        chaine(transcriber=transcriber, diariser=diariser,
               writer=writer).run_chain(AUDIO)
        assert "Fiabilité de la transcription" in writer.recu
        assert "ne comble" in writer.recu
        assert reliability_header(chaine().run_chain(AUDIO)) == "", \
            "une transcription complète ne doit pas être affublée d'un avertissement"


class TestEnteteContexte:
    """La date de la réunion, dite au rédacteur.

    Sans elle, le rédacteur prend la date du traitement : une réunion du 25
    s'est retrouvée datée du 26 dans un compte rendu réel.
    """

    def test_la_date_et_l_heure_sortent_du_nom_de_fichier(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-08-25_14h33_reunion-essai-reel")
        assert "25 août 2026" in header
        assert "14 h 33" in header

    def test_le_redacteur_est_prie_de_ne_pas_prendre_la_date_du_jour(self) -> None:
        from greffier.application.render import context_header

        assert "jamais celle du jour" in context_header("2026-01-09_09h05_point")

    def test_le_mois_est_en_francais_sans_dependre_de_la_locale(self) -> None:
        from greffier.application.render import context_header

        assert "9 janvier 2026" in context_header("2026-01-09_09h05_point")
        assert "1 décembre 2025" in context_header("2025-12-01_08h00_point")

    def test_la_duree_est_rendue_en_heures_et_minutes(self) -> None:
        from greffier.application.render import context_header

        assert "durée 1 h 00." in context_header("2026-08-25_14h33_x", 3606)
        assert "durée 2 h 05." in context_header("2026-08-25_14h33_x", 7500)

    def test_une_reunion_courte_est_dite_en_minutes(self) -> None:
        from greffier.application.render import context_header

        assert "durée 12 min." in context_header("2026-08-25_14h33_x", 720)

    def test_une_date_sans_heure_reste_valide(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-08-25_import-telephone")
        assert "25 août 2026" in header
        assert " h " not in header.split("2026")[1].split(".")[0]

    def test_l_heure_de_fin_se_deduit_de_la_duree(self) -> None:
        """Demandé à l'usage : le compte rendu doit dire début et fin."""
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_reunion", 1020.0)
        assert "de 16 h 46 à 17 h 03" in header

    def test_les_heures_d_horloge_l_emportent_sur_la_duree_transcrite(self) -> None:
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
            commencee_le=datetime(2026, 9, 9, 10, 5).astimezone(),
            terminee_le=datetime(2026, 9, 9, 10, 37).astimezone(),
        )
        assert "de 10 h 05 à 10 h 37" in header
        assert "10 h 32" not in header
        assert "durée 32 min" in header

    def test_sans_heures_retenues_la_fin_reste_deduite(self) -> None:
        """Les réunions déjà sur le disque n'ont pas ces heures : rien ne casse."""
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_reunion", 1020.0)
        assert "de 16 h 46 à 17 h 03" in header

    def test_la_mention_sur_l_enregistrement_est_dictee(self) -> None:
        """Une mention légale n'est pas matière à style : un modèle qui la
        reformule la rend inexploitable, on ne peut plus la chercher."""
        from greffier.application.render import disclosure_header

        header = disclosure_header("rien")
        assert "telle quelle" in header
        assert "n'a pas été tracée" in header

    def test_la_mention_suit_ce_qui_a_ete_fait(self) -> None:
        from greffier.application.render import disclosure_header

        assert "informés" in disclosure_header("annoncé")
        assert "accord" in disclosure_header("accord")

    def test_une_valeur_inconnue_ne_pretend_a_aucun_accord(self) -> None:
        from greffier.application.render import disclosure_header

        assert "n'a pas été tracée" in disclosure_header("peut-être")

    def test_le_redacteur_recoit_la_mention(self) -> None:
        writer = RedacteurFactice()
        processing = chaine(writer=writer)
        processing.disclosure = "annoncé"
        processing.run_chain(AUDIO)
        assert "Mention sur l'enregistrement" in writer.recu

    def test_les_participants_nommes_sont_listes(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_x", 600.0,
                                 names=["Paul", "Camilo"], voix_entendues=2)
        assert "Participants : Paul, Camilo." in header

    def test_les_voix_non_nommees_sont_comptees_a_part(self) -> None:
        from greffier.application.render import context_header

        header = context_header("2026-09-02_16h46_x", 600.0,
                                 names=["Paul"], voix_entendues=3)
        assert "Paul, et 2 voix non nommées." in header

    def test_sans_aucun_nom_on_dit_combien_de_personnes(self) -> None:
        """Constaté : un compte rendu ne disait pas du tout qui était présent."""
        from greffier.application.render import context_header

        header = context_header("2026-09-02_17h04_x", 190.0, voix_entendues=3)
        assert "3 personnes ont parlé, aucune nommée." in header

    def test_la_ligne_est_dictee_mot_pour_mot(self) -> None:
        """Deux comptes rendus du même jour la formataient différemment."""
        from greffier.application.render import context_header

        assert "telle quelle" in context_header("2026-09-02_17h04_x", 190.0)

    def test_un_nom_sans_date_ne_fait_rien_inventer(self) -> None:
        from greffier.application.render import context_header

        assert context_header("import-sans-date") == ""

    def test_une_duree_nulle_n_est_pas_annoncee(self) -> None:
        from greffier.application.render import context_header

        assert "Durée" not in context_header("2026-08-25_14h33_x", 0)


class TestEnteteMateriel:
    """Un branchement en cours de réunion change ce que le compte rendu peut dire."""

    def test_sans_evenement_rien_n_est_ajoute(self) -> None:
        from greffier.application.render import hardware_header

        assert hardware_header([]) == ""

    def test_chaque_constat_est_repris(self) -> None:
        from greffier.application.render import hardware_header

        header = hardware_header(["casque branché", "casque débranché"])
        assert "- casque branché" in header
        assert "- casque débranché" in header

    def test_le_redacteur_est_averti_qu_un_echange_peut_etre_a_sens_unique(self) -> None:
        # C'est le vrai risque : la voix de la personne qui enregistre manque au
        # début, et le compte rendu présente comme complet un échange dont il
        # n'a entendu qu'un côté.
        from greffier.application.render import hardware_header

        header = hardware_header(["casque branché en cours de réunion"])
        assert "un seul côté" in header
        assert "recollés" in header


class TestDureeLisible:
    def test_sous_la_minute_on_donne_les_secondes(self) -> None:
        # « 0 min » serait faux : un extrait de trente secondes existe, et le
        # rédacteur doit savoir qu'il n'a qu'un extrait.
        from greffier.application.render import context_header

        assert "30 s" in context_header("extrait", 30.5)

    def test_un_fichier_sans_date_n_annonce_pas_une_date_absente(self) -> None:
        # Sinon le compte rendu s'ouvre sur « Date non précisée ».
        from greffier.application.render import context_header

        header = context_header("import-telephone", 720)
        assert "Date" not in header
        assert "12 min" in header

    def test_sans_date_ni_duree_rien_n_est_dit(self) -> None:
        from greffier.application.render import context_header

        assert context_header("import-telephone", 0) == ""


class TestMiseANiveauAvantTranscription:
    """Un signal faible ne donne pas une transcription pauvre, il en invente une.

    Mesuré sur un enregistrement réel de treize secondes, micro à -43 dB : le
    modèle a rendu « Merci d'avoir regardé cette vidéo ! » là où la personne
    disait « Test, test de réunion ». Le même fichier normalisé rend la bonne
    phrase, donc la chaîne prépare l'audio avant de le transcrire.
    """

    def test_l_audio_est_prepare_avant_d_etre_transcrit(self, tmp_path):
        audio_recorder = EnregistreurFactice()
        processing = chaine(audio_recorder=audio_recorder)
        audio = tmp_path / "reunion.wav"
        audio.write_bytes(b"RIFF----WAVEfmt ")
        processing.run_chain(audio, send=False)
        assert audio_recorder.prepares == [audio]


class TestLaChaineGardeLaReunion:
    """Une réunion traitée doit laisser des traces, quel que soit l'appelant.

    Constaté en usage réel le 2026-09-02 : terminée depuis la fenêtre, une
    réunion était transcrite, son compte rendu rédigé et envoyé par courriel,
    puis **rien n'était écrit** — aucune ligne dans la liste des réunions,
    aucun moyen de nommer une voix après coup, aucun compte rendu à relire.
    L'écriture n'existait que dans la commande en ligne.
    """

    def test_le_fichier_maitre_est_ecrit(self, tmp_path):
        deposees = []

        class DepotEspion:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

        outcome = chaine(store=DepotEspion()).run_chain(AUDIO)
        assert deposees, "la chaîne doit déposer la réunion"
        assert outcome.fichier_maitre == tmp_path / "reunions/essai.json"

    def test_la_transcription_et_le_compte_rendu_sont_ecrits(self, tmp_path):
        outcome = chaine(
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
        ).run_chain(AUDIO)
        assert outcome.transcript_written is not None
        assert outcome.transcript_written.exists()
        assert outcome.compte_rendu_ecrit is not None
        assert outcome.compte_rendu_ecrit.read_text(encoding="utf-8")

    def test_garde_avant_envoi(self, tmp_path):
        """Un serveur de courriel indisponible ne doit rien faire perdre.

        L'exception remontait autrefois : les fichiers étaient bien gardés,
        mais la chaîne s'arrêtait là et la dernière phase publiée restait
        « envoi ». Elle va désormais jusqu'au bout et dit pourquoi — voir
        `TestUnEnvoiQuiEchoue`.
        """

        class ExpediteurQuiTombe:
            def send(self, *_args, **_options):
                raise RuntimeError("serveur injoignable")

        processing = chaine(
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
            sender=ExpediteurQuiTombe(),
            recipient="moi@exemple.fr",
        )
        outcome = processing.run_chain(AUDIO)
        assert (tmp_path / "comptes-rendus").exists(), "le compte rendu survit à l'envoi"
        assert outcome.envoye is False
        assert any("injoignable" in a for a in outcome.warnings)

    def test_garde_avant_de_rediger(self, tmp_path):
        """Un rédacteur qui expire ne doit pas faire perdre la transcription.

        Le 2026-09-09, le rédacteur a dépassé son délai sur une réunion de
        32 minutes : la transcription et l'attribution des voix, déjà faites et
        justes, ont disparu avec l'exception, et rien ne permettait de
        reprendre. Le cas « aucun rédacteur » était protégé, le cas « le
        rédacteur échoue » ne l'était pas.
        """

        class RedacteurQuiExpire:
            def write_up(self, transcription):
                raise subprocess.TimeoutExpired(cmd="redacteur", timeout=900)

        deposees = []

        class DepotEspion:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

        processing = chaine(
            writer=RedacteurQuiExpire(),
            store=DepotEspion(),
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

    def test_la_reunion_se_nomme_depuis_le_compte_rendu(self, tmp_path):
        """Demandé à l'usage : « 2026-09-09_10h05_reunion » ne dit rien.

        Le rédacteur a écrit son titre après avoir lu toute la transcription :
        personne n'est mieux placé pour nommer la réunion.
        """
        class RedacteurQuiTitre:
            def write_up(self, transcription):
                return "# Compte rendu : point d'avancement des projets\n\nTexte."

        deposees = []

        class DepotEspion:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

            def read(self, identifier):
                raise FileNotFoundError(identifier)

        chaine(writer=RedacteurQuiTitre(), store=DepotEspion()).run_chain(AUDIO)
        assert deposees[-1].subject == "point d'avancement des projets"

    def test_un_sujet_saisi_a_la_main_survit_au_retraitement(self, tmp_path):
        """Une correction que la chaîne écraserait ne servirait à rien."""
        from datetime import UTC, datetime

        from greffier.domain.meeting import StoredMeeting

        class RedacteurQuiTitre:
            def write_up(self, transcription):
                return "# Compte rendu : titre automatique\n\nTexte."

        deposees = []

        class DepotAvecSujet:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

            def read(self, identifier):
                return StoredMeeting(
                    identifier=identifier, audio=AUDIO,
                    traitee_le=datetime.now(UTC), duration=1.0,
                    utterances=[], turns=[], names={}, propositions={},
                    warnings=[], subject="Point Oasis",
                )

        chaine(writer=RedacteurQuiTitre(), store=DepotAvecSujet()).run_chain(AUDIO)
        assert deposees[-1].subject == "Point Oasis"

    def test_sans_dossier_la_chaine_reste_utilisable(self):
        """Les tests d'intégration s'en servent en mémoire, sans rien écrire."""
        outcome = chaine().run_chain(AUDIO)
        assert outcome.transcript_written is None
        assert outcome.compte_rendu_ecrit is None

    def test_sans_redacteur_la_reunion_est_gardee(self, tmp_path):
        """Le cas de qui ne veut rien laisser sortir du poste.

        « Aucun — s'arrêter à la transcription attribuée » est un choix offert
        par l'assistant, et « --sans-compte-rendu » le prend pour un traitement.
        Le retour anticipé passait alors avant l'écriture : la transcription et
        l'attribution des voix étaient perdues à la seconde où elles étaient
        prêtes, alors que la commande proposait dans la foulée de nommer les
        voix d'une réunion qu'aucun dépôt ne connaissait.
        """
        deposees = []

        class DepotEspion:
            def record(self, meeting):
                deposees.append(meeting)
                return tmp_path / "reunions/essai.json"

        outcome = chaine(
            writer=None,
            store=DepotEspion(),
            dossier_transcriptions=tmp_path / "transcriptions",
        ).run_chain(AUDIO)

        assert deposees, "la réunion doit être déposée même sans compte rendu"
        assert outcome.transcript_written is not None
        assert outcome.transcript_written.exists()

    def test_sans_redacteur_aucun_compte_rendu_n_est_ecrit(self, tmp_path):
        """Garder la réunion ne doit pas fabriquer un compte rendu vide."""
        outcome = chaine(
            writer=None,
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
        ).run_chain(AUDIO)

        assert outcome.compte_rendu_ecrit is None
        assert not (tmp_path / "comptes-rendus").exists()
        assert outcome.fichier_maitre is None


class TestCanauxEnPresentiel:
    """Le silence de la boucle système ne veut pas dire la même chose partout."""

    def test_une_reunion_en_salle_ne_declenche_aucune_alarme(self):
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
        chaine()._preciser_les_canaux(outcome)
        assert outcome.warnings == []

    def test_une_seule_voix_sans_boucle_est_signalee(self):
        """Là, une visio mal branchée a bien pu perdre tout le monde."""
        from greffier.application.process import AVERTISSEMENT_SANS_BOUCLE, Outcome

        outcome = Outcome(audio=AUDIO)
        outcome.warnings.append(AVERTISSEMENT_SANS_BOUCLE)
        outcome.turns = [SpeakerTurn(Span(0, 90), "0")]
        chaine()._preciser_les_canaux(outcome)
        assert len(outcome.warnings) == 1
        assert "visio" in outcome.warnings[0]

    def test_le_message_provisoire_ne_survit_jamais(self):
        """Il n'est pas fait pour être lu : c'est une marque, pas une phrase."""
        from greffier.application.process import AVERTISSEMENT_SANS_BOUCLE, Outcome

        for turns in ([SpeakerTurn(Span(0, 90), "0")],
                      [SpeakerTurn(Span(0, 40), "0"),
                       SpeakerTurn(Span(40, 90), "1")]):
            outcome = Outcome(audio=AUDIO)
            outcome.warnings.append(AVERTISSEMENT_SANS_BOUCLE)
            outcome.turns = turns
            chaine()._preciser_les_canaux(outcome)
            assert AVERTISSEMENT_SANS_BOUCLE not in outcome.warnings

    def test_sans_marque_rien_n_est_ajoute(self):
        from greffier.application.process import Outcome

        outcome = Outcome(audio=AUDIO)
        outcome.turns = [SpeakerTurn(Span(0, 90), "0")]
        chaine()._preciser_les_canaux(outcome)
        assert outcome.warnings == []


class TestHomonymesApresReunion:
    """Deux voix reconnues sous le même nom n'en font qu'une.

    Le défaut, mesuré sur une réunion réelle de 1 h 42 : la chaîne concluait
    « Laura » sur neuf voix distinctes, dont huit d'un seul tour. Le compte
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

        bank = BanqueFactice([Person("Josiane", [normalise([0.92, 0.39, 0.0])])])
        processing = chaine(extractor=ExtracteurFactice(self.VECTORS), bank=bank)
        return processing.run_chain(AUDIO)

    def test_une_seule_voix_porte_le_nom(self):
        outcome = self._outcome()
        assert list(outcome.names.values()) == ["Josiane"], outcome.names

    def test_la_voix_la_plus_fournie_garde_les_tours(self):
        """Dix-neuf secondes contre sept : c'est le meilleur extrait des deux."""
        outcome = self._outcome()
        gardee = next(iter(outcome.names))
        assert {t.voice for t in outcome.turns} == {gardee}

    def test_les_repliques_suivent(self):
        """Sinon le compte rendu attribue encore à une voix qui n'existe plus."""
        outcome = self._outcome()
        gardee = next(iter(outcome.names))
        portees = {r.voice for r in outcome.utterances if r.voice is not None}
        assert portees == {gardee}, portees

    def test_deux_personnes_distinctes_restent_deux(self):
        """Le garde-fou : la règle ne doit pas tout replier sur une voix."""
        from greffier.domain.voiceprints import normalise

        bank = BanqueFactice([
            Person("Josiane", [normalise([1.0, 0.02, 0.0])]),
            Person("Michel", [normalise([0.02, 1.0, 0.0])]),
        ])
        vectors = {(0.0, 12.0): [1.0, 0.0, 0.0], (21.0, 28.0): [1.0, 0.0, 0.0],
                    (13.0, 20.0): [0.0, 1.0, 0.0]}
        outcome = chaine(
            extractor=ExtracteurFactice(vectors), bank=bank
        ).run_chain(AUDIO)
        assert sorted(outcome.names.values()) == ["Josiane", "Michel"]


class TestUnEnvoiQuiEchoue:
    """Un envoi qui échoue ne doit pas emporter la chaîne.

    Le 2026-09-10, une réunion de 1 h 42 est restée figée sur la phase
    « envoi » deux heures durant. Tout était déjà sur le disque — la
    transcription, les voix, le compte rendu, gardés avant l'envoi
    justement pour cela — mais l'exception remontait, la phase suivante
    n'était jamais publiée, et l'échec ne se rapportait que par une fenêtre
    modale que personne n'a vue.
    """

    class ExpediteurQuiTombe:
        def send(self, recipient, subject, corps, pieces):
            raise PermissionError("macOS refuse de piloter Outlook.")

    def _outcome(self, log):
        processing = chaine(
            sender=self.ExpediteurQuiTombe(),
            recipient="tanguy@example.org",
            log=log,
        )
        return processing.run_chain(AUDIO)

    def test_la_chaine_va_jusqu_au_bout(self):
        log = JournalFactice()
        self._outcome(log)
        assert log.phases[-1] == Phase.TERMINE.value, log.phases

    def test_la_phase_envoi_ne_reste_pas_la_derniere(self):
        """C'est elle qui mentait : « Envoi du compte rendu… », pour toujours."""
        log = JournalFactice()
        self._outcome(log)
        assert Phase.ENVOI.value in log.phases
        assert log.phases[-1] != Phase.ENVOI.value

    def test_la_raison_est_dite(self):
        outcome = self._outcome(JournalFactice())
        assert any("Outlook" in a for a in outcome.warnings), outcome.warnings
        assert any("greffier envoyer" in a for a in outcome.warnings)

    def test_le_compte_rendu_n_est_pas_annonce_comme_parti(self):
        assert self._outcome(JournalFactice()).envoye is False

    def test_le_compte_rendu_est_bien_la(self):
        assert self._outcome(JournalFactice()).minutes


class TestLigneDesParticipants:
    """La première ligne du compte rendu, celle que tout le monde lit.

    Les deux défauts, sur la réunion du 2026-09-10 : « et 9 voix non nommées »
    là où huit de ces neuf étaient la même personne — corrigé par la réunion
    des homonymes — et un accord de verbe qui écrivait « 1 personne ont parlé »
    en tête d'un compte rendu envoyé par courriel.
    """

    def _line(self, names, entendues: int) -> str:
        from greffier.application.render import context_header

        return context_header(
            "2026-09-10_10h10_reunion", 6120.0, names=names, voix_entendues=entendues
        )

    def test_une_seule_voix_anonyme_est_dite_au_singulier(self):
        line = self._line(["Paul", "Benjamin"], 3)
        assert "et 1 voix non nommée." in line
        assert "non nommées" not in line

    def test_plusieurs_voix_anonymes_au_pluriel(self):
        assert "et 3 voix non nommées." in self._line(["Paul"], 4)

    def test_toutes_nommees_ne_laisse_aucune_traine(self):
        line = self._line(["Paul", "Benjamin"], 2)
        assert "Participants : Paul, Benjamin." in line
        assert "non nomm" not in line

    def test_une_seule_personne_sans_nom_accorde_le_verbe(self):
        """« 1 personne ont parlé » s'écrivait tel quel."""
        line = self._line([], 1)
        assert "1 personne a parlé, non nommée." in line
        assert "ont parlé" not in line

    def test_plusieurs_personnes_sans_nom_accordent_le_verbe(self):
        line = self._line([], 4)
        assert "4 personnes ont parlé" in line

    def test_un_nom_repete_ne_compte_qu_une_fois(self):
        """La réunion des homonymes le fait en amont ; la ligne ne doit pas
        le défaire si un nom arrive deux fois."""
        line = self._line(["Laura", "Laura", "Paul"], 3)
        assert "Participants : Laura, Paul, et 1 voix non nommée." in line
