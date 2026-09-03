"""Les génériques inventés par le modèle, et ce qui doit rester.

Constaté dans un fil réel le 2026-09-02 : « (sous titré réalisé par… ) »
affiché comme une prise de parole. Whisper a été entraîné sur des vidéos
sous-titrées et comble les silences avec ce qu'il y a le plus vu.
"""

import pytest

from greffier.domaine.generiques import est_un_generique


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
        assert est_un_generique(texte)


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
        assert not est_un_generique(texte)

    @pytest.mark.parametrize("texte", [
        "Merci d'avoir regardé le ticket, il est passé en recette.",
        "Merci d'avoir regardé cette vidéo, mais revenons au calendrier de la "
        "recette : il faut trancher avant jeudi.",
        "Sous-titrage réalisé par nos soins, et validé par la communication.",
    ])
    def test_une_phrase_qui_commence_comme_un_generique_mais_continue(self, texte):
        """Le piège de la correspondance par préfixe : cette phrase-là
        disparaissait, alors qu'elle porte une information."""
        assert not est_un_generique(texte)
