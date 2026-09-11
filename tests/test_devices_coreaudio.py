"""Reading the real audio hardware.

The reading is a pure function: it can be covered on captured outputs,
including those that cannot be reproduced at will on a given machine. The
outputs below come from a real Mac, before and after plugging the headset in.
"""

from __future__ import annotations

from greffier.adapters.devices_coreaudio import analyser
from greffier.domain.devices import Hardware, WatchRules, advised_mic

# Relevé réel, casque et station débranchés.
SEUL = """Périphériques audio :

  BlackHole 2ch  [entrée 2ch, sortie 2ch]
    uid: BlackHole2ch_UID
  Haut-parleurs MacBook Pro  [sortie 2ch]
    uid: BuiltInSpeakerDevice
  Micro MacBook Pro  [entrée 1ch]
    uid: BuiltInMicrophoneDevice
  Reunion Entree  [entrée 3ch, sortie 2ch]
    uid: com.reunions.entree
  Reunion Sortie  [sortie 2ch]
    uid: com.reunions.sortie
"""

# Le même poste, casque Jabra et station branchés.
BRANCHE = """Périphériques audio :

  BlackHole 2ch  [entrée 2ch, sortie 2ch]
    uid: BlackHole2ch_UID
  HP E273m  [sortie 2ch]
    uid: 220E6E34-0000-0000-0120-0103803C2278
  Haut-parleurs MacBook Pro  [sortie 2ch]
    uid: BuiltInSpeakerDevice
  Jabra EVOLVE 30 II  [entrée 1ch]
    uid: AppleUSBAudioEngine:GN Audio A/S:Jabra EVOLVE 30 II:0000718017FA09:1
  Jabra EVOLVE 30 II  [sortie 2ch]
    uid: AppleUSBAudioEngine:GN Audio A/S:Jabra EVOLVE 30 II:0000718017FA09:2
  Micro MacBook Pro  [entrée 1ch]
    uid: BuiltInMicrophoneDevice
  Realtek USB2.0 Audio  [entrée 2ch]
    uid: AppleUSBAudioEngine:Generic:USB Audio:200901010001:1
  Reunion Entree  [entrée 3ch, sortie 2ch]
    uid: com.reunions.entree
  Reunion Sortie  [sortie 2ch]
    uid: com.reunions.sortie
"""


class TestReadingWhatTheWriterReturned:
    def test_every_device_is_recognised(self) -> None:
        assert len(analyser(SEUL).devices) == 5
        assert len(analyser(BRANCHE).devices) == 9

    def test_the_channels_are_read_both_ways(self) -> None:
        agrege = analyser(SEUL).by_name("Reunion Entree")
        assert agrege is not None
        assert agrege.entrees == 3
        assert agrege.sorties == 2

    def test_an_output_only_device_has_no_input(self) -> None:
        hp = analyser(SEUL).by_name("Haut-parleurs MacBook Pro")
        assert hp is not None
        assert hp.entrees == 0
        assert not hp.captured

    def test_l_uid_est_conserve_entier(self) -> None:
        jabra = analyser(BRANCHE).by_name("Jabra EVOLVE 30 II")
        assert jabra is not None
        assert jabra.uid.endswith(":1")

    def test_a_name_carried_by_two_devices_is_not_lost(self) -> None:
        # Le Jabra expose micro et écouteurs sous le même nom, uid différents.
        jabras = [p for p in analyser(BRANCHE).devices if p.name.startswith("Jabra")]
        assert len(jabras) == 2
        assert {p.entrees for p in jabras} == {0, 1}

    def test_only_the_devices_that_capture_count_as_mics(self) -> None:
        assert {p.name for p in analyser(SEUL).mics} == {
            "BlackHole 2ch", "Micro MacBook Pro", "Reunion Entree",
        }

    def test_an_empty_output_does_not_make_the_reading_fail(self) -> None:
        assert analyser("").devices == ()
        assert analyser("Périphériques audio :\n\n").devices == ()

    def test_une_sortie_tronquee_ignore_l_entree_incomplete(self) -> None:
        # A device announced without its "uid" line is dropped rather than
        # entering the comparison in a partial shape.
        tronque = SEUL[: SEUL.index("  Reunion Entree")] + "  Casque coupé  [entrée 1ch]\n"
        names = {p.name for p in analyser(tronque).devices}
        assert "Casque coupé" not in names


class TestDecidingOnRealHardware:
    """The decision, applied to real readings rather than to manufactured cases."""

    def test_plugging_the_headset_in_is_seen(self) -> None:
        watch_rules = WatchRules(wanted_mic="Jabra EVOLVE 30 II")
        decision = watch_rules.examine(analyser(SEUL), analyser(BRANCHE))
        assert decision.mic == "Jabra EVOLVE 30 II"
        assert decision.audio_suspect

    def test_unplugging_avoids_the_dock_s_line_input(self) -> None:
        # On unplugging, the Realtek dock disappears too. But even if it
        # stayed it should not be chosen: see the next test.
        watch_rules = WatchRules(wanted_mic="Jabra EVOLVE 30 II")
        assert watch_rules.examine(analyser(BRANCHE), analyser(SEUL)).mic == "Micro MacBook Pro"

    def test_the_dock_alone_does_not_beat_the_laptop_mic(self) -> None:
        # Dock plugged in, headset not: the Realtek line input is almost always
        # empty, the laptop mic captures at least something.
        materiel = analyser(BRANCHE)
        sans_casque = Hardware(
            tuple(p for p in materiel.devices if not p.name.startswith("Jabra"))
        )
        assert sans_casque.by_name("Realtek USB2.0 Audio") is not None
        assert advised_mic(sans_casque, "Jabra EVOLVE 30 II") == "Micro MacBook Pro"

    def test_the_aggregate_is_never_kept_despite_its_three_inputs(self) -> None:
        assert advised_mic(analyser(SEUL), "Casque absent") == "Micro MacBook Pro"
