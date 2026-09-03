"""La chaîne de traitement, jouée avec des doublures.

Aucun audio, aucun modèle, aucun réseau : on vérifie l'enchaînement et les
garde-fous, pas whisper. Les doublures tiennent en quelques lignes parce que les
ports sont des `Protocol` — rien à hériter.
"""

from pathlib import Path

import pytest

from greffier.application.traiter import (
    MOTS_MINIMUM,
    ChaineInterrompue,
    Traitement,
)
from greffier.domaine.modeles import Intervalle, Personne, Phase, Replique, TourDeParole

AUDIO = Path("/tmp/reunion.wav")


class EnregistreurFactice:
    def __init__(self, niveaux=(-30.0, -35.0)):
        self._niveaux = list(niveaux)
        self.prepares = []

    def demarrer(self, destination):
        return 4242

    def arreter(self, processus):
        pass

    def preparer_transcription(self, audio, destination):
        # Le double ne normalise rien : il rend l'audio tel quel, ce qui suffit
        # à vérifier que la chaîne transcrit bien ce qu'on lui a préparé.
        self.prepares.append(audio)
        return audio

    def assembler(self, morceaux, destination):
        return destination

    def niveaux(self, audio):
        return self._niveaux


class TranscripteurFactice:
    def __init__(self, repliques):
        self.repliques = repliques
        self.amorce_recue = None

    def transcrire(self, audio, langue, amorce):
        self.amorce_recue = amorce
        return list(self.repliques)


class DiariseurFactice:
    def __init__(self, tours):
        self._tours = tours

    def decouper(self, audio, personnes):
        return list(self._tours)


class RedacteurFactice:
    def __init__(self):
        self.recu = None

    def rediger(self, transcription):
        self.recu = transcription
        return "# Compte rendu\n\nTout va bien."


class ExpediteurFactice:
    def __init__(self):
        self.envois = []

    def envoyer(self, destinataire, sujet, corps, pieces):
        self.envois.append((destinataire, sujet, corps))


class JournalFactice:
    def __init__(self):
        self.phases = []

    def publier(self, phase, message=""):
        self.phases.append(phase)


def replique(debut, fin, texte):
    return Replique(intervalle=Intervalle(debut, fin), texte=texte)


def tour(debut, fin, voix):
    return TourDeParole(intervalle=Intervalle(debut, fin), voix=voix)


BAVARDAGE = [
    replique(0, 5, "Bonjour à tous, moi c'est Tanguy, on commence par le point recette."),
    replique(6, 12, "La recette est décalée à jeudi, il reste deux anomalies bloquantes."),
    replique(13, 20, "Merci Tanguy. De mon côté le déploiement est prêt depuis lundi."),
    replique(21, 28, "On valide donc jeudi, et on prévient les utilisateurs mercredi soir."),
]
TOURS = [tour(0, 12, "1"), tour(13, 20, "2"), tour(21, 28, "1")]


def chaine(**remplacements):
    defauts = dict(
        enregistreur=EnregistreurFactice(),
        transcripteur=TranscripteurFactice(BAVARDAGE),
        diariseur=DiariseurFactice(TOURS),
        redacteur=RedacteurFactice(),
    )
    defauts.update(remplacements)
    return Traitement(**defauts)


class TestGardeFous:
    def test_un_enregistrement_muet_arrete_tout(self):
        """Le bug du 2026-08-20 : sans ça, un CR était fabriqué puis envoyé."""
        traitement = chaine(enregistreur=EnregistreurFactice(niveaux=(-120.0, -120.0)))
        with pytest.raises(ChaineInterrompue) as arret:
            traitement.executer(AUDIO)
        assert arret.value.phase is Phase.ECHEC
        assert "muet" in arret.value.raison

    def test_une_transcription_vide_n_est_pas_redigee(self):
        transcripteur = TranscripteurFactice([replique(0, 2, "Bonjour.")])
        redacteur = RedacteurFactice()
        traitement = chaine(transcripteur=transcripteur, redacteur=redacteur)
        with pytest.raises(ChaineInterrompue, match="quasi vide"):
            traitement.executer(AUDIO)
        assert redacteur.recu is None, "le rédacteur ne doit pas être appelé"

    def test_le_seuil_de_mots_reste_bas_mais_non_nul(self):
        assert 0 < MOTS_MINIMUM <= 50

    def test_un_micro_muet_avertit_sans_bloquer(self):
        traitement = chaine(enregistreur=EnregistreurFactice(niveaux=(-120.0, -30.0)))
        resultat = traitement.executer(AUDIO)
        assert any("micro" in a for a in resultat.avertissements)
        assert resultat.compte_rendu

    def test_aucun_son_systeme_avertit_sans_bloquer(self):
        traitement = chaine(enregistreur=EnregistreurFactice(niveaux=(-30.0, -120.0)))
        resultat = traitement.executer(AUDIO)
        assert any("système" in a for a in resultat.avertissements)


class TestEnchainement:
    def test_les_phases_se_suivent(self):
        journal = JournalFactice()
        chaine(journal=journal).executer(AUDIO)
        assert journal.phases[0] == Phase.TRANSCRIPTION.value
        assert Phase.LOCUTEURS.value in journal.phases
        assert journal.phases[-1] == Phase.TERMINE.value

    def test_le_vocabulaire_est_transmis_au_transcripteur(self):
        transcripteur = TranscripteurFactice(BAVARDAGE)
        traitement = chaine(transcripteur=transcripteur)
        traitement.amorce = "Vocabulaire : Copernic."
        traitement.executer(AUDIO)
        assert transcripteur.amorce_recue == "Vocabulaire : Copernic."

    def test_sans_redacteur_la_transcription_reste_disponible(self):
        resultat = chaine(redacteur=None).executer(AUDIO)
        assert resultat.repliques and resultat.compte_rendu == ""

    def test_l_envoi_n_a_lieu_qu_avec_un_destinataire(self):
        expediteur = ExpediteurFactice()
        traitement = chaine(expediteur=expediteur)
        assert traitement.executer(AUDIO).envoye is False
        traitement.destinataire = "moi@exemple.fr"
        assert traitement.executer(AUDIO).envoye is True
        assert expediteur.envois[0][0] == "moi@exemple.fr"

    def test_on_peut_traiter_sans_envoyer(self):
        expediteur = ExpediteurFactice()
        traitement = chaine(expediteur=expediteur)
        traitement.destinataire = "moi@exemple.fr"
        resultat = traitement.executer(AUDIO, envoyer=False)
        assert resultat.compte_rendu and not resultat.envoye and not expediteur.envois


class TestAttributionDesVoix:
    def test_chaque_replique_recoit_la_voix_dominante(self):
        resultat = chaine().executer(AUDIO)
        assert [r.voix for r in resultat.repliques] == ["1", "1", "2", "1"]

    def test_l_auto_presentation_nomme_le_locuteur(self):
        """« moi c'est Tanguy » désigne celui qui parle."""
        resultat = chaine().executer(AUDIO)
        assert resultat.noms["1"] == "Tanguy"

    def test_le_vocabulaire_metier_n_est_pas_pris_pour_un_prenom(self):
        transcripteur = TranscripteurFactice([
            replique(0, 6, "Merci Copernic pour la démonstration de ce matin, c'était clair."),
            replique(7, 14, "On enchaîne sur le sujet suivant, à savoir la reprise des données."),
            replique(15, 22, "Très bien, je note que la reprise démarre la semaine prochaine."),
        ])
        traitement = chaine(transcripteur=transcripteur)
        traitement.pas_des_prenoms = frozenset({"copernic"})
        resultat = traitement.executer(AUDIO)
        assert "Copernic" not in resultat.noms.values()
        assert "Copernic" not in resultat.propositions.values()

    def test_la_transcription_rendue_porte_les_noms_et_les_horaires(self):
        redacteur = RedacteurFactice()
        chaine(redacteur=redacteur).executer(AUDIO)
        assert "[Tanguy]" in redacteur.recu
        assert "00:00" in redacteur.recu
        # Une voix sans nom reste identifiée, jamais inventée.
        assert "[Personne 2]" in redacteur.recu


class ExtracteurFactice:
    """Rend une empreinte par intervalle, dictée par la voix attendue."""

    def __init__(self, vecteurs):
        self.vecteurs = vecteurs
        self.appels = []

    def extraire_intervalles(self, audio, intervalles):
        from greffier.domaine.empreintes import normaliser

        self.appels.append(list(intervalles))
        cle = (intervalles[0].debut, intervalles[0].fin)
        return [normaliser(self.vecteurs[cle], duree_source=i.duree) for i in intervalles]


class BanqueFactice:
    def __init__(self, personnes):
        self._personnes = personnes
        self.ajouts = []

    def personnes(self):
        return list(self._personnes)

    def enregistrer(self, nom, empreinte):
        self.ajouts.append(nom)


class TestBanqueDeVoix:
    def test_une_voix_connue_est_nommee_sans_qu_on_la_nomme(self):
        """Le cœur du besoin : « Josiane » et non « Personne 2 »."""
        from greffier.domaine.empreintes import normaliser

        vecteurs = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        banque = BanqueFactice([Personne("Josiane", [normaliser([0.02, 1.0, 0.0])])])
        traitement = chaine(extracteur=ExtracteurFactice(vecteurs), banque=banque)
        resultat = traitement.executer(AUDIO)
        assert resultat.noms["2"] == "Josiane"

    def test_un_desaccord_entre_banque_et_reunion_est_signale(self):
        """La banque a été validée par un humain : elle prime, mais on le dit."""
        from greffier.domaine.empreintes import normaliser

        vecteurs = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        banque = BanqueFactice([Personne("Michel", [normaliser([1.0, 0.02, 0.0])])])
        traitement = chaine(extracteur=ExtracteurFactice(vecteurs), banque=banque)
        resultat = traitement.executer(AUDIO)
        assert resultat.noms["1"] == "Michel"
        assert any("Michel" in a and "Tanguy" in a for a in resultat.avertissements)

    def test_une_banque_vide_ne_gene_pas(self):
        vecteurs = {(0.0, 12.0): [1.0, 0.0, 0.0], (13.0, 20.0): [0.0, 1.0, 0.0],
                    (21.0, 28.0): [1.0, 0.0, 0.0]}
        traitement = chaine(extracteur=ExtracteurFactice(vecteurs), banque=BanqueFactice([]))
        assert traitement.executer(AUDIO).noms["1"] == "Tanguy"


class TestLectureDuResultat:
    def test_les_fragments_ne_sont_pas_des_participants(self):
        """La segmentation laisse une traîne de fragments d'une seconde."""
        resultat = chaine().executer(AUDIO)
        resultat.tours = resultat.tours + [tour(29, 29.5, "bruit")]
        assert "bruit" in resultat.temps_de_parole()
        assert "bruit" not in resultat.voix_significatives()

    def test_le_temps_de_parole_va_du_plus_bavard_au_moins(self):
        resultat = chaine().executer(AUDIO)
        durees = list(resultat.temps_de_parole().values())
        assert durees == sorted(durees, reverse=True)


class TestFiabilite:
    def test_la_couverture_dit_ce_qui_manque(self):
        """25 s de texte sur 28 s de parole : seules les respirations manquent."""
        resultat = chaine().executer(AUDIO)
        assert resultat.couverture == pytest.approx(25 / 28, abs=0.01)

    def test_un_trou_de_transcription_est_repere(self):
        transcripteur = TranscripteurFactice([
            replique(0, 10, "On commence par le point sur la recette de la semaine."),
            replique(120, 130, "Voilà, je crois qu'on a fait le tour des sujets prévus."),
        ])
        diariseur = DiariseurFactice([tour(0, 10, "1"), tour(120, 130, "2")])
        resultat = chaine(transcripteur=transcripteur, diariseur=diariseur).executer(AUDIO)
        trous = resultat.trous(minimum=8)
        assert any(t.duree > 100 for t in trous)

    def test_le_redacteur_est_prevenu_de_ce_qui_manque(self):
        """Sans cet en-tête, le compte rendu présente comme complet un texte
        qui ne l'est pas."""
        from greffier.application.restituer import entete_fiabilite

        transcripteur = TranscripteurFactice([
            replique(0, 10, "On commence par le point sur la recette de la semaine."),
            replique(120, 130, "Voilà, je crois qu'on a fait le tour des sujets prévus."),
        ])
        diariseur = DiariseurFactice([tour(0, 10, "1"), tour(120, 130, "2")])
        redacteur = RedacteurFactice()
        chaine(transcripteur=transcripteur, diariseur=diariseur,
               redacteur=redacteur).executer(AUDIO)
        assert "Fiabilité de la transcription" in redacteur.recu
        assert "ne comble" in redacteur.recu
        assert entete_fiabilite(chaine().executer(AUDIO)) == "", \
            "une transcription complète ne doit pas être affublée d'un avertissement"


class TestEnteteContexte:
    """La date de la réunion, dite au rédacteur.

    Sans elle, le rédacteur prend la date du traitement : une réunion du 25
    s'est retrouvée datée du 26 dans un compte rendu réel.
    """

    def test_la_date_et_l_heure_sortent_du_nom_de_fichier(self) -> None:
        from greffier.application.restituer import entete_contexte

        entete = entete_contexte("2026-08-25_14h33_reunion-essai-reel")
        assert "25 août 2026" in entete
        assert "14 h 33" in entete

    def test_le_redacteur_est_prie_de_ne_pas_prendre_la_date_du_jour(self) -> None:
        from greffier.application.restituer import entete_contexte

        assert "jamais celle du jour" in entete_contexte("2026-01-09_09h05_point")

    def test_le_mois_est_en_francais_sans_dependre_de_la_locale(self) -> None:
        from greffier.application.restituer import entete_contexte

        assert "9 janvier 2026" in entete_contexte("2026-01-09_09h05_point")
        assert "1 décembre 2025" in entete_contexte("2025-12-01_08h00_point")

    def test_la_duree_est_rendue_en_heures_et_minutes(self) -> None:
        from greffier.application.restituer import entete_contexte

        assert "durée 1 h 00." in entete_contexte("2026-08-25_14h33_x", 3606)
        assert "durée 2 h 05." in entete_contexte("2026-08-25_14h33_x", 7500)

    def test_une_reunion_courte_est_dite_en_minutes(self) -> None:
        from greffier.application.restituer import entete_contexte

        assert "durée 12 min." in entete_contexte("2026-08-25_14h33_x", 720)

    def test_une_date_sans_heure_reste_valide(self) -> None:
        from greffier.application.restituer import entete_contexte

        entete = entete_contexte("2026-08-25_import-telephone")
        assert "25 août 2026" in entete
        assert " h " not in entete.split("2026")[1].split(".")[0]

    def test_l_heure_de_fin_se_deduit_de_la_duree(self) -> None:
        """Demandé à l'usage : le compte rendu doit dire début et fin."""
        from greffier.application.restituer import entete_contexte

        entete = entete_contexte("2026-09-02_16h46_reunion", 1020.0)
        assert "de 16 h 46 à 17 h 03" in entete

    def test_les_participants_nommes_sont_listes(self) -> None:
        from greffier.application.restituer import entete_contexte

        entete = entete_contexte("2026-09-02_16h46_x", 600.0,
                                 noms=["Paul", "Camilo"], voix_entendues=2)
        assert "Participants : Paul, Camilo." in entete

    def test_les_voix_non_nommees_sont_comptees_a_part(self) -> None:
        from greffier.application.restituer import entete_contexte

        entete = entete_contexte("2026-09-02_16h46_x", 600.0,
                                 noms=["Paul"], voix_entendues=3)
        assert "Paul, et 2 voix non nommées." in entete

    def test_sans_aucun_nom_on_dit_combien_de_personnes(self) -> None:
        """Constaté : un compte rendu ne disait pas du tout qui était présent."""
        from greffier.application.restituer import entete_contexte

        entete = entete_contexte("2026-09-02_17h04_x", 190.0, voix_entendues=3)
        assert "3 personnes ont parlé, aucune nommée." in entete

    def test_la_ligne_est_dictee_mot_pour_mot(self) -> None:
        """Deux comptes rendus du même jour la formataient différemment."""
        from greffier.application.restituer import entete_contexte

        assert "telle quelle" in entete_contexte("2026-09-02_17h04_x", 190.0)

    def test_un_nom_sans_date_ne_fait_rien_inventer(self) -> None:
        from greffier.application.restituer import entete_contexte

        assert entete_contexte("import-sans-date") == ""

    def test_une_duree_nulle_n_est_pas_annoncee(self) -> None:
        from greffier.application.restituer import entete_contexte

        assert "Durée" not in entete_contexte("2026-08-25_14h33_x", 0)


class TestEnteteMateriel:
    """Un branchement en cours de réunion change ce que le compte rendu peut dire."""

    def test_sans_evenement_rien_n_est_ajoute(self) -> None:
        from greffier.application.restituer import entete_materiel

        assert entete_materiel([]) == ""

    def test_chaque_constat_est_repris(self) -> None:
        from greffier.application.restituer import entete_materiel

        entete = entete_materiel(["casque branché", "casque débranché"])
        assert "- casque branché" in entete
        assert "- casque débranché" in entete

    def test_le_redacteur_est_averti_qu_un_echange_peut_etre_a_sens_unique(self) -> None:
        # C'est le vrai risque : la voix de la personne qui enregistre manque au
        # début, et le compte rendu présente comme complet un échange dont il
        # n'a entendu qu'un côté.
        from greffier.application.restituer import entete_materiel

        entete = entete_materiel(["casque branché en cours de réunion"])
        assert "un seul côté" in entete
        assert "recollés" in entete


class TestDureeLisible:
    def test_sous_la_minute_on_donne_les_secondes(self) -> None:
        # « 0 min » serait faux : un extrait de trente secondes existe, et le
        # rédacteur doit savoir qu'il n'a qu'un extrait.
        from greffier.application.restituer import entete_contexte

        assert "30 s" in entete_contexte("extrait", 30.5)

    def test_un_fichier_sans_date_n_annonce_pas_une_date_absente(self) -> None:
        # Sinon le compte rendu s'ouvre sur « Date non précisée ».
        from greffier.application.restituer import entete_contexte

        entete = entete_contexte("import-telephone", 720)
        assert "Date" not in entete
        assert "12 min" in entete

    def test_sans_date_ni_duree_rien_n_est_dit(self) -> None:
        from greffier.application.restituer import entete_contexte

        assert entete_contexte("import-telephone", 0) == ""


class TestMiseANiveauAvantTranscription:
    """Un signal faible ne donne pas une transcription pauvre, il en invente une.

    Mesuré sur un enregistrement réel de treize secondes, micro à -43 dB : le
    modèle a rendu « Merci d'avoir regardé cette vidéo ! » là où la personne
    disait « Test, test de réunion ». Le même fichier normalisé rend la bonne
    phrase, donc la chaîne prépare l'audio avant de le transcrire.
    """

    def test_l_audio_est_prepare_avant_d_etre_transcrit(self, tmp_path):
        enregistreur = EnregistreurFactice()
        traitement = chaine(enregistreur=enregistreur)
        audio = tmp_path / "reunion.wav"
        audio.write_bytes(b"RIFF----WAVEfmt ")
        traitement.executer(audio, envoyer=False)
        assert enregistreur.prepares == [audio]


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
            def enregistrer(self, reunion):
                deposees.append(reunion)
                return tmp_path / "reunions/essai.json"

        resultat = chaine(depot=DepotEspion()).executer(AUDIO)
        assert deposees, "la chaîne doit déposer la réunion"
        assert resultat.fichier_maitre == tmp_path / "reunions/essai.json"

    def test_la_transcription_et_le_compte_rendu_sont_ecrits(self, tmp_path):
        resultat = chaine(
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
        ).executer(AUDIO)
        assert resultat.transcription_ecrite is not None
        assert resultat.transcription_ecrite.exists()
        assert resultat.compte_rendu_ecrit is not None
        assert resultat.compte_rendu_ecrit.read_text(encoding="utf-8")

    def test_garde_avant_envoi(self, tmp_path):
        """Un serveur de courriel indisponible ne doit pas faire perdre
        une heure de transcription et sa rédaction."""

        class ExpediteurQuiTombe:
            def envoyer(self, *_args, **_options):
                raise RuntimeError("serveur injoignable")

        traitement = chaine(
            dossier_transcriptions=tmp_path / "transcriptions",
            dossier_comptes_rendus=tmp_path / "comptes-rendus",
            expediteur=ExpediteurQuiTombe(),
            destinataire="moi@exemple.fr",
        )
        with pytest.raises(Exception, match="injoignable"):
            traitement.executer(AUDIO)
        assert (tmp_path / "comptes-rendus").exists(), "le compte rendu survit à l'envoi"

    def test_sans_dossier_la_chaine_reste_utilisable(self):
        """Les tests d'intégration s'en servent en mémoire, sans rien écrire."""
        resultat = chaine().executer(AUDIO)
        assert resultat.transcription_ecrite is None
        assert resultat.compte_rendu_ecrit is None
        assert resultat.fichier_maitre is None
