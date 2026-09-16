"""The audio hardware changes during the meeting: what should the tool do?

Eleven situations, all covered without plugging in a single cable. The one of
25 August 2026 is named: a headset plugged in after the start, the voice of
whoever was recording captured 12 dB too low, then wiped out in the mix.
Nothing had said so.
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

JABRA_MIC = Device("Jabra EVOLVE 30 II", "jabra:1", entries=1)
JABRA_OUTPUT = Device("Jabra EVOLVE 30 II", "jabra:2", sorties=2)
BUILT_IN_MIC = Device("Micro MacBook Pro", "BuiltInMicrophoneDevice", entries=1)
BUILT_IN_SPEAKERS = Device("Haut-parleurs MacBook Pro", "BuiltInSpeakerDevice", sorties=2)
BLACKHOLE = Device("BlackHole 2ch", "BlackHole2ch_UID", entries=2, sorties=2)
SCREEN = Device("HP E273m", "220E6E34", sorties=2)
REALTEK = Device("Realtek USB2.0 Audio", "realtek:1", entries=2)
AGGREGATED = Device("Reunion Entree", "com.reunions.entree", entries=3, sorties=2)

WITHOUT_HEADSET = Hardware((BLACKHOLE, BUILT_IN_SPEAKERS, BUILT_IN_MIC, AGGREGATED))
WITH_HEADSET = Hardware(
    (BLACKHOLE, BUILT_IN_SPEAKERS, JABRA_MIC, JABRA_OUTPUT, BUILT_IN_MIC, AGGREGATED)
)


@pytest.fixture
def watch_rules() -> WatchRules:
    return WatchRules(wanted_mic="Jabra EVOLVE 30 II")


class TestTheHeadsetUnpluggedMidMeeting:
    """Le casque est branché après le début de l'enregistrement."""

    def test_the_tool_rebuilds_and_takes_the_capture_back(self, watch_rules: WatchRules) -> None:
        decision = watch_rules.examine(WITHOUT_HEADSET, WITH_HEADSET)
        assert decision.action is Action.REBUILD
        assert decision.mic == "Jabra EVOLVE 30 II"

    def test_it_says_the_start_of_the_meeting_had_no_headset(
        self, watch_rules: WatchRules
    ) -> None:
        decision = watch_rules.examine(WITHOUT_HEADSET, WITH_HEADSET)
        assert "vient d'être branché" in decision.because
        assert "le début de la réunion ne l'a pas eu" in decision.because

    def test_the_audio_already_captured_is_marked_doubtful(self, watch_rules: WatchRules) -> None:
        # What was recorded before it was plugged in is barely usable: the
        # minutes have to be able to say so.
        assert watch_rules.examine(WITHOUT_HEADSET, WITH_HEADSET).audio_suspect

    def test_the_event_is_kept_for_the_log(self, watch_rules: WatchRules) -> None:
        watch_rules.examine(WITHOUT_HEADSET, WITH_HEADSET)
        assert watch_rules.events == ["Jabra EVOLVE 30 II branché en cours de réunion"]


class TestAnUnpluggedHeadset:
    def test_the_capture_moves_to_the_built_in_mic(self, watch_rules: WatchRules) -> None:
        decision = watch_rules.examine(WITH_HEADSET, WITHOUT_HEADSET)
        assert decision.action is Action.REBUILD
        assert decision.mic == "Micro MacBook Pro"
        assert "débranché" in decision.because

    def test_with_no_fallback_mic_it_warns_without_cutting(
        self, watch_rules: WatchRules
    ) -> None:
        # Unplugging the headset with nothing else around: cutting the
        # recording would also lose the others' voices, which come through
        # BlackHole. It warns, and carries on.
        nothing = Hardware((BLACKHOLE, BUILT_IN_SPEAKERS, AGGREGATED))
        decision = watch_rules.examine(WITH_HEADSET, nothing)
        assert decision.action is Action.ALERT
        assert "ta voix n'est plus enregistrée" in decision.because

    def test_blackhole_is_never_chosen_as_a_mic(self, watch_rules: WatchRules) -> None:
        # BlackHole captures the system output, never a mouth. Taking it for a
        # mic would produce a meeting where nobody is recorded.
        nothing = Hardware((BLACKHOLE, BUILT_IN_SPEAKERS, AGGREGATED))
        assert watch_rules.examine(WITH_HEADSET, nothing).mic == ""


class TestPluggingAndUnplugging:
    def test_unplugged_then_plugged_comes_back_to_the_headset(
        self, watch_rules: WatchRules
    ) -> None:
        first_call = watch_rules.examine(WITH_HEADSET, WITHOUT_HEADSET)
        second = watch_rules.examine(WITHOUT_HEADSET, WITH_HEADSET)
        assert first_call.mic == "Micro MacBook Pro"
        assert second.mic == "Jabra EVOLVE 30 II"
        assert len(watch_rules.events) == 2

    def test_repeated_to_and_fro_stays_consistent(self, watch_rules: WatchRules) -> None:
        for _ in range(3):
            assert watch_rules.examine(WITH_HEADSET, WITHOUT_HEADSET).action is Action.REBUILD
            assert watch_rules.examine(WITHOUT_HEADSET, WITH_HEADSET).action is Action.REBUILD
        assert len(watch_rules.events) == 6

    def test_a_second_headset_is_taken_when_the_first_is_gone(self) -> None:
        watch_rules = WatchRules(wanted_mic="Casque absent")
        other = Device("Poly Blackwire", "poly:1", entries=1)
        later = Hardware((BLACKHOLE, BUILT_IN_MIC, other, AGGREGATED))
        decision = watch_rules.examine(WITHOUT_HEADSET, later)
        assert decision.action is Action.REBUILD
        # An external mono mic comes before the built-in one: that is the shape
        # of a headset mic, so the one being spoken into.
        assert decision.mic == "Poly Blackwire"


class TestChangesThatChangeNothing:
    def test_identical_hardware_triggers_nothing(self, watch_rules: WatchRules) -> None:
        assert watch_rules.examine(WITH_HEADSET, WITH_HEADSET).action is Action.NOTHING

    def test_plugging_a_screen_does_not_touch_the_capture(self, watch_rules: WatchRules) -> None:
        later = Hardware((*WITH_HEADSET.devices, SCREEN))
        assert watch_rules.examine(WITH_HEADSET, later).action is Action.NOTHING

    def test_the_headset_stays_when_only_the_output_moves(
        self, watch_rules: WatchRules
    ) -> None:
        # The Jabra exposes its mic and its earpieces separately: losing the
        # output must not suggest the mic has gone.
        without_output = Hardware(
            tuple(p for p in WITH_HEADSET.devices if p != JABRA_OUTPUT)
        )
        assert watch_rules.examine(WITH_HEADSET, without_output).action is Action.NOTHING

    def test_no_event_is_noted_without_a_change(self, watch_rules: WatchRules) -> None:
        watch_rules.examine(WITH_HEADSET, WITH_HEADSET)
        later = Hardware((*WITH_HEADSET.devices, SCREEN))
        watch_rules.examine(WITH_HEADSET, later)
        assert watch_rules.events == []


class TestBeforeStarting:
    def test_the_usual_headset_is_taken_when_it_is_there(self) -> None:
        assert advised_mic(WITH_HEADSET, "Jabra EVOLVE 30 II") == "Jabra EVOLVE 30 II"

    def test_with_no_headset_the_built_in_mic_beats_refusing(self) -> None:
        # Refusing to start because the usual headset is missing would lose the
        # whole meeting. Better to record with what is there.
        assert advised_mic(WITHOUT_HEADSET, "Jabra EVOLVE 30 II") == "Micro MacBook Pro"

    def test_without_a_single_mic_nothing_is_advised(self) -> None:
        assert advised_mic(Hardware((BLACKHOLE, BUILT_IN_SPEAKERS)), "Jabra") == ""

    def test_a_headset_is_judged_present_by_its_input(self) -> None:
        assert headset_present(WITH_HEADSET, "Jabra EVOLVE 30 II")
        assert not headset_present(WITHOUT_HEADSET, "Jabra EVOLVE 30 II")

    def test_an_output_only_device_is_not_a_headset(self) -> None:
        output_only = Hardware((JABRA_OUTPUT, BUILT_IN_SPEAKERS))
        assert not headset_present(output_only, "Jabra EVOLVE 30 II")


class TestChoosingTheFallbackMic:
    """A bad fallback gives a silent recording, not a mere inconvenience."""

    def test_a_stereo_line_input_does_not_beat_the_built_in_mic(self) -> None:
        # "Realtek USB2.0 Audio", two inputs: the line input of a dock or a
        # screen, with nothing plugged into it. Preferring it to the laptop mic
        # gave a silent recording. Seen by unplugging a headset on a real
        # machine.
        hardware = Hardware((BLACKHOLE, BUILT_IN_MIC, REALTEK, AGGREGATED))
        assert advised_mic(hardware, "Casque absent") == "Micro MacBook Pro"

    def test_an_external_mono_mic_comes_before_the_built_in_one(self) -> None:
        headset = Device("Poly Blackwire", "poly:1", entries=1)
        hardware = Hardware((BLACKHOLE, BUILT_IN_MIC, headset, AGGREGATED))
        assert advised_mic(hardware, "Casque absent") == "Poly Blackwire"

    def test_a_line_input_serves_when_there_is_nothing_else(self) -> None:
        # Failing anything better, trying beats capturing nothing at all.
        hardware = Hardware((BLACKHOLE, REALTEK, AGGREGATED))
        assert advised_mic(hardware, "Casque absent") == "Realtek USB2.0 Audio"

    def test_the_aggregate_is_never_offered_even_alone(self) -> None:
        assert advised_mic(Hardware((AGGREGATED, BLACKHOLE)), "Casque absent") == ""


class TestChoosingByListening:
    """A mic plugged in, recognised, turned up to the maximum, and silent all the same.

    Measured on a real machine: a Jabra headset at -78 dB because the mute button
    on its inline box was pressed, the built-in mic at -58 dB in the same silence.
    Greffier kept the headset, recorded an hour of silence, then blamed the
    microphone permission.
    """

    def test_the_mic_that_hears_best_is_kept(self) -> None:
        from greffier.domain.devices import choose_by_listening

        choice = choose_by_listening(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choice is not None
        assert choice.name == "Micro MacBook Pro"
        assert not choice.all_silent

    def test_the_mic_set_aside_is_kept_to_explain_it(self) -> None:
        from greffier.domain.devices import choose_by_listening

        choice = choose_by_listening(
            {"Jabra EVOLVE 30 II": -78.5, "Micro MacBook Pro": -58.6}
        )
        assert choice is not None
        assert choice.set_aside == (("Jabra EVOLVE 30 II", -78.5),)

    def test_when_all_are_silent_it_says_so(self) -> None:
        # The case where the mic permission really is missing, or all is muted.
        from greffier.domain.devices import choose_by_listening

        choice = choose_by_listening({"Jabra": -78.5, "Micro MacBook Pro": -80.0})
        assert choice is not None and choice.all_silent

    def test_with_no_candidate_nothing_is_chosen(self) -> None:
        from greffier.domain.devices import choose_by_listening

        assert choose_by_listening({}) is None

    def test_it_compares_rather_than_judging_on_a_threshold(self) -> None:
        # A noisy room gives higher levels everywhere: the best stays the best,
        # and none is declared silent.
        from greffier.domain.devices import choose_by_listening

        choice = choose_by_listening({"A": -40.0, "B": -35.0})
        assert choice is not None
        assert choice.name == "B" and not choice.all_silent

    def test_blackhole_and_the_aggregate_are_never_listened_to(self) -> None:
        from greffier.domain.devices import candidates_to_listen_to

        candidates_ = candidates_to_listen_to(WITH_HEADSET, "Jabra EVOLVE 30 II")
        assert "BlackHole 2ch" not in candidates_
        assert "Reunion Entree" not in candidates_

    def test_the_preferred_mic_is_listened_to_first(self) -> None:
        from greffier.domain.devices import candidates_to_listen_to

        assert candidates_to_listen_to(WITH_HEADSET, "Micro MacBook Pro")[0] == (
            "Micro MacBook Pro"
        )


class TestAHeadsetWins:
    """The loudest when nobody speaks is not the best in a meeting.

    On 2026-09-09 a Jabra was set aside at -68 dB in favour of the built-in mic at
    -49 dB: the headset was lying on the desk, a metre from the mouth. Worn, it
    would have been far better, a headset mic sits three centimetres from the
    mouth, a laptop's fifty, and it picks up the whole room.
    """

    #: The real hardware of this machine: the Jabra is **two** devices here,
    #: an input and an output of the same name, which is the usual shape of a
    #: USB headset on macOS.
    HARDWARE = Hardware((
        BUILT_IN_MIC, BUILT_IN_SPEAKERS, JABRA_MIC, JABRA_OUTPUT, BLACKHOLE,
    ))

    def test_a_headset_is_known_by_the_name_it_shares(self):
        """A "captures and plays back" test on a single device would fail: a headset is
        presented as two distinct devices.
        """
        assert headsets_among(self.HARDWARE) == frozenset({"Jabra EVOLVE 30 II"})

    def test_the_built_in_mic_is_not_a_headset(self):
        assert "Micro MacBook Pro" not in headsets_among(self.HARDWARE)

    def test_a_software_loopback_is_not_a_headset(self):
        """BlackHole captures and plays back, but comes near nobody's mouth."""
        assert "BlackHole 2ch" not in headsets_among(self.HARDWARE)

    def test_a_desk_sound_card_is_not_a_headset(self):
        """Measured: a 2-channel input and a 4-channel output, against 1 and 2 for a
        headset. Without that test it would be preferred to the built-in mic when
        nothing is plugged into it.
        """
        realtek_input = Device("Realtek USB2.0 Audio", "generic:1", entries=2)
        realtek_output = Device("Realtek USB2.0 Audio", "generic:2", sorties=4)
        hardware = Hardware((
            BUILT_IN_MIC, JABRA_MIC, JABRA_OUTPUT,
            realtek_input, realtek_output,
        ))
        assert headsets_among(hardware) == frozenset({"Jabra EVOLVE 30 II"})

    def test_the_built_in_speakers_do_not_make_a_headset(self):
        """The mic and the speakers of a laptop carry different names, and the pair of
        them is not a headset.
        """
        assert "Haut-parleurs MacBook Pro" not in headsets_among(self.HARDWARE)

    def test_the_headset_wins_even_when_quieter(self):
        trials = {"Micro MacBook Pro": -49.0, "Jabra EVOLVE 30 II": -68.0}
        choice = choose_by_listening(trials, headsets_among(self.HARDWARE))
        assert choice is not None
        assert choice.name == "Jabra EVOLVE 30 II"
        assert choice.preferred_headset is True

    def test_a_silent_headset_does_not_win(self):
        """C'était tout l'objet de l'écoute : un casque coupé rend -78 dB."""
        trials = {"Micro MacBook Pro": -58.0, "Jabra EVOLVE 30 II": -78.0}
        choice = choose_by_listening(trials, headsets_among(self.HARDWARE))
        assert choice is not None
        assert choice.name == "Micro MacBook Pro"
        assert choice.preferred_headset is False

    def test_with_no_headset_the_loudest_wins(self):
        trials = {"Micro MacBook Pro": -49.0, "Micro de table": -62.0}
        choice = choose_by_listening(trials, frozenset())
        assert choice is not None
        assert choice.name == "Micro MacBook Pro"

    def test_the_mic_set_aside_is_still_named_with_its_level(self):
        """So that the choice can be explained, since the levels make it look wrong."""
        trials = {"Micro MacBook Pro": -49.0, "Jabra EVOLVE 30 II": -68.0}
        choice = choose_by_listening(trials, headsets_among(self.HARDWARE))
        assert choice is not None
        assert ("Micro MacBook Pro", -49.0) in choice.set_aside

    def test_all_silent_looks_at_what_was_really_captured(self):
        """Preferring a muted headset must not hide that nothing is capturing."""
        trials = {"Micro MacBook Pro": -90.0, "Jabra EVOLVE 30 II": -95.0}
        choice = choose_by_listening(trials, headsets_among(self.HARDWARE))
        assert choice is not None
        assert choice.all_silent is True
