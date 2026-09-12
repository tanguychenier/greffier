"""Ce qui tient lieu d'identifiant quand la réduction en ASCII ne laisse rien.

Trois endroits réduisent un texte libre en identifiant de fichier : la banque de
voix, le nom d'une réunion, l'ancre d'une section de courriel. Tous les trois se
rabattaient sur un mot fixe quand il ne restait rien : « sans-nom », « reunion »,
« s- », donc sur le MÊME identifiant pour des textes différents. Dans la banque
de voix, cela fusionnait deux personnes.
"""

from greffier.domain.texts import short_voiceprint


class TestAShortFingerprint:
    def test_two_different_texts_are_not_confused(self):
        assert short_voiceprint("Дмитрий") != short_voiceprint("Ольга")

    def test_the_same_text_always_returns_the_same(self):
        """Une voix nommée aujourd'hui doit se retrouver demain : « hash »,
        lui, change d'une exécution à l'autre."""
        assert short_voiceprint("田中") == short_voiceprint("田中")

    def test_it_fits_in_a_file_name(self):
        voiceprint = short_voiceprint("Δημήτρης")
        assert len(voiceprint) == 10
        assert voiceprint.isalnum()

    def test_the_empty_string_has_one_too(self):
        """Un titre entièrement fait de ponctuation n'est pas une erreur."""
        assert short_voiceprint("")
