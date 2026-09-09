"""Reconstruire une réunion depuis le fil du direct, faute de traitement.

Le 2026-09-09, une réunion n'a jamais été finalisée : le fil existait, mais
rien ne savait le lire. La différence que ces tests protègent est celle entre
approximatif et perdu.
"""

from pathlib import Path

from greffier.application.recuperer import AVERTISSEMENT, depuis_le_fil
from greffier.domaine.modeles import Intervalle, TourDeParole


def tour(numero: int, debut: float, fin: float, texte: str, voix: str) -> dict:
    return {"genre": "tour", "numero": numero, "debut": debut, "fin": fin,
            "texte": texte, "voix": voix, "nom": None,
            "certitude": "inconnue", "rang": 1}


FIL = [
    {"genre": "etat", "message": "Transcription en direct active.", "actif": True},
    tour(1, 0.0, 5.0, "Bonjour à tous.", "v1"),
    tour(2, 5.0, 11.0, "On commence par la recette.", "v1"),
    tour(3, 12.0, 18.0, "Elle est décalée à jeudi.", "v2"),
]


class TestReconstruction:
    def test_les_paroles_deviennent_des_repliques(self):
        reunion = depuis_le_fil("2026-09-09_10h05_reunion", FIL)
        assert [r.texte for r in reunion.repliques] == [
            "Bonjour à tous.", "On commence par la recette.", "Elle est décalée à jeudi."
        ]

    def test_les_voix_sont_conservees(self):
        reunion = depuis_le_fil("2026-09-09_10h05_reunion", FIL)
        assert {t.voix for t in reunion.tours} == {"v1", "v2"}

    def test_la_duree_vient_du_dernier_tour(self):
        assert depuis_le_fil("2026-09-09_10h05_reunion", FIL).duree == 18.0

    def test_la_date_vient_de_l_identifiant(self):
        reunion = depuis_le_fil("2026-09-09_10h05_reunion", FIL)
        assert reunion.commencee_le is not None
        assert (reunion.commencee_le.hour, reunion.commencee_le.minute) == (10, 5)

    def test_les_lignes_sans_parole_sont_ecartees(self):
        reunion = depuis_le_fil("x", [{"genre": "etat", "message": "actif"}])
        assert reunion.repliques == []

    def test_un_texte_vide_n_est_pas_une_replique(self):
        reunion = depuis_le_fil("x", [tour(1, 0.0, 2.0, "   ", "v1")])
        assert reunion.repliques == []

    def test_l_audio_est_repris_quand_il_existe(self):
        reunion = depuis_le_fil("x", FIL, audio=Path("/tmp/x.wav"))
        assert reunion.audio == Path("/tmp/x.wav")


class TestHonnetete:
    """Une transcription de moindre qualité ne doit pas passer pour ordinaire."""

    def test_la_reunion_porte_son_avertissement(self):
        reunion = depuis_le_fil("2026-09-09_10h05_reunion", FIL)
        assert reunion.avertissements == [AVERTISSEMENT]

    def test_l_avertissement_dit_ce_qui_est_moins_bon(self):
        aplati = " ".join(AVERTISSEMENT.split())
        assert "modèle rapide" in aplati
        assert "approximative" in aplati

    def test_il_dit_aussi_quoi_faire_de_mieux(self):
        assert "Retraiter" in AVERTISSEMENT


class TestRecollage:
    """Le direct découpe par tranches : une minute de parole fait six tours."""

    def test_les_tours_consecutifs_d_une_voix_se_recollent(self):
        from greffier.application.recuperer import fusionner_intervalles

        tours = [
            TourDeParole(Intervalle(0, 10), "v1"),
            TourDeParole(Intervalle(10, 20), "v1"),
            TourDeParole(Intervalle(20, 30), "v2"),
        ]
        recolles = fusionner_intervalles(tours)
        assert len(recolles) == 2
        assert recolles[0].intervalle.fin == 20

    def test_un_changement_de_voix_coupe(self):
        from greffier.application.recuperer import fusionner_intervalles

        tours = [TourDeParole(Intervalle(0, 10), "v1"),
                 TourDeParole(Intervalle(10, 20), "v2")]
        assert len(fusionner_intervalles(tours)) == 2

    def test_un_trou_ne_se_recolle_pas(self):
        from greffier.application.recuperer import fusionner_intervalles

        tours = [TourDeParole(Intervalle(0, 10), "v1"),
                 TourDeParole(Intervalle(60, 70), "v1")]
        assert len(fusionner_intervalles(tours)) == 2

    def test_une_liste_vide_ne_leve_pas(self):
        from greffier.application.recuperer import fusionner_intervalles

        assert fusionner_intervalles([]) == []
