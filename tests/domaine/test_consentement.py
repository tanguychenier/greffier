"""Ce que les participants doivent pouvoir savoir, et sa trace.

Une voix est une donnée biométrique. Le principe retenu : ce qui n'est pas
écrit n'a pas eu lieu — une mention orale ne se retrouve pas six mois plus
tard, une ligne dans le compte rendu si.
"""

from greffier.domaine.consentement import (
    MENTIONS,
    RAPPEL,
    Information,
    a_tracer,
    lire,
    mention,
)


class TestLecture:
    def test_les_trois_etats_se_lisent(self):
        assert lire("rien") is Information.RIEN
        assert lire("annoncé") is Information.ANNONCE
        assert lire("accord") is Information.ACCORD

    def test_la_casse_et_les_espaces_ne_comptent_pas(self):
        assert lire("  Accord ") is Information.ACCORD

    def test_une_valeur_inconnue_retombe_sur_le_plus_prudent(self):
        """Une faute d'orthographe ne doit pas faire écrire que les
        participants ont donné leur accord."""
        assert lire("oui") is Information.RIEN
        assert lire("") is Information.RIEN


class TestMention:
    def test_chaque_etat_a_sa_phrase(self):
        for etat in Information:
            assert mention(etat)

    def test_rien_est_dit_tel_quel(self):
        """Prétendre le contraire serait pire que de l'avouer."""
        assert "n'a pas été tracée" in mention(Information.RIEN)

    def test_annonce_ne_pretend_pas_a_un_accord(self):
        phrase = mention(Information.ANNONCE)
        assert "informés" in phrase
        assert "accord" not in phrase

    def test_l_accord_est_distingue_de_l_annonce(self):
        assert "accord" in mention(Information.ACCORD)

    def test_toutes_disent_que_la_reunion_est_enregistree(self):
        for phrase in MENTIONS.values():
            assert "enregistrée" in phrase


class TestCeQuiResteAFaire:
    def test_rien_de_trace_reste_a_faire(self):
        assert a_tracer(Information.RIEN) is True

    def test_une_annonce_tracee_suffit(self):
        assert a_tracer(Information.ANNONCE) is False
        assert a_tracer(Information.ACCORD) is False

    def test_le_rappel_dit_pourquoi_et_quoi_faire(self):
        aplati = " ".join(RAPPEL.split())
        assert "donnée biométrique" in aplati
        assert "prévenir les participants" in aplati
