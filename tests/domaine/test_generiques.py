"""Les génériques inventés par le modèle, et ce qui doit rester.

Constaté dans un fil réel le 2026-09-02 : « (sous titré réalisé par… ) »
affiché comme une prise de parole. Whisper a été entraîné sur des vidéos
sous-titrées et comble les silences avec ce qu'il y a le plus vu.
"""

import pytest

from greffier.domaine.generiques import est_un_generique, est_une_annotation
from greffier.domaine.profils.francais import FRANCAIS


class TestCeQuiEstEcarte:
    @pytest.mark.parametrize("texte", [
        "Sous-titrage réalisé par la communauté d'Amara.org",
        "sous-titrage réalisé par",
        "Sous-titres réalisés par la communauté",
        "Merci d'avoir regardé cette vidéo !",
        "MERCI D'AVOIR REGARDÉ CETTE VIDÉO",
        "Abonnez-vous !",
        "Sous-titrage Société Radio-Canada",
        "  Sous-titrage.  ",
    ])
    def test_un_generique_entier_part(self, texte):
        assert est_un_generique(texte, FRANCAIS)


class TestCeQuiReste:
    @pytest.mark.parametrize("texte", [
        "Merci.",
        "Merci Sophie, on valide jeudi.",
        "On a sous-titré la vidéo de présentation, c'est fait.",
        "Abonnez-vous à la liste de diffusion du projet, je vous envoie le lien.",
        "",
        "   ",
    ])
    def test_la_parole_reelle_reste(self, texte):
        """Mieux vaut laisser passer un générique que perdre une décision."""
        assert not est_un_generique(texte, FRANCAIS)

    @pytest.mark.parametrize("texte", [
        "Merci d'avoir regardé le ticket, il est passé en recette.",
        "Merci d'avoir regardé cette vidéo, mais revenons au calendrier de la "
        "recette : il faut trancher avant jeudi.",
        "Sous-titrage réalisé par nos soins, et validé par la communication.",
    ])
    def test_une_phrase_qui_commence_comme_un_generique_mais_continue(self, texte):
        """Le piège de la correspondance par préfixe : cette phrase-là
        disparaissait, alors qu'elle porte une information."""
        assert not est_un_generique(texte, FRANCAIS)


class TestAnnotations:
    """Ce que le modèle écrit quand il entend du son sans parole.

    Relevé dans le fil d'une réunion réelle : « *Belouge* » inscrit comme une
    prise de parole, avec sa propre empreinte de voix — donc une voix de plus
    dans une réunion qui n'en comptait que quelques-unes.
    """

    def test_une_annotation_entre_asterisques_part(self):
        assert est_une_annotation("*Belouge*")

    def test_une_annotation_entre_parentheses_part(self):
        assert est_une_annotation("(rires)")
        assert est_une_annotation("[Applaudissements]")

    def test_une_note_de_musique_part(self):
        assert est_une_annotation("♪ ♪ ♪")

    def test_une_parenthese_au_milieu_d_une_phrase_reste(self):
        """Couper là perdrait la phrase."""
        assert not est_une_annotation("il a dit (à tort) que c'était prêt")

    def test_deux_annotations_dans_une_phrase_ne_font_pas_une_annotation(self):
        assert not est_une_annotation("(a) et (b) sont prêts")

    def test_une_phrase_ordinaire_reste(self):
        assert not est_une_annotation("on reprend le sujet lundi")

    def test_un_texte_trop_court_ne_declenche_rien(self):
        assert not est_une_annotation("**")

