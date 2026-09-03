"""Ce que la fenêtre calcule avant d'afficher, éprouvé sans écran.

Ce qui touche à Tk n'est pas testé ici : Tk ne démarre pas sur un exécuteur
d'intégration continue. Ce qui se teste, c'est ce que la fenêtre calcule avant
d'afficher, et c'est justement là que les erreurs de lecture se produisent.
"""

from __future__ import annotations

from pathlib import Path

from greffier.interface.lisible import etat_du_direct as _etat_du_direct
from greffier.interface.lisible import horloge as _horloge
from greffier.interface.lisible import sujet_lisible as _sujet_lisible


class TestHorloge:
    def test_sous_l_heure_on_montre_minutes_et_secondes(self) -> None:
        assert _horloge(0) == "0:00"
        assert _horloge(65) == "1:05"
        assert _horloge(3599) == "59:59"

    def test_au_dela_de_l_heure_on_ajoute_les_heures(self) -> None:
        assert _horloge(3600) == "1:00:00"
        assert _horloge(3725) == "1:02:05"

    def test_une_duree_negative_ne_produit_pas_d_horreur(self) -> None:
        # La durée est calculée en retirant le temps de pause : un état incohérent
        # ne doit pas afficher « -1:-1 » en gros au milieu de la fenêtre.
        assert _horloge(-5).startswith("0:") or _horloge(-5) == "0:00"


class TestSujetLisible:
    def test_le_titre_du_compte_rendu_remplace_l_horodatage(self, tmp_path: Path) -> None:
        # « 2026-08-25_14h33_reunion » ne dit rien de ce qui s'est passé.
        compte_rendu = tmp_path / "cr.md"
        compte_rendu.write_text("# Compte rendu : bug photos et signature Fast\n")
        assert _sujet_lisible("2026-08-25_14h33_reunion", compte_rendu) == (
            "bug photos et signature Fast"
        )

    def test_sans_compte_rendu_l_identifiant_reste(self, tmp_path: Path) -> None:
        assert _sujet_lisible("2026-08-25_14h33_x", tmp_path / "absent.md") == (
            "2026-08-25_14h33_x"
        )

    def test_un_titre_sans_deux_points_est_gardé_entier(self, tmp_path: Path) -> None:
        compte_rendu = tmp_path / "cr.md"
        compte_rendu.write_text("# Point hebdomadaire\n")
        assert _sujet_lisible("id", compte_rendu) == "Point hebdomadaire"

    def test_un_compte_rendu_sans_titre_laisse_l_identifiant(self, tmp_path: Path) -> None:
        compte_rendu = tmp_path / "cr.md"
        compte_rendu.write_text("Du texte, mais pas de titre.\n")
        assert _sujet_lisible("mon-id", compte_rendu) == "mon-id"

    def test_un_titre_reduit_aux_deux_points_ne_vide_pas_la_colonne(
        self, tmp_path: Path
    ) -> None:
        compte_rendu = tmp_path / "cr.md"
        compte_rendu.write_text("# Compte rendu :\n")
        assert _sujet_lisible("mon-id", compte_rendu) == "Compte rendu :"


class TestEtatDuDirect:
    """Ce que dit l'onglet du fil quand il n'a rien à montrer.

    Un onglet vide se lit « personne ne parle » alors qu'il veut souvent dire
    « rien n'écoute » : modèle absent, processus non lancé. La différence est
    celle entre attendre et perdre sa réunion.
    """

    def test_hors_reunion_on_explique_a_quoi_sert_l_onglet(self) -> None:
        dit = _etat_du_direct(en_reunion=False, annonce="", phrases=0)
        assert "Aucune réunion en cours" in dit

    def test_un_modele_absent_est_dit_plutot_que_montre_par_un_vide(self) -> None:
        dit = _etat_du_direct(
            en_reunion=True, annonce="Aucun modèle de transcription : le fil restera vide.",
            phrases=0,
        )
        assert "Aucun modèle" in dit

    def test_avant_la_premiere_tranche_on_dit_qu_on_attend(self) -> None:
        assert "attente" in _etat_du_direct(en_reunion=True, annonce="", phrases=0)

    def test_des_qu_il_y_a_du_texte_on_rappelle_comment_corriger(self) -> None:
        dit = _etat_du_direct(en_reunion=True, annonce="", phrases=14)
        assert "14 phrase(s)" in dit
        assert "corriger" in dit
