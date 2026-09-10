"""Reconstruire une réunion depuis le fil du direct, faute de traitement.

Le 2026-09-09, une réunion n'a jamais été finalisée : le fil existait, mais
rien ne savait le lire. La différence que ces tests protègent est celle entre
approximatif et perdu.
"""

from pathlib import Path

from greffier.application.recover import WARNING, depuis_le_fil
from greffier.domain.models import Span, SpeakerTurn


def turn(number: int, start: float, end: float, text: str, voice: str) -> dict:
    return {"genre": "tour", "numero": number, "debut": start, "fin": end,
            "texte": text, "voix": voice, "nom": None,
            "certitude": "inconnue", "rang": 1}


THREAD = [
    {"genre": "etat", "message": "Transcription en direct active.", "actif": True},
    turn(1, 0.0, 5.0, "Bonjour à tous.", "v1"),
    turn(2, 5.0, 11.0, "On commence par la recette.", "v1"),
    turn(3, 12.0, 18.0, "Elle est décalée à jeudi.", "v2"),
]


class TestReconstruction:
    def test_les_paroles_deviennent_des_repliques(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert [r.text for r in meeting.utterances] == [
            "Bonjour à tous.", "On commence par la recette.", "Elle est décalée à jeudi."
        ]

    def test_les_voix_sont_conservees(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert {t.voice for t in meeting.turns} == {"v1", "v2"}

    def test_la_duree_vient_du_dernier_tour(self):
        assert depuis_le_fil("2026-09-09_10h05_reunion", THREAD).duration == 18.0

    def test_la_date_vient_de_l_identifiant(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert meeting.started_at is not None
        assert (meeting.started_at.hour, meeting.started_at.minute) == (10, 5)

    def test_les_lignes_sans_parole_sont_ecartees(self):
        meeting = depuis_le_fil("x", [{"genre": "etat", "message": "actif"}])
        assert meeting.utterances == []

    def test_un_texte_vide_n_est_pas_une_replique(self):
        meeting = depuis_le_fil("x", [turn(1, 0.0, 2.0, "   ", "v1")])
        assert meeting.utterances == []

    def test_l_audio_est_repris_quand_il_existe(self):
        meeting = depuis_le_fil("x", THREAD, audio=Path("/tmp/x.wav"))
        assert meeting.audio == Path("/tmp/x.wav")


class TestHonnetete:
    """Une transcription de moindre qualité ne doit pas passer pour ordinaire."""

    def test_la_reunion_porte_son_avertissement(self):
        meeting = depuis_le_fil("2026-09-09_10h05_reunion", THREAD)
        assert meeting.warnings == [WARNING]

    def test_l_avertissement_dit_ce_qui_est_moins_bon(self):
        aplati = " ".join(WARNING.split())
        assert "modèle rapide" in aplati
        assert "approximative" in aplati

    def test_il_dit_aussi_quoi_faire_de_mieux(self):
        assert "Retraiter" in WARNING


class TestRecollage:
    """Le direct découpe par tranches : une minute de parole fait six tours."""

    def test_les_tours_consecutifs_d_une_voix_se_recollent(self):
        from greffier.application.recover import join_spans

        turns = [
            SpeakerTurn(Span(0, 10), "v1"),
            SpeakerTurn(Span(10, 20), "v1"),
            SpeakerTurn(Span(20, 30), "v2"),
        ]
        recolles = join_spans(turns)
        assert len(recolles) == 2
        assert recolles[0].span.end == 20

    def test_un_changement_de_voix_coupe(self):
        from greffier.application.recover import join_spans

        turns = [SpeakerTurn(Span(0, 10), "v1"),
                 SpeakerTurn(Span(10, 20), "v2")]
        assert len(join_spans(turns)) == 2

    def test_un_trou_ne_se_recolle_pas(self):
        from greffier.application.recover import join_spans

        turns = [SpeakerTurn(Span(0, 10), "v1"),
                 SpeakerTurn(Span(60, 70), "v1")]
        assert len(join_spans(turns)) == 2

    def test_une_liste_vide_ne_leve_pas(self):
        from greffier.application.recover import join_spans

        assert join_spans([]) == []
