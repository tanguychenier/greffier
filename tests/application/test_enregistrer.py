"""La machine à états de l'enregistrement, sans carte son."""

from datetime import UTC, datetime, timedelta

import pytest

from greffier.application.enregistrer import Enregistrement, Etat, _identifiant
from greffier.domaine.modeles import Phase


class EnregistreurFactice:
    def __init__(self, pid=4242):
        self.pid = pid
        self.demarre = []
        self.arretes = []
        self.assembles = []

    def demarrer(self, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"RIFF----WAVEfmt ")
        self.demarre.append(destination)
        return self.pid

    def arreter(self, processus):
        self.arretes.append(processus)

    def assembler(self, morceaux, destination):
        self.assembles.append(list(morceaux))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"RIFF----WAVEfmt " * len(morceaux))
        return destination

    def niveaux(self, audio):
        return [-30.0]


@pytest.fixture
def enregistreur():
    return EnregistreurFactice()


@pytest.fixture
def machine(tmp_path, monkeypatch, enregistreur):
    # Le PID factice doit paraître vivant : c'est lui qui décide si un
    # enregistrement est en cours. Celui du processus de test aussi, puisque
    # c'est lui qui porte le traitement quand la chaîne publie son avancement.
    import os

    monkeypatch.setattr(
        "greffier.application.enregistrer._vivant",
        lambda pid: pid in (4242, os.getpid()),
    )
    return Enregistrement(
        enregistreur=enregistreur,
        dossier_audio=tmp_path / "enregistrements",
        fichier_etat=tmp_path / "etat.json",
    )


class TestIdentifiant:
    def test_la_date_d_abord_pour_que_ca_se_trie(self):
        quand = datetime(2026, 8, 24, 14, 30)
        assert _identifiant("Point Copernic", quand) == "2026-08-24_14h30_point-copernic"

    def test_les_accents_et_symboles_disparaissent(self):
        quand = datetime(2026, 8, 24, 9, 5)
        assert _identifiant("Réunion #4 (été)", quand) == "2026-08-24_09h05_reunion-4-ete"

    def test_un_nom_vide_reste_utilisable(self):
        assert _identifiant("???", datetime(2026, 1, 1, 0, 0)).endswith("_reunion")


class TestCycle:
    def test_au_repos_rien_n_est_en_cours(self, machine):
        assert machine.lire().phase is Phase.REPOS

    def test_demarrer_puis_arreter(self, machine):
        etat = machine.demarrer("point recette")
        assert etat.phase is Phase.ENREGISTREMENT
        assert machine.lire().phase is Phase.ENREGISTREMENT
        arrete = machine.arreter()
        assert arrete.phase is Phase.FINALISATION
        assert machine.enregistreur.arretes == [4242]

    def test_l_etat_survit_a_un_autre_processus(self, machine, tmp_path):
        """Deux commandes séparées d'une heure : l'état est sur le disque."""
        machine.demarrer("copil")
        autre = Enregistrement(
            enregistreur=EnregistreurFactice(),
            dossier_audio=tmp_path / "enregistrements",
            fichier_etat=tmp_path / "etat.json",
        )
        assert autre.lire().nom == "copil"
        assert autre.lire().phase is Phase.ENREGISTREMENT

    def test_deux_enregistrements_a_la_fois_sont_refuses(self, machine):
        machine.demarrer("premier")
        with pytest.raises(RuntimeError, match="déjà en cours"):
            machine.demarrer("second")

    def test_arreter_sans_rien_enregistrer_est_une_erreur(self, machine):
        with pytest.raises(RuntimeError, match="Aucun enregistrement"):
            machine.arreter()

    def test_un_enregistrement_vide_est_signale(self, machine, monkeypatch):
        machine.demarrer("muet")
        etat = machine.lire()
        # L'audio capté vit dans les morceaux : c'est là qu'il faut regarder.
        for morceau in etat.morceaux:
            morceau.write_bytes(b"")
        with pytest.raises(RuntimeError, match="vide"):
            machine.arreter()

    def test_le_premier_morceau_est_numerote(self, machine):
        etat = machine.demarrer("point")
        assert len(etat.morceaux) == 1
        assert etat.morceaux[0].name.endswith("-01.wav")
        assert etat.morceaux[0] != etat.audio


class TestMaterielQuiChange:
    """Brancher un casque en cours de réunion coupe la capture en morceaux."""

    def test_reprendre_ouvre_un_morceau_suivant(self, machine):
        machine.demarrer("point")
        etat = machine.reprendre("Jabra branché en cours de réunion")
        assert len(etat.morceaux) == 2
        assert etat.morceaux[1].name.endswith("-02.wav")

    def test_la_raison_est_conservee_pour_le_compte_rendu(self, machine):
        machine.demarrer("point")
        machine.reprendre("Jabra branché en cours de réunion")
        assert machine.lire().evenements == ["Jabra branché en cours de réunion"]

    def test_l_ancienne_capture_est_arretee_avant_la_nouvelle(self, machine, enregistreur):
        machine.demarrer("point")
        machine.reprendre("changement")
        # Un ffmpeg laissé vivant tiendrait le périphérique et empêcherait
        # le suivant de l'ouvrir.
        assert len(enregistreur.arretes) == 1
        assert len(enregistreur.demarre) == 2

    def test_plusieurs_changements_s_empilent(self, machine):
        machine.demarrer("point")
        for rang in range(3):
            machine.reprendre(f"changement {rang}")
        etat = machine.lire()
        assert len(etat.morceaux) == 4
        assert etat.morceaux[-1].name.endswith("-04.wav")
        assert len(etat.evenements) == 3

    def test_l_arret_recolle_tous_les_morceaux(self, machine, enregistreur):
        machine.demarrer("point")
        machine.reprendre("changement")
        etat = machine.arreter()
        assert len(enregistreur.assembles) == 1
        assert len(enregistreur.assembles[0]) == 2
        assert [m.name for m in enregistreur.assembles[0]] == [
            f"{etat.identifiant}-01.wav", f"{etat.identifiant}-02.wav",
        ]
        # Après recollage, l'état ne connaît plus qu'un fichier : le final.
        assert etat.morceaux == [etat.audio]

    def test_les_morceaux_sont_effaces_apres_recollage(self, machine):
        machine.demarrer("point")
        avant = machine.reprendre("changement").morceaux
        machine.arreter()
        assert not any(m.exists() for m in avant)

    def test_signaler_n_ouvre_aucun_morceau(self, machine):
        machine.demarrer("point")
        etat = machine.signaler("plus aucun micro disponible")
        assert len(etat.morceaux) == 1
        assert etat.evenements == ["plus aucun micro disponible"]

    def test_reprendre_hors_enregistrement_est_une_erreur(self, machine):
        with pytest.raises(RuntimeError, match="Aucun enregistrement"):
            machine.reprendre("changement")


class TestRobustesse:
    def test_un_processus_mort_ne_passe_pas_pour_vivant(self, machine, monkeypatch):
        """Redémarrage pendant une réunion : l'état ment, les processus non."""
        machine.demarrer("interrompue")
        monkeypatch.setattr("greffier.application.enregistrer._vivant", lambda pid: False)
        etat = machine.lire()
        assert etat.phase is Phase.ECHEC
        assert "conservé" in etat.message

    def test_un_fichier_d_etat_abime_ne_bloque_pas(self, machine):
        machine.fichier_etat.parent.mkdir(parents=True, exist_ok=True)
        machine.fichier_etat.write_text("{ pas du json", encoding="utf-8")
        assert machine.lire().phase is Phase.REPOS

    def test_la_chaine_publie_son_avancement_dans_le_meme_fichier(self, machine):
        """C'est ce que lira l'icône de la barre, sans rien calculer."""
        machine.demarrer("copil")
        machine.publier("transcription", "Transcription…")
        etat = machine.lire()
        assert etat.phase is Phase.TRANSCRIPTION
        assert etat.message == "Transcription…"
        assert etat.nom == "copil", "publier ne doit pas perdre le reste de l'état"

    def test_le_chronometre_part_du_debut(self):
        etat = Etat(debut=datetime.now(UTC) - timedelta(minutes=5))
        assert 290 < etat.secondes < 310


class TestInterruption:
    def test_on_interrompt_le_traitement_pas_l_audio(self, machine, monkeypatch):
        tues = []
        monkeypatch.setattr("greffier.application.enregistrer._tuer_arbre", tues.append)
        machine.demarrer("copil")
        machine.publier("transcription", "Transcription…")
        etat = machine.interrompre()
        assert etat.phase is Phase.INTERROMPU
        assert "conservé" in etat.message
        assert tues, "le processus de traitement doit être arrêté"

    def test_interrompre_sans_traitement_est_une_erreur(self, machine):
        with pytest.raises(RuntimeError, match="Aucun traitement"):
            machine.interrompre()

    def test_publier_retient_le_processus_courant(self, machine):
        """C'est lui qui porte la transcription puis la rédaction."""
        import os

        machine.demarrer("copil")
        machine.publier("redaction", "Rédaction…")
        assert machine.lire().pid == os.getpid()


class TestPause:
    """Une interruption en réunion ne doit pas obliger à clore la séance.

    Sans pause, il fallait arrêter, ce qui lance le traitement, puis relancer :
    deux enregistrements et deux comptes rendus pour une seule réunion.
    """

    def test_suspendre_arrete_la_capture_sans_clore(self, machine, enregistreur):
        machine.demarrer("point")
        etat = machine.suspendre()
        assert etat.phase is Phase.PAUSE
        assert etat.pid is None
        assert len(enregistreur.arretes) == 1
        # Le morceau déjà capté reste, rien n'est recollé pour l'instant.
        assert len(etat.morceaux) == 1

    def test_relancer_ouvre_un_morceau_de_plus(self, machine):
        machine.demarrer("point")
        machine.suspendre()
        etat = machine.relancer()
        assert etat.phase is Phase.ENREGISTREMENT
        assert len(etat.morceaux) == 2
        assert etat.morceaux[1].name.endswith("-02.wav")

    def test_le_temps_de_pause_ne_compte_pas_dans_la_duree(self, machine, monkeypatch):
        from datetime import UTC, datetime, timedelta

        machine.demarrer("point")
        etat = machine.suspendre()
        # Cinq minutes plus tard, on repart.
        etat.suspendu_le = datetime.now(UTC) - timedelta(minutes=5)
        machine.ecrire(etat)
        repris = machine.relancer()
        assert repris.pause_totale >= 300
        # Le chronomètre montre le temps enregistré, pas le temps écoulé.
        assert repris.secondes < 60

    def test_arreter_depuis_la_pause_recolle_tout(self, machine, enregistreur):
        machine.demarrer("point")
        machine.suspendre()
        machine.relancer()
        machine.suspendre()
        etat = machine.arreter()
        assert len(enregistreur.assembles[0]) == 2
        assert etat.morceaux == [etat.audio]

    def test_suspendre_hors_enregistrement_est_une_erreur(self, machine):
        with pytest.raises(RuntimeError, match="Aucun enregistrement"):
            machine.suspendre()

    def test_relancer_sans_pause_est_une_erreur(self, machine):
        machine.demarrer("point")
        with pytest.raises(RuntimeError, match="pas en pause"):
            machine.relancer()

    def test_la_pause_survit_a_la_relecture_de_l_etat(self, machine):
        machine.demarrer("point")
        machine.suspendre()
        # L'interface relit le fichier : la pause doit y être.
        assert machine.lire().phase is Phase.PAUSE
        assert machine.lire().suspendu_le is not None
