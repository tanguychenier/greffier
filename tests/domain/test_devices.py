"""Le matériel audio change pendant la réunion : que doit faire l'outil ?

Onze situations, toutes éprouvées sans brancher un câble. Celle du 25 août 2026
est nommée : casque branché après le début, voix de la personne qui enregistrait
captée 12 dB trop bas, puis effacée au mixage. Rien ne l'avait signalé.
"""

from __future__ import annotations

import pytest

from greffier.domain.devices import (
    Action,
    Device,
    Hardware,
    WatchRules,
    advised_mic,
    choose_by_listening,
    headset_present,
    headsets_among,
)

JABRA_MICRO = Device("Jabra EVOLVE 30 II", "jabra:1", entrees=1)
JABRA_SORTIE = Device("Jabra EVOLVE 30 II", "jabra:2", sorties=2)
MICRO_INTEGRE = Device("Micro MacBook Pro", "BuiltInMicrophoneDevice", entrees=1)
HP_INTEGRES = Device("Haut-parleurs MacBook Pro", "BuiltInSpeakerDevice", sorties=2)
BLACKHOLE = Device("BlackHole 2ch", "BlackHole2ch_UID", entrees=2, sorties=2)
ECRAN = Device("HP E273m", "220E6E34", sorties=2)
REALTEK = Device("Realtek USB2.0 Audio", "realtek:1", entrees=2)
AGREGE = Device("Reunion Entree", "com.reunions.entree", entrees=3, sorties=2)

SANS_CASQUE = Hardware((BLACKHOLE, HP_INTEGRES, MICRO_INTEGRE, AGREGE))
AVEC_CASQUE = Hardware((BLACKHOLE, HP_INTEGRES, JABRA_MICRO, JABRA_SORTIE, MICRO_INTEGRE, AGREGE))


@pytest.fixture
def watch_rules() -> WatchRules:
    return WatchRules(wanted_mic="Jabra EVOLVE 30 II")


class TestTheHeadsetUnpluggedMidMeeting:
    """Le casque est branché après le début de l'enregistrement."""

    def test_the_tool_rebuilds_and_takes_the_capture_back(self, watch_rules: WatchRules) -> None:
        decision = watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert decision.action is Action.RECONSTRUIRE
        assert decision.mic == "Jabra EVOLVE 30 II"

    def test_it_says_the_start_of_the_meeting_had_no_headset(
        self, watch_rules: WatchRules
    ) -> None:
        decision = watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert "vient d'être branché" in decision.because
        assert "le début de la réunion ne l'a pas eu" in decision.because

    def test_the_audio_already_captured_is_marked_doubtful(self, watch_rules: WatchRules) -> None:
        # Ce qui a été enregistré avant le branchement est sous-exploitable :
        # le compte rendu doit pouvoir le dire.
        assert watch_rules.examine(SANS_CASQUE, AVEC_CASQUE).audio_suspect

    def test_the_event_is_kept_for_the_log(self, watch_rules: WatchRules) -> None:
        watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert watch_rules.events == ["Jabra EVOLVE 30 II branché en cours de réunion"]


class TestAnUnpluggedHeadset:
    def test_the_capture_moves_to_the_built_in_mic(self, watch_rules: WatchRules) -> None:
        decision = watch_rules.examine(AVEC_CASQUE, SANS_CASQUE)
        assert decision.action is Action.RECONSTRUIRE
        assert decision.mic == "Micro MacBook Pro"
        assert "débranché" in decision.because

    def test_with_no_fallback_mic_it_warns_without_cutting(
        self, watch_rules: WatchRules
    ) -> None:
        # Débrancher le casque quand il n'y a rien d'autre : couper
        # l'enregistrement perdrait aussi la voix des autres, qui arrive par
        # BlackHole. On prévient, on continue.
        rien = Hardware((BLACKHOLE, HP_INTEGRES, AGREGE))
        decision = watch_rules.examine(AVEC_CASQUE, rien)
        assert decision.action is Action.ALERTER
        assert "ta voix n'est plus enregistrée" in decision.because

    def test_blackhole_is_never_chosen_as_a_mic(self, watch_rules: WatchRules) -> None:
        # BlackHole capte la sortie du système, jamais une bouche. Le prendre
        # pour micro produirait une réunion où personne n'est enregistré.
        rien = Hardware((BLACKHOLE, HP_INTEGRES, AGREGE))
        assert watch_rules.examine(AVEC_CASQUE, rien).mic == ""


class TestPluggingAndUnplugging:
    def test_unplugged_then_plugged_comes_back_to_the_headset(
        self, watch_rules: WatchRules
    ) -> None:
        first_call = watch_rules.examine(AVEC_CASQUE, SANS_CASQUE)
        second = watch_rules.examine(SANS_CASQUE, AVEC_CASQUE)
        assert first_call.mic == "Micro MacBook Pro"
        assert second.mic == "Jabra EVOLVE 30 II"
        assert len(watch_rules.events) == 2

    def test_repeated_to_and_fro_stays_consistent(self, watch_rules: WatchRules) -> None:
        for _ in range(3):
            assert watch_rules.examine(AVEC_CASQUE, SANS_CASQUE).action is Action.RECONSTRUIRE
            assert watch_rules.examine(SANS_CASQUE, AVEC_CASQUE).action is Action.RECONSTRUIRE
        assert len(watch_rules.events) == 6

    def test_a_second_headset_is_taken_when_the_first_is_gone(self) -> None:
        watch_rules = WatchRules(wanted_mic="Casque absent")
        other = Device("Poly Blackwire", "poly:1", entrees=1)
        apres = Hardware((BLACKHOLE, MICRO_INTEGRE, other, AGREGE))
        decision = watch_rules.examine(SANS_CASQUE, apres)
        assert decision.action is Action.RECONSTRUIRE
        # Un micro externe mono passe devant le micro intégré : c'est la forme
        # d'un micro de casque, donc celui dans lequel on parle.
        assert decision.mic == "Poly Blackwire"


class TestChangesThatChangeNothing:
    def test_identical_hardware_triggers_nothing(self, watch_rules: WatchRules) -> None:
        assert watch_rules.examine(AVEC_CASQUE, AVEC_CASQUE).action is Action.NOTHING

    def test_plugging_a_screen_does_not_touch_the_capture(self, watch_rules: WatchRules) -> None:
        apres = Hardware((*AVEC_CASQUE.devices, ECRAN))
        assert watch_rules.examine(AVEC_CASQUE, apres).action is Action.NOTHING

    def test_the_headset_stays_when_only_the_output_moves(
        self, watch_rules: WatchRules
    ) -> None:
        # Le Jabra expose micro et écouteurs séparément : perdre la sortie ne
        # doit pas faire croire que le micro a disparu.
        sans_sortie = Hardware(
            tuple(p for p in AVEC_CASQUE.devices if p != JABRA_SORTIE)
        )
        assert watch_rules.examine(AVEC_CASQUE, sans_sortie).action is Action.NOTHING

    def test_no_event_is_noted_without_a_change(self, watch_rules: WatchRules) -> None:
        watch_rules.examine(AVEC_CASQUE, AVEC_CASQUE)
        apres = Hardware((*AVEC_CASQUE.devices, ECRAN))
        watch_rules.examine(AVEC_CASQUE, apres)
        assert watch_rules.events == []


class TestBeforeStarting:
    def test_the_usual_headset_is_taken_when_it_is_there(self) -> None:
        assert advised_mic(AVEC_CASQUE, "Jabra EVOLVE 30 II") == "Jabra EVOLVE 30 II"

    def test_with_no_headset_the_built_in_mic_beats_refusing(self) -> None:
        # Refuser de démarrer parce que le casque habituel manque ferait perdre
        # la réunion entière. Mieux vaut enregistrer avec ce qu'on a.
        assert advised_mic(SANS_CASQUE, "Jabra EVOLVE 30 II") == "Micro MacBook Pro"

    def test_without_a_single_mic_nothing_is_advised(self) -> None:
        assert advised_mic(Hardware((BLACKHOLE, HP_INTEGRES)), "Jabra") == ""

    def test_a_headset_is_judged_present_by_its_input(self) -> None:
        assert headset_present(AVEC_CASQUE, "Jabra EVOLVE 30 II")
        assert not headset_present(SANS_CASQUE, "Jabra EVOLVE 30 II")

    def test_an_output_only_device_is_not_a_headset(self) -> None:
        sortie_seule = Hardware((JABRA_SORTIE, HP_INTEGRES))
        assert not headset_present(sortie_seule, "Jabra EVOLVE 30 II")


class TestChoosingTheFallbackMic:
    """Un mauvais repli donne un enregistrement muet, pas une simple gêne."""

    def test_a_stereo_line_input_does_not_beat_the_built_in_mic(self) -> None:
        # « Realtek USB2.0 Audio », deux entrées : c'est l'entrée ligne d'une
        # station d'accueil ou d'un écran, sur laquelle rien n'est branché.
        # La préférer au micro du portable donnait un enregistrement muet.
        # Constaté en débranchant un casque sur un poste réel.
        materiel = Hardware((BLACKHOLE, MICRO_INTEGRE, REALTEK, AGREGE))
        assert advised_mic(materiel, "Casque absent") == "Micro MacBook Pro"

    def test_an_external_mono_mic_comes_before_the_built_in_one(self) -> None:
        casque = Device("Poly Blackwire", "poly:1", entrees=1)
        materiel = Hardware((BLACKHOLE, MICRO_INTEGRE, casque, AGREGE))
        assert advised_mic(materiel, "Casque absent") == "Poly Blackwire"

    def test_a_line_input_serves_when_there_is_nothing_else(self) -> None:
        # Faute de mieux, mieux vaut tenter que ne rien capter du tout.
        materiel = Hardware((BLACKHOLE, REALTEK, AGREGE))
        assert advised_mic(materiel, "Casque absent") == "Realtek USB2.0 Audio"

    def test_the_aggregate_is_never_offered_even_alone(self) -> None:
        assert advised_mic(Hardware((AGREGE, BLACKHOLE)), "Casque absent") == ""


class TestChoosingByListening:
    """Un micro branché, reconnu, réglé au maximum, et pourtant muet.

    Mesuré sur un poste réel : casque Jabra à -78 dB parce que le bouton de
    sourdine de son boîtier était enfoncé, micro intégré à -58 dB dans le même
    silence. Greffier retenait le casque, enregistrait une heure de silence, puis
    accusait l'autorisation micro.
    """

    def test_the_mic_that_hears_best_is_kept(self) -> None:
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choix is not None
        assert choix.name == "Micro MacBook Pro"
        assert not choix.all_silent

    def test_the_mic_set_aside_is_kept_to_explain_it(self) -> None:
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choix is not None
        assert choix.ecartes == (("Jabra EVOLVE 30 II", -78.5),)

    def test_when_all_are_silent_it_says_so(self) -> None:
        # Le cas où l'autorisation micro manque vraiment, ou où tout est coupé.
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening({"Jabra": -78.5, "Micro MacBook Pro": -80.0})
        assert choix is not None and choix.all_silent

    def test_with_no_candidate_nothing_is_chosen(self) -> None:
        from greffier.domain.devices import choose_by_listening

        assert choose_by_listening({}) is None

    def test_it_compares_rather_than_judging_on_a_threshold(self) -> None:
        # Une pièce bruyante donne des niveaux plus hauts partout : le meilleur
        # reste le meilleur, et aucun n'est déclaré muet.
        from greffier.domain.devices import choose_by_listening

        choix = choose_by_listening({"A": -40.0, "B": -35.0})
        assert choix is not None
        assert choix.name == "B" and not choix.all_silent

    def test_blackhole_and_the_aggregate_are_never_listened_to(self) -> None:
        from greffier.domain.devices import candidates_to_listen_to

        candidats = candidates_to_listen_to(AVEC_CASQUE, "Jabra EVOLVE 30 II")
        assert "BlackHole 2ch" not in candidats
        assert "Reunion Entree" not in candidats

    def test_the_preferred_mic_is_listened_to_first(self) -> None:
        from greffier.domain.devices import candidates_to_listen_to

        assert candidates_to_listen_to(AVEC_CASQUE, "Micro MacBook Pro")[0] == (
            "Micro MacBook Pro"
        )


class TestAHeadsetWins:
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
    MATERIEL = Hardware((
        MICRO_INTEGRE, HP_INTEGRES, JABRA_MICRO, JABRA_SORTIE, BLACKHOLE,
    ))

    def test_a_headset_is_known_by_the_name_it_shares(self):
        """Un critère « capte et restitue » sur un seul appareil échouerait :
        le casque est présenté comme deux périphériques distincts."""
        assert headsets_among(self.MATERIEL) == frozenset({"Jabra EVOLVE 30 II"})

    def test_the_built_in_mic_is_not_a_headset(self):
        assert "Micro MacBook Pro" not in headsets_among(self.MATERIEL)

    def test_a_software_loopback_is_not_a_headset(self):
        """BlackHole capte et restitue, mais ne s'approche d'aucune bouche."""
        assert "BlackHole 2ch" not in headsets_among(self.MATERIEL)

    def test_a_desk_sound_card_is_not_a_headset(self):
        """Mesuré : entrée à 2 canaux et sortie à 4, contre 1 et 2 pour un
        casque. Sans ce critère, elle serait préférée au micro intégré alors
        que rien n'est branché dessus."""
        realtek_entree = Device("Realtek USB2.0 Audio", "generic:1", entrees=2)
        realtek_sortie = Device("Realtek USB2.0 Audio", "generic:2", sorties=4)
        materiel = Hardware((
            MICRO_INTEGRE, JABRA_MICRO, JABRA_SORTIE,
            realtek_entree, realtek_sortie,
        ))
        assert headsets_among(materiel) == frozenset({"Jabra EVOLVE 30 II"})

    def test_the_built_in_speakers_do_not_make_a_headset(self):
        """Micro et haut-parleurs d'un portable portent des noms différents,
        et l'ensemble n'est pas un casque."""
        assert "Haut-parleurs MacBook Pro" not in headsets_among(self.MATERIEL)

    def test_the_headset_wins_even_when_quieter(self):
        essais = {"Micro MacBook Pro": -49.0, "Jabra EVOLVE 30 II": -68.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert choix.name == "Jabra EVOLVE 30 II"
        assert choix.preferred_headset is True

    def test_a_silent_headset_does_not_win(self):
        """C'était tout l'objet de l'écoute : un casque coupé rend -78 dB."""
        essais = {"Micro MacBook Pro": -58.0, "Jabra EVOLVE 30 II": -78.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert choix.name == "Micro MacBook Pro"
        assert choix.preferred_headset is False

    def test_with_no_headset_the_loudest_wins(self):
        essais = {"Micro MacBook Pro": -49.0, "Micro de table": -62.0}
        choix = choose_by_listening(essais, frozenset())
        assert choix is not None
        assert choix.name == "Micro MacBook Pro"

    def test_the_mic_set_aside_is_still_named_with_its_level(self):
        """Pour pouvoir expliquer le choix, qui paraît faux au vu des niveaux."""
        essais = {"Micro MacBook Pro": -49.0, "Jabra EVOLVE 30 II": -68.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert ("Micro MacBook Pro", -49.0) in choix.ecartes

    def test_all_silent_looks_at_what_was_really_captured(self):
        """Préférer un casque coupé ne doit pas masquer que rien ne capte."""
        essais = {"Micro MacBook Pro": -90.0, "Jabra EVOLVE 30 II": -95.0}
        choix = choose_by_listening(essais, headsets_among(self.MATERIEL))
        assert choix is not None
        assert choix.all_silent is True
