"""Le matériel audio change pendant la réunion : que doit faire l'outil ?

Onze situations, toutes éprouvées sans brancher un câble. Celle du 25 août 2026
est nommée : casque branché après le début, voix de la personne qui enregistrait
captée 12 dB trop bas, puis effacée au mixage. Rien ne l'avait signalé.
"""

from __future__ import annotations

import pytest

from greffier.domain.devices import (
    Action,
    Materiel,
    Peripherique,
    WatchRules,
    advised_mic,
    choose_by_listening,
    headset_present,
    headsets_among,
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
def watch_rules() -> WatchRules:
    return WatchRules(micro_voulu="Jabra EVOLVE 30 II")


class TestLeScenarioDu25Aout:
    """Le casque est branché après le début de l'enregistrement."""

    def test_l_outil_reconstruit_et_reprend_la_capture(self, watch_rules: WatchRules) -> None:
        decision = watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert decision.action is Action.RECONSTRUIRE
        assert decision.mic == "Jabra EVOLVE 30 II"

    def test_il_dit_que_le_debut_de_la_reunion_n_a_pas_eu_le_casque(
        self, watch_rules: WatchRules
    ) -> None:
        decision = watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert "vient d'être branché" in decision.because
        assert "le début de la réunion ne l'a pas eu" in decision.because

    def test_l_audio_deja_capte_est_marque_suspect(self, watch_rules: WatchRules) -> None:
        # Ce qui a été enregistré avant le branchement est sous-exploitable :
        # le compte rendu doit pouvoir le dire.
        assert watch_rules.examine(SANS_CASQUE, AVEC_CASQUE).audio_suspect

    def test_l_evenement_est_conserve_pour_le_journal(self, watch_rules: WatchRules) -> None:
        watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert watch_rules.events == ["Jabra EVOLVE 30 II branché en cours de réunion"]


class TestCasqueDebranche:
    def test_la_capture_repart_sur_le_micro_integre(self, watch_rules: WatchRules) -> None:
        decision = watch_rules.examine(AVEC_CASQUE, SANS_CASQUE)
        assert decision.action is Action.RECONSTRUIRE
        assert decision.mic == "Micro MacBook Pro"
        assert "débranché" in decision.because

    def test_sans_aucun_micro_de_repli_l_outil_alerte_sans_couper(
        self, watch_rules: WatchRules
    ) -> None:
        # Débrancher le casque quand il n'y a rien d'autre : couper
        # l'enregistrement perdrait aussi la voix des autres, qui arrive par
        # BlackHole. On prévient, on continue.
        rien = Materiel((BLACKHOLE, HP_INTEGRES, AGREGE))
        decision = watch_rules.examine(AVEC_CASQUE, rien)
        assert decision.action is Action.ALERTER
        assert "ta voix n'est plus enregistrée" in decision.because

    def test_blackhole_n_est_jamais_choisi_comme_micro(self, watch_rules: WatchRules) -> None:
        # BlackHole capte la sortie du système, jamais une bouche. Le prendre
        # pour micro produirait une réunion où personne n'est enregistré.
        rien = Materiel((BLACKHOLE, HP_INTEGRES, AGREGE))
        assert watch_rules.examine(AVEC_CASQUE, rien).mic == ""


class TestBranchementsSuccessifs:
    def test_debranche_puis_rebranche_revient_au_casque(self, watch_rules: WatchRules) -> None:
        premier = watch_rules.examine(AVEC_CASQUE, SANS_CASQUE)
        second = watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert premier.mic == "Micro MacBook Pro"
        assert second.mic == "Jabra EVOLVE 30 II"
        assert len(watch_rules.events) == 2

    def test_un_va_et_vient_repete_reste_coherent(self, watch_rules: WatchRules) -> None:
        for _ in range(3):
            assert watch_rules.examine(AVEC_CASQUE, SANS_CASQUE).action is Action.RECONSTRUIRE
            assert watch_rules.examine(SANS_CASQUE, AVEC_CASQUE).action is Action.RECONSTRUIRE
        assert len(watch_rules.events) == 6

    def test_un_second_casque_branche_est_pris_si_le_premier_manque(self) -> None:
        watch_rules = WatchRules(micro_voulu="Casque absent")
        autre = Peripherique("Poly Blackwire", "poly:1", entrees=1)
        apres = Materiel((BLACKHOLE, MICRO_INTEGRE, autre, AGREGE))
        decision = watch_rules.examine(SANS_CASQUE, apres)
        assert decision.action is Action.RECONSTRUIRE
        # Un micro externe mono passe devant le micro intégré : c'est la forme
        # d'un micro de casque, donc celui dans lequel on parle.
        assert decision.mic == "Poly Blackwire"


class TestChangementsSansEffet:
    def test_un_materiel_identique_ne_declenche_rien(self, watch_rules: WatchRules) -> None:
        assert watch_rules.examine(AVEC_CASQUE, AVEC_CASQUE).action is Action.RIEN

    def test_brancher_un_ecran_ne_touche_pas_a_la_capture(self, watch_rules: WatchRules) -> None:
        apres = Materiel((*AVEC_CASQUE.devices, ECRAN))
        assert watch_rules.examine(AVEC_CASQUE, apres).action is Action.RIEN

    def test_le_casque_reste_present_quand_seule_la_sortie_bouge(
        self, watch_rules: WatchRules
    ) -> None:
        # Le Jabra expose micro et écouteurs séparément : perdre la sortie ne
        # doit pas faire croire que le micro a disparu.
        sans_sortie = Materiel(
            tuple(p for p in AVEC_CASQUE.devices if p != JABRA_SORTIE)
        )
        assert watch_rules.examine(AVEC_CASQUE, sans_sortie).action is Action.RIEN

    def test_aucun_evenement_n_est_note_sans_changement(self, watch_rules: WatchRules) -> None:
        watch_rules.examine(AVEC_CASQUE, AVEC_CASQUE)
        apres = Materiel((*AVEC_CASQUE.devices, ECRAN))
        watch_rules.examine(AVEC_CASQUE, apres)
        assert watch_rules.events == []


class TestAvantDeDemarrer:
    def test_le_casque_habituel_est_pris_quand_il_est_la(self) -> None:
        assert advised_mic(AVEC_CASQUE, "Jabra EVOLVE 30 II") == "Jabra EVOLVE 30 II"

    def test_sans_casque_on_prend_le_micro_integre_plutot_que_de_refuser(self) -> None:
        # Refuser de démarrer parce que le casque habituel manque ferait perdre
        # la réunion entière. Mieux vaut enregistrer avec ce qu'on a.
        assert advised_mic(SANS_CASQUE, "Jabra EVOLVE 30 II") == "Micro MacBook Pro"

    def test_sans_le_moindre_micro_rien_n_est_conseille(self) -> None:
        assert advised_mic(Materiel((BLACKHOLE, HP_INTEGRES)), "Jabra") == ""

    def test_la_presence_du_casque_se_verifie_sur_son_entree(self) -> None:
        assert headset_present(AVEC_CASQUE, "Jabra EVOLVE 30 II")
        assert not headset_present(SANS_CASQUE, "Jabra EVOLVE 30 II")

    def test_un_peripherique_de_sortie_seule_n_est_pas_un_casque(self) -> None:
        sortie_seule = Materiel((JABRA_SORTIE, HP_INTEGRES))
        assert not headset_present(sortie_seule, "Jabra EVOLVE 30 II")


class TestChoixDuMicroDeRepli:
    """Un mauvais repli donne un enregistrement muet, pas une simple gêne."""

    def test_une_entree_ligne_stereo_ne_bat_pas_le_micro_integre(self) -> None:
        # « Realtek USB2.0 Audio », deux entrées : c'est l'entrée ligne d'une
        # station d'accueil ou d'un écran, sur laquelle rien n'est branché.
        # La préférer au micro du portable donnait un enregistrement muet.
        # Constaté en débranchant un casque sur un poste réel.
        materiel = Materiel((BLACKHOLE, MICRO_INTEGRE, REALTEK, AGREGE))
        assert advised_mic(materiel, "Casque absent") == "Micro MacBook Pro"

    def test_un_micro_externe_mono_passe_devant_le_micro_integre(self) -> None:
        casque = Peripherique("Poly Blackwire", "poly:1", entrees=1)
        materiel = Materiel((BLACKHOLE, MICRO_INTEGRE, casque, AGREGE))
        assert advised_mic(materiel, "Casque absent") == "Poly Blackwire"

    def test_une_entree_ligne_sert_quand_il_n_y_a_rien_d_autre(self) -> None:
        # Faute de mieux, mieux vaut tenter que ne rien capter du tout.
        materiel = Materiel((BLACKHOLE, REALTEK, AGREGE))
        assert advised_mic(materiel, "Casque absent") == "Realtek USB2.0 Audio"

    def test_l_agrege_n_est_jamais_propose_meme_seul(self) -> None:
        assert advised_mic(Materiel((AGREGE, BLACKHOLE)), "Casque absent") == ""


class TestChoixParEcoute:
    """Un micro branché, reconnu, réglé au maximum, et pourtant muet.

    Mesuré sur un poste réel : casque Jabra à -78 dB parce que le bouton de
    sourdine de son boîtier était enfoncé, micro intégré à -58 dB dans le même
    silence. Greffier retenait le casque, enregistrait une heure de silence, puis
    accusait l'autorisation micro.
    """

    def test_le_micro_qui_capte_le_mieux_est_retenu(self) -> None:
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choix is not None
        assert choix.name == "Micro MacBook Pro"
        assert not choix.tous_muets

    def test_le_micro_ecarte_est_conserve_pour_l_expliquer(self) -> None:
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choix is not None
        assert choix.ecartes == (("Jabra EVOLVE 30 II", -78.5),)

    def test_quand_tous_sont_muets_on_le_dit(self) -> None:
        # Le cas où l'autorisation micro manque vraiment, ou où tout est coupé.
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening({"Jabra": -78.5, "Micro MacBook Pro": -80.0})
        assert choix is not None and choix.tous_muets

    def test_sans_candidat_rien_n_est_choisi(self) -> None:
        from greffier.domain.devices import choose_by_listening

        assert choose_by_listening({}) is None

    def test_on_compare_plutot_que_de_trancher_sur_un_seuil(self) -> None:
        # Une pièce bruyante donne des niveaux plus hauts partout : le meilleur
        # reste le meilleur, et aucun n'est déclaré muet.
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening({"A": -40.0, "B": -35.0})
        assert choix is not None
        assert choix.name == "B" and not choix.tous_muets

    def test_blackhole_et_l_agrege_ne_sont_jamais_ecoutes(self) -> None:
        from greffier.domain.devices import candidates_to_listen_to

        candidats = candidates_to_listen_to(AVEC_CASQUE, "Jabra EVOLVE 30 II")
        assert "BlackHole 2ch" not in candidats
        assert "Reunion Entree" not in candidats

    def test_le_micro_prefere_est_ecoute_en_premier(self) -> None:
        from greffier.domain.devices import candidates_to_listen_to

        assert candidates_to_listen_to(AVEC_CASQUE, "Micro MacBook Pro")[0] == (
            "Micro MacBook Pro"
        )


class TestUnCasqueLEmporte:
    """Le plus fort à froid n'est pas le meilleur en réunion.

    Le 2026-09-09, un Jabra a été écarté à -68 dB au profit du micro intégré à
    -49 dB : le casque était posé sur le bureau, à un mètre de la bouche. Une
    fois porté, il aurait été de loin le meilleur — un micro de casque est à
    trois centimètres de la bouche, celui d'un portable à cinquante et il capte
    toute la pièce.
    """

    #: Le matériel réel de ce poste : le Jabra y est **deux** périphériques,
    #: une entrée et une sortie de même nom, ce qui est la forme habituelle
    #: d'un casque USB sur macOS.
    MATERIEL = Materiel((
        MICRO_INTEGRE, HP_INTEGRES, JABRA_MICRO, JABRA_SORTIE, BLACKHOLE,
    ))

    def test_un_casque_est_reconnu_a_son_nom_partage(self):
        """Un critère « capte et restitue » sur un seul appareil échouerait :
        le casque est présenté comme deux périphériques distincts."""
        assert headsets_among(self.MATERIEL) == frozenset({"Jabra EVOLVE 30 II"})

    def test_le_micro_integre_n_est_pas_un_casque(self):
        assert "Micro MacBook Pro" not in headsets_among(self.MATERIEL)

    def test_une_boucle_logicielle_n_est_pas_un_casque(self):
        """BlackHole capte et restitue, mais ne s'approche d'aucune bouche."""
        assert "BlackHole 2ch" not in headsets_among(self.MATERIEL)

    def test_une_carte_son_de_station_n_est_pas_un_casque(self):
        """Mesuré : entrée à 2 canaux et sortie à 4, contre 1 et 2 pour un
        casque. Sans ce critère, elle serait préférée au micro intégré alors
        que rien n'est branché dessus."""
        realtek_entree = Peripherique("Realtek USB2.0 Audio", "generic:1", entrees=2)
        realtek_sortie = Peripherique("Realtek USB2.0 Audio", "generic:2", sorties=4)
        materiel = Materiel((
            MICRO_INTEGRE, JABRA_MICRO, JABRA_SORTIE,
            realtek_entree, realtek_sortie,
        ))
        assert headsets_among(materiel) == frozenset({"Jabra EVOLVE 30 II"})

    def test_les_haut_parleurs_integres_ne_font_pas_un_casque(self):
        """Micro et haut-parleurs d'un portable portent des noms différents,
        et l'ensemble n'est pas un casque."""
        assert "Haut-parleurs MacBook Pro" not in headsets_among(self.MATERIEL)

    def test_le_casque_l_emporte_meme_plus_faible(self):
        essais = {"Micro MacBook Pro": -49.0, "Jabra EVOLVE 30 II": -68.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert choix.name == "Jabra EVOLVE 30 II"
        assert choix.casque_prefere is True

    def test_un_casque_mute_ne_l_emporte_pas(self):
        """C'était tout l'objet de l'écoute : un casque coupé rend -78 dB."""
        essais = {"Micro MacBook Pro": -58.0, "Jabra EVOLVE 30 II": -78.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert choix.name == "Micro MacBook Pro"
        assert choix.casque_prefere is False

    def test_sans_casque_le_plus_fort_gagne(self):
        essais = {"Micro MacBook Pro": -49.0, "Micro de table": -62.0}
        choix = choose_by_listening(essais, frozenset())
        assert choix is not None
        assert choix.name == "Micro MacBook Pro"

    def test_le_micro_ecarte_reste_dit_avec_son_niveau(self):
        """Pour pouvoir expliquer le choix, qui paraît faux au vu des niveaux."""
        essais = {"Micro MacBook Pro": -49.0, "Jabra EVOLVE 30 II": -68.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert ("Micro MacBook Pro", -49.0) in choix.ecartes

    def test_tous_muets_regarde_le_meilleur_reellement_capte(self):
        """Préférer un casque coupé ne doit pas masquer que rien ne capte."""
        essais = {"Micro MacBook Pro": -90.0, "Jabra EVOLVE 30 II": -95.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert choix.tous_muets is True
