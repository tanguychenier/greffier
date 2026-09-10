"""Les génériques inventés par le modèle, et ce qui doit rester.

Constaté dans un fil réel le 2026-09-02 : « (sous titré réalisé par… ) »
affiché comme une prise de parole. Whisper a été entraîné sur des vidéos
sous-titrées et comble les silences avec ce qu'il y a le plus vu.
"""

import pytest

from greffier.domain.boilerplate import collapse_loops, is_an_annotation, is_boilerplate
from greffier.domain.models import Span, Utterance
from greffier.domain.profiles.french import FRENCH


class TestCeQuiEstEcarte:
    @pytest.mark.parametrize("text", [
        "Sous-titrage réalisé par la communauté d'Amara.org",
        "sous-titrage réalisé par",
        "Sous-titres réalisés par la communauté",
        "Merci d'avoir regardé cette vidéo !",
        "MERCI D'AVOIR REGARDÉ CETTE VIDÉO",
        "Abonnez-vous !",
        "Sous-titrage Société Radio-Canada",
        "  Sous-titrage.  ",
    ])
    def test_un_generique_entier_part(self, text):
        assert is_boilerplate(text, FRENCH)


class TestCeQuiReste:
    @pytest.mark.parametrize("text", [
        "Merci.",
        "Merci Sophie, on valide jeudi.",
        "On a sous-titré la vidéo de présentation, c'est fait.",
        "Abonnez-vous à la liste de diffusion du projet, je vous envoie le lien.",
        "",
        "   ",
    ])
    def test_la_parole_reelle_reste(self, text):
        """Mieux vaut laisser passer un générique que perdre une décision."""
        assert not is_boilerplate(text, FRENCH)

    @pytest.mark.parametrize("text", [
        "Merci d'avoir regardé le ticket, il est passé en recette.",
        "Merci d'avoir regardé cette vidéo, mais revenons au calendrier de la "
        "recette : il faut trancher avant jeudi.",
        "Sous-titrage réalisé par nos soins, et validé par la communication.",
    ])
    def test_une_phrase_qui_commence_comme_un_generique_mais_continue(self, text):
        """Le piège de la correspondance par préfixe : cette phrase-là
        disparaissait, alors qu'elle porte une information."""
        assert not is_boilerplate(text, FRENCH)


class TestAnnotations:
    """Ce que le modèle écrit quand il entend du son sans parole.

    Relevé dans le fil d'une réunion réelle : « *Belouge* » inscrit comme une
    prise de parole, avec sa propre empreinte de voix — donc une voix de plus
    dans une réunion qui n'en comptait que quelques-unes.
    """

    def test_une_annotation_entre_asterisques_part(self):
        assert is_an_annotation("*Belouge*")

    def test_une_annotation_entre_parentheses_part(self):
        assert is_an_annotation("(rires)")
        assert is_an_annotation("[Applaudissements]")

    def test_une_note_de_musique_part(self):
        assert is_an_annotation("♪ ♪ ♪")

    def test_une_parenthese_au_milieu_d_une_phrase_reste(self):
        """Couper là perdrait la phrase."""
        assert not is_an_annotation("il a dit (à tort) que c'était prêt")

    def test_deux_annotations_dans_une_phrase_ne_font_pas_une_annotation(self):
        assert not is_an_annotation("(a) et (b) sont prêts")

    def test_une_phrase_ordinaire_reste(self):
        assert not is_an_annotation("on reprend le sujet lundi")

    def test_un_texte_trop_court_ne_declenche_rien(self):
        assert not is_an_annotation("**")



class TestLaBoucleDuTranscripteur:
    """Onze fois la même phrase de suite, c'est le modèle, pas une personne.

    Mesuré sur la réunion du 2026-09-10 à 13 h 08 : « Est-ce que tu entends
    Lucie ? » inscrit **onze fois**, en onze tours consécutifs d'une seconde,
    et trois autres boucles à côté. Sur cent vingt-cinq tours du fil,
    soixante-cinq étaient de la répétition. Whisper fait cela sur du
    quasi-silence.
    """

    def _boucle(self, how_many: int, texte: str = "Est-ce que tu entends Lucie ?"):
        return [
            Utterance(span=Span(30.0 + i, 31.0 + i), text=texte)
            for i in range(how_many)
        ]

    def test_onze_repetitions_deviennent_une(self):
        assert len(collapse_loops(self._boucle(11))) == 1

    def test_la_phrase_gardee_couvre_tout_le_passage(self):
        """Le passage a bien duré onze secondes : l'horodatage doit le dire."""
        gardee = collapse_loops(self._boucle(11))[0]
        assert (gardee.span.start, gardee.span.end) == (30.0, 41.0)

    def test_deux_fois_de_suite_est_une_personne(self):
        """Quelqu'un se répète, ou deux tranches se recouvrent. On n'y touche pas."""
        assert len(collapse_loops(self._boucle(2))) == 2

    def test_trois_fois_est_une_boucle(self):
        assert len(collapse_loops(self._boucle(3))) == 1

    def test_une_respiration_coupe_la_boucle(self):
        """Une personne qui repose sa question laisse un souffle.

        Trois segments collés se replient ; celui qui arrive après le silence
        reste une phrase à part, parce qu'il a été dit à part.
        """
        dites = [
            Utterance(span=Span(0.0, 1.0), text="tu m'entends ?"),
            Utterance(span=Span(1.0, 2.0), text="tu m'entends ?"),
            Utterance(span=Span(2.0, 3.0), text="tu m'entends ?"),
            Utterance(span=Span(9.0, 10.0), text="tu m'entends ?"),
        ]
        gardees = collapse_loops(dites)
        assert len(gardees) == 2
        assert (gardees[0].span.start, gardees[0].span.end) == (0.0, 3.0)
        assert gardees[1].span.start == 9.0

    def test_deux_boucles_de_suite_sont_deux_phrases(self):
        dites = self._boucle(4) + [
            Utterance(span=Span(34.0 + i, 35.0 + i), text="Je vais vous créer la vache.")
            for i in range(4)
        ]
        gardees = collapse_loops(dites)
        assert len(gardees) == 2
        assert gardees[0].text != gardees[1].text

    def test_la_casse_et_les_accents_ne_font_pas_deux_phrases(self):
        dites = [
            Utterance(span=Span(0.0, 1.0), text="Voilà."),
            Utterance(span=Span(1.0, 2.0), text="voila"),
            Utterance(span=Span(2.0, 3.0), text="VOILÀ !"),
        ]
        assert len(collapse_loops(dites)) == 1

    def test_une_conversation_ordinaire_n_est_pas_touchee(self):
        dites = [
            Utterance(span=Span(0.0, 3.0), text="on cale la recette jeudi"),
            Utterance(span=Span(3.0, 6.0), text="d'accord, je prévois les tests"),
            Utterance(span=Span(6.0, 9.0), text="et la mise en prod lundi"),
        ]
        assert collapse_loops(dites) == dites

    def test_une_liste_vide_ou_courte_ne_casse_rien(self):
        assert collapse_loops([]) == []
        assert len(collapse_loops(self._boucle(1))) == 1
