"""Le fil du direct, rendu en texte pour qu'on puisse l'interroger."""

from greffier.domaine.direct import Fil, TourDirect
from greffier.domaine.modeles import Intervalle


def fil_avec(*tours: tuple[int, float, float, str, str]) -> Fil:
    fil = Fil()
    for numero, debut, fin, texte, voix in tours:
        fil.tours.append(TourDirect(numero, Intervalle(debut, fin), texte, voix))
    return fil


class TestRenduDuFil:
    """Avant, la conversation exigeait un compte rendu, donc une réunion finie.

    Impossible de demander « qu'a-t-on décidé sur Oasis ? » pendant qu'on en
    parle, alors que le fil était déjà là.
    """

    def test_le_texte_est_horodate_et_attribue(self):
        rendu = fil_avec((1, 0.0, 5.0, "Bonjour à tous.", "v1")).rendu()
        assert "00:00" in rendu
        assert "Bonjour à tous." in rendu

    def test_les_tours_d_une_meme_voix_sont_regroupes(self):
        """Une étiquette par phrase rend le texte illisible pour qui le résume."""
        rendu = fil_avec(
            (1, 0.0, 5.0, "Première phrase.", "v1"),
            (2, 5.0, 9.0, "Seconde phrase.", "v1"),
        ).rendu()
        etiquettes = [ligne for ligne in rendu.splitlines() if ligne.startswith("[")]
        assert len(etiquettes) == 1

    def test_un_changement_de_voix_ouvre_un_bloc(self):
        rendu = fil_avec(
            (1, 0.0, 5.0, "Moi d'abord.", "v1"),
            (2, 5.0, 9.0, "Moi ensuite.", "v2"),
        ).rendu()
        assert len([ligne for ligne in rendu.splitlines() if ligne.startswith("[")]) == 2

    def test_un_fil_vide_ne_rend_rien(self):
        assert Fil().rendu() == ""

    def test_les_tours_sans_texte_sont_ecartes(self):
        assert fil_avec((1, 0.0, 5.0, "   ", "v1")).rendu() == ""

    def test_on_peut_ne_demander_que_la_fin(self):
        """Une longue réunion n'a pas à repartir en entier à chaque question."""
        rendu = fil_avec(
            (1, 0.0, 10.0, "Le début, très ancien.", "v1"),
            (2, 600.0, 610.0, "La fin, celle qui compte.", "v1"),
        ).rendu(depuis=300.0)
        assert "celle qui compte" in rendu
        assert "très ancien" not in rendu

    def test_l_horodatage_passe_la_minute(self):
        rendu = fil_avec((1, 125.0, 130.0, "Deux minutes cinq.", "v1")).rendu()
        assert "02:05" in rendu
