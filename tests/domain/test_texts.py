"""Ce qui tient lieu d'identifiant quand la réduction en ASCII ne laisse rien.

Trois endroits réduisent un texte libre en identifiant de fichier : la banque de
voix, le nom d'une réunion, l'ancre d'une section de courriel. Tous les trois se
rabattaient sur un mot fixe quand il ne restait rien — « sans-nom », « reunion »,
« s- » — donc sur le MÊME identifiant pour des textes différents. Dans la banque
de voix, cela fusionnait deux personnes.
"""

from greffier.domain.texts import short_voiceprint


class TestEmpreinteCourte:
    def test_deux_textes_differents_ne_se_confondent_pas(self):
        assert short_voiceprint("Дмитрий") != short_voiceprint("Ольга")

    def test_le_meme_texte_rend_toujours_la_meme_chose(self):
        """Une voix nommée aujourd'hui doit se retrouver demain : « hash »,
        lui, change d'une exécution à l'autre."""
        assert short_voiceprint("田中") == short_voiceprint("田中")

    def test_elle_tient_dans_un_nom_de_fichier(self):
        voiceprint = short_voiceprint("Δημήτρης")
        assert len(voiceprint) == 10
        assert voiceprint.isalnum()

    def test_le_vide_a_lui_aussi_une_empreinte(self):
        """Un titre entièrement fait de ponctuation n'est pas une erreur."""
        assert short_voiceprint("")
