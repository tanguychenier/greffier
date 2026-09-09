"""Disposer un arbre sans que rien ne se recouvre."""

from greffier.domaine.carte import Apport, Carte, fusionner
from greffier.domaine.mise_en_page import (
    ENTRE_COLONNES,
    ENTRE_LIGNES,
    LARGEUR,
    disposer,
)


def carte_type() -> Carte:
    carte = Carte("Oasis")
    fusionner(carte, [Apport("Problème A"), Apport("Problème B")])
    fusionner(carte, [Apport("Piste A1", sous="Problème A"),
                      Apport("Piste A2", sous="Problème A")])
    return carte


class TestDisposition:
    def test_tous_les_noeuds_recoivent_une_place(self):
        assert len(disposer(carte_type())) == carte_type().compte

    def test_la_racine_est_a_gauche(self):
        places = disposer(carte_type())
        assert places[0].noeud.texte == "Oasis"
        assert places[0].x == 0

    def test_la_profondeur_donne_la_colonne(self):
        places = {place.noeud.texte: place for place in disposer(carte_type())}
        assert places["Problème A"].x == ENTRE_COLONNES
        assert places["Piste A1"].x == 2 * ENTRE_COLONNES

    def test_le_lien_vers_le_parent_est_donne(self):
        places = {place.noeud.texte: place for place in disposer(carte_type())}
        assert places["Piste A1"].parent == "Problème A"
        assert places["Oasis"].parent == ""

    def test_deux_noeuds_d_une_colonne_ne_se_touchent_pas(self):
        places = disposer(carte_type())
        for colonne in {place.x for place in places}:
            hauteurs = sorted(p.y for p in places if p.x == colonne)
            ecarts = [b - a for a, b in zip(hauteurs, hauteurs[1:], strict=False)]
            assert all(ecart >= ENTRE_LIGNES for ecart in ecarts), colonne

    def test_les_colonnes_sont_plus_ecartees_que_larges(self):
        """Un texte de deux lignes déborde de la boîte annoncée."""
        assert ENTRE_COLONNES > LARGEUR

    def test_un_parent_est_centre_sur_ses_enfants(self):
        """Sinon la carte penche vers le haut à chaque branche chargée."""
        places = {place.noeud.texte: place for place in disposer(carte_type())}
        enfants = [places["Piste A1"].y, places["Piste A2"].y]
        assert places["Problème A"].y == sum(enfants) / 2

    def test_une_carte_d_un_seul_noeud_tient(self):
        places = disposer(Carte("Oasis"))
        assert len(places) == 1 and places[0].x == 0 and places[0].y == 0
