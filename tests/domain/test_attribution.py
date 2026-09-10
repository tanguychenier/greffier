"""Une phrase à cheval sur deux locuteurs ne doit désigner personne."""

from __future__ import annotations

from greffier.domain.attribution import PART_MINIMALE, time_per_voice, voice_of
from greffier.domain.models import Span, SpeakerTurn


def turn(voice: str, start: float, end: float) -> SpeakerTurn:
    return SpeakerTurn(span=Span(start, end), voice=voice)


class TestVoixDe:
    def test_une_phrase_dans_un_seul_tour_va_a_cette_voix(self):
        turns = [turn("0", 0.0, 8.0), turn("1", 8.4, 17.0)]
        assert voice_of(Span(0.0, 7.7), turns) == "0"

    def test_une_phrase_sans_aucun_tour_ne_designe_personne(self):
        assert voice_of(Span(0.0, 5.0), []) is None
        assert voice_of(Span(30.0, 35.0), [turn("0", 0.0, 8.0)]) is None

    def test_un_debord_de_quelques_centiemes_ne_change_rien(self):
        """Les bornes des deux découpes ne coïncident jamais exactement.

        Mesuré : la dernière réplique de la réunion de table tenait 0,98 — un
        chevauchement de 0,2 s sur le tour voisin. Refuser de trancher là
        laisserait la moitié des phrases sans voix.
        """
        turns = [turn("1", 41.9, 50.4), turn("0", 35.0, 41.2)]
        assert voice_of(Span(41.0, 50.4), turns) == "1"

    def test_une_phrase_qui_enjambe_un_changement_de_locuteur_ne_designe_personne(self):
        """Le cas mesuré : « Merci Pierre… », dit par Jacques, donné à Pierre.

        La phrase transcrite couvre 9,6 s du tour de Pierre et 6,1 s de celui
        de Jacques, soit 0,61 pour le meneur. L'ancienne règle du plus bavard
        attribuait la phrase entière à Pierre.
        """
        turns = [turn("pierre", 24.55, 34.14), turn("jacques", 34.96, 41.07)]
        assert voice_of(Span(23.77, 41.07), turns) is None

    def test_un_partage_moitie_moitie_ne_designe_personne(self):
        turns = [turn("0", 0.0, 5.0), turn("1", 5.0, 10.0)]
        assert voice_of(Span(0.0, 10.0), turns) is None

    def test_le_seuil_est_franchi_a_la_part_minimale(self):
        """Pile au seuil, on tranche : le refus commence en dessous."""
        turns = [turn("0", 0.0, 8.0), turn("1", 8.0, 10.0)]
        assert voice_of(Span(0.0, 10.0), turns, PART_MINIMALE) == "0"
        assert voice_of(Span(0.0, 10.0), turns, 0.81) is None

    def test_les_morceaux_epars_d_une_meme_voix_se_cumulent(self):
        """Une voix coupée en deux par une interjection reste la même voix."""
        turns = [turn("0", 0.0, 4.0), turn("1", 4.0, 4.5), turn("0", 4.5, 10.0)]
        assert voice_of(Span(0.0, 10.0), turns) == "0"


class TestTempsParVoix:
    def test_chaque_voix_recoit_son_temps_de_recouvrement(self):
        turns = [turn("0", 0.0, 4.0), turn("1", 4.0, 10.0)]
        assert time_per_voice(Span(2.0, 6.0), turns) == {"0": 2.0, "1": 2.0}

    def test_un_tour_hors_de_la_phrase_ne_compte_pas(self):
        assert time_per_voice(Span(0.0, 3.0), [turn("0", 5.0, 9.0)]) == {}
