"""Le matériel audio change pendant la réunion : que doit faire l'outil ?

Onze situations, toutes éprouvées sans brancher un câble. Celle du 25 août 2026
est nommée : casque branché après le début, voix de la personne qui enregistrait
captée 12 dB trop bas, puis effacée au mixage. Rien ne l'avait signalé.
"""

from __future__ import annotations

import pytest

from greffier.domaine.peripheriques import (
    Action,
    Materiel,
    Peripherique,
    Veille,
    casque_present,
    micro_conseille,
)

JABRA_MICRO = Peripherique("Jabra EVOLVE 30 II", "jabra:1", entrees=1)
JABRA_SORTIE = Peripherique("Jabra EVOLVE 30 II", "jabra:2", sorties=2)
MICRO_INTEGRE = Peripherique("Micro MacBook Pro", "BuiltInMicrophoneDevice", entrees=1)
HP_INTEGRES = Peripherique("Haut-parleurs MacBook Pro", "BuiltInSpeakerDevice", sorties=2)
BLACKHOLE = Peripherique("BlackHole 2ch", "BlackHole2ch_UID", entrees=2, sorties=2)
ECRAN = Peripherique("HP E273m", "220E6E34", sorties=2)
REALTEK = Peripherique("Realtek USB2.0 Audio", "realtek:1", entrees=2)
AGREGE = Peripherique("Reunion Entree", "com.reunions.entree", entrees=3, sorties=2)

SANS_CASQUE = Materiel((BLACKHOLE, HP_INTEGRES, MICRO_INTEGRE, AGREGE))
AVEC_CASQUE = Materiel((BLACKHOLE, HP_INTEGRES, JABRA_MICRO, JABRA_SORTIE, MICRO_INTEGRE, AGREGE))


@pytest.fixture
def veille() -> Veille:
    return Veille(micro_voulu="Jabra EVOLVE 30 II")


class TestLeScenarioDu25Aout:
    """Le casque est branché après le début de l'enregistrement."""

    def test_l_outil_reconstruit_et_reprend_la_capture(self, veille: Veille) -> None:
        decision = veille.examiner(SANS_CASQUE, AVEC_CASQUE)
        assert decision.action is Action.RECONSTRUIRE
        assert decision.micro == "Jabra EVOLVE 30 II"

    def test_il_dit_que_le_debut_de_la_reunion_n_a_pas_eu_le_casque(
        self, veille: Veille
    ) -> None:
        decision = veille.examiner(SANS_CASQUE, AVEC_CASQUE)
        assert "vient d'être branché" in decision.raison
        assert "le début de la réunion ne l'a pas eu" in decision.raison

    def test_l_audio_deja_capte_est_marque_suspect(self, veille: Veille) -> None:
        # Ce qui a été enregistré avant le branchement est sous-exploitable :
        # le compte rendu doit pouvoir le dire.
        assert veille.examiner(SANS_CASQUE, AVEC_CASQUE).audio_suspect

    def test_l_evenement_est_conserve_pour_le_journal(self, veille: Veille) -> None:
        veille.examiner(SANS_CASQUE, AVEC_CASQUE)
        assert veille.evenements == ["Jabra EVOLVE 30 II branché en cours de réunion"]


class TestCasqueDebranche:
    def test_la_capture_repart_sur_le_micro_integre(self, veille: Veille) -> None:
        decision = veille.examiner(AVEC_CASQUE, SANS_CASQUE)
        assert decision.action is Action.RECONSTRUIRE
        assert decision.micro == "Micro MacBook Pro"
        assert "débranché" in decision.raison

    def test_sans_aucun_micro_de_repli_l_outil_alerte_sans_couper(
        self, veille: Veille
    ) -> None:
        # Débrancher le casque quand il n'y a rien d'autre : couper
        # l'enregistrement perdrait aussi la voix des autres, qui arrive par
        # BlackHole. On prévient, on continue.
        rien = Materiel((BLACKHOLE, HP_INTEGRES, AGREGE))
        decision = veille.examiner(AVEC_CASQUE, rien)
        assert decision.action is Action.ALERTER
        assert "ta voix n'est plus enregistrée" in decision.raison

    def test_blackhole_n_est_jamais_choisi_comme_micro(self, veille: Veille) -> None:
        # BlackHole capte la sortie du système, jamais une bouche. Le prendre
        # pour micro produirait une réunion où personne n'est enregistré.
        rien = Materiel((BLACKHOLE, HP_INTEGRES, AGREGE))
        assert veille.examiner(AVEC_CASQUE, rien).micro == ""


class TestBranchementsSuccessifs:
    def test_debranche_puis_rebranche_revient_au_casque(self, veille: Veille) -> None:
        premier = veille.examiner(AVEC_CASQUE, SANS_CASQUE)
        second = veille.examiner(SANS_CASQUE, AVEC_CASQUE)
        assert premier.micro == "Micro MacBook Pro"
        assert second.micro == "Jabra EVOLVE 30 II"
        assert len(veille.evenements) == 2

    def test_un_va_et_vient_repete_reste_coherent(self, veille: Veille) -> None:
        for _ in range(3):
            assert veille.examiner(AVEC_CASQUE, SANS_CASQUE).action is Action.RECONSTRUIRE
            assert veille.examiner(SANS_CASQUE, AVEC_CASQUE).action is Action.RECONSTRUIRE
        assert len(veille.evenements) == 6

    def test_un_second_casque_branche_est_pris_si_le_premier_manque(self) -> None:
        veille = Veille(micro_voulu="Casque absent")
        autre = Peripherique("Poly Blackwire", "poly:1", entrees=1)
        apres = Materiel((BLACKHOLE, MICRO_INTEGRE, autre, AGREGE))
        decision = veille.examiner(SANS_CASQUE, apres)
        assert decision.action is Action.RECONSTRUIRE
        # Un micro externe mono passe devant le micro intégré : c'est la forme
        # d'un micro de casque, donc celui dans lequel on parle.
        assert decision.micro == "Poly Blackwire"


class TestChangementsSansEffet:
    def test_un_materiel_identique_ne_declenche_rien(self, veille: Veille) -> None:
        assert veille.examiner(AVEC_CASQUE, AVEC_CASQUE).action is Action.RIEN

    def test_brancher_un_ecran_ne_touche_pas_a_la_capture(self, veille: Veille) -> None:
        apres = Materiel((*AVEC_CASQUE.peripheriques, ECRAN))
        assert veille.examiner(AVEC_CASQUE, apres).action is Action.RIEN

    def test_le_casque_reste_present_quand_seule_la_sortie_bouge(
        self, veille: Veille
    ) -> None:
        # Le Jabra expose micro et écouteurs séparément : perdre la sortie ne
        # doit pas faire croire que le micro a disparu.
        sans_sortie = Materiel(
            tuple(p for p in AVEC_CASQUE.peripheriques if p != JABRA_SORTIE)
        )
        assert veille.examiner(AVEC_CASQUE, sans_sortie).action is Action.RIEN

    def test_aucun_evenement_n_est_note_sans_changement(self, veille: Veille) -> None:
        veille.examiner(AVEC_CASQUE, AVEC_CASQUE)
        apres = Materiel((*AVEC_CASQUE.peripheriques, ECRAN))
        veille.examiner(AVEC_CASQUE, apres)
        assert veille.evenements == []


class TestAvantDeDemarrer:
    def test_le_casque_habituel_est_pris_quand_il_est_la(self) -> None:
        assert micro_conseille(AVEC_CASQUE, "Jabra EVOLVE 30 II") == "Jabra EVOLVE 30 II"

    def test_sans_casque_on_prend_le_micro_integre_plutot_que_de_refuser(self) -> None:
        # Refuser de démarrer parce que le casque habituel manque ferait perdre
        # la réunion entière. Mieux vaut enregistrer avec ce qu'on a.
        assert micro_conseille(SANS_CASQUE, "Jabra EVOLVE 30 II") == "Micro MacBook Pro"

    def test_sans_le_moindre_micro_rien_n_est_conseille(self) -> None:
        assert micro_conseille(Materiel((BLACKHOLE, HP_INTEGRES)), "Jabra") == ""

    def test_la_presence_du_casque_se_verifie_sur_son_entree(self) -> None:
        assert casque_present(AVEC_CASQUE, "Jabra EVOLVE 30 II")
        assert not casque_present(SANS_CASQUE, "Jabra EVOLVE 30 II")

    def test_un_peripherique_de_sortie_seule_n_est_pas_un_casque(self) -> None:
        sortie_seule = Materiel((JABRA_SORTIE, HP_INTEGRES))
        assert not casque_present(sortie_seule, "Jabra EVOLVE 30 II")


class TestChoixDuMicroDeRepli:
    """Un mauvais repli donne un enregistrement muet, pas une simple gêne."""

    def test_une_entree_ligne_stereo_ne_bat_pas_le_micro_integre(self) -> None:
        # « Realtek USB2.0 Audio », deux entrées : c'est l'entrée ligne d'une
        # station d'accueil ou d'un écran, sur laquelle rien n'est branché.
        # La préférer au micro du portable donnait un enregistrement muet.
        # Constaté en débranchant un casque sur un poste réel.
        materiel = Materiel((BLACKHOLE, MICRO_INTEGRE, REALTEK, AGREGE))
        assert micro_conseille(materiel, "Casque absent") == "Micro MacBook Pro"

    def test_un_micro_externe_mono_passe_devant_le_micro_integre(self) -> None:
        casque = Peripherique("Poly Blackwire", "poly:1", entrees=1)
        materiel = Materiel((BLACKHOLE, MICRO_INTEGRE, casque, AGREGE))
        assert micro_conseille(materiel, "Casque absent") == "Poly Blackwire"

    def test_une_entree_ligne_sert_quand_il_n_y_a_rien_d_autre(self) -> None:
        # Faute de mieux, mieux vaut tenter que ne rien capter du tout.
        materiel = Materiel((BLACKHOLE, REALTEK, AGREGE))
        assert micro_conseille(materiel, "Casque absent") == "Realtek USB2.0 Audio"

    def test_l_agrege_n_est_jamais_propose_meme_seul(self) -> None:
        assert micro_conseille(Materiel((AGREGE, BLACKHOLE)), "Casque absent") == ""


class TestChoixParEcoute:
    """Un micro branché, reconnu, réglé au maximum, et pourtant muet.

    Mesuré sur un poste réel : casque Jabra à -78 dB parce que le bouton de
    sourdine de son boîtier était enfoncé, micro intégré à -58 dB dans le même
    silence. Greffier retenait le casque, enregistrait une heure de silence, puis
    accusait l'autorisation micro.
    """

    def test_le_micro_qui_capte_le_mieux_est_retenu(self) -> None:
        from greffier.domaine.peripheriques import choisir_par_ecoute

        choix = choisir_par_ecoute(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choix is not None
        assert choix.nom == "Micro MacBook Pro"
        assert not choix.tous_muets

    def test_le_micro_ecarte_est_conserve_pour_l_expliquer(self) -> None:
        from greffier.domaine.peripheriques import choisir_par_ecoute

        choix = choisir_par_ecoute(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choix is not None
        assert choix.ecartes == (("Jabra EVOLVE 30 II", -78.5),)

    def test_quand_tous_sont_muets_on_le_dit(self) -> None:
        # Le cas où l'autorisation micro manque vraiment, ou où tout est coupé.
        from greffier.domaine.peripheriques import choisir_par_ecoute

        choix = choisir_par_ecoute({"Jabra": -78.5, "Micro MacBook Pro": -80.0})
        assert choix is not None and choix.tous_muets

    def test_sans_candidat_rien_n_est_choisi(self) -> None:
        from greffier.domaine.peripheriques import choisir_par_ecoute

        assert choisir_par_ecoute({}) is None

    def test_on_compare_plutot_que_de_trancher_sur_un_seuil(self) -> None:
        # Une pièce bruyante donne des niveaux plus hauts partout : le meilleur
        # reste le meilleur, et aucun n'est déclaré muet.
        from greffier.domaine.peripheriques import choisir_par_ecoute

        choix = choisir_par_ecoute({"A": -40.0, "B": -35.0})
        assert choix is not None
        assert choix.nom == "B" and not choix.tous_muets

    def test_blackhole_et_l_agrege_ne_sont_jamais_ecoutes(self) -> None:
        from greffier.domaine.peripheriques import candidats_a_ecouter

        candidats = candidats_a_ecouter(AVEC_CASQUE, "Jabra EVOLVE 30 II")
        assert "BlackHole 2ch" not in candidats
        assert "Reunion Entree" not in candidats

    def test_le_micro_prefere_est_ecoute_en_premier(self) -> None:
        from greffier.domaine.peripheriques import candidats_a_ecouter

        assert candidats_a_ecouter(AVEC_CASQUE, "Micro MacBook Pro")[0] == (
            "Micro MacBook Pro"
        )
