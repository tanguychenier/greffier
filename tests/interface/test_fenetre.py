"""Ce que la fenêtre calcule avant d'afficher, éprouvé sans écran.

Ce qui touche à Tk n'est pas testé ici : Tk ne démarre pas sur un exécuteur
d'intégration continue. Ce qui se teste, c'est ce que la fenêtre calcule avant
d'afficher, et c'est justement là que les erreurs de lecture se produisent.
"""

from __future__ import annotations

from pathlib import Path

from greffier.interface.readable import button_grid as _grille
from greffier.interface.readable import clock as _clock
from greffier.interface.readable import dot_marker as _marque
from greffier.interface.readable import live_state_line as _live_state_line
from greffier.interface.readable import readable_subject as _readable_subject


class TestHorloge:
    def test_sous_l_heure_on_montre_minutes_et_secondes(self) -> None:
        assert _clock(0) == "0:00"
        assert _clock(65) == "1:05"
        assert _clock(3599) == "59:59"

    def test_au_dela_de_l_heure_on_ajoute_les_heures(self) -> None:
        assert _clock(3600) == "1:00:00"
        assert _clock(3725) == "1:02:05"

    def test_une_duree_negative_ne_produit_pas_d_horreur(self) -> None:
        # La durée est calculée en retirant le temps de pause : un état incohérent
        # ne doit pas afficher « -1:-1 » en gros au milieu de la fenêtre.
        assert _clock(-5).startswith("0:") or _clock(-5) == "0:00"


class TestSujetLisible:
    def test_le_titre_du_compte_rendu_remplace_l_horodatage(self, tmp_path: Path) -> None:
        # « 2026-08-25_14h33_reunion » ne dit rien de ce qui s'est passé.
        minutes = tmp_path / "cr.md"
        minutes.write_text("# Compte rendu : bug photos et signature Fast\n")
        assert _readable_subject("2026-08-25_14h33_reunion", minutes) == (
            "bug photos et signature Fast"
        )

    def test_sans_compte_rendu_l_identifiant_reste(self, tmp_path: Path) -> None:
        assert _readable_subject("2026-08-25_14h33_x", tmp_path / "absent.md") == (
            "2026-08-25_14h33_x"
        )

    def test_un_titre_sans_deux_points_est_gardé_entier(self, tmp_path: Path) -> None:
        minutes = tmp_path / "cr.md"
        minutes.write_text("# Point hebdomadaire\n")
        assert _readable_subject("id", minutes) == "Point hebdomadaire"

    def test_un_compte_rendu_sans_titre_laisse_l_identifiant(self, tmp_path: Path) -> None:
        minutes = tmp_path / "cr.md"
        minutes.write_text("Du texte, mais pas de titre.\n")
        assert _readable_subject("mon-id", minutes) == "mon-id"

    def test_un_titre_reduit_aux_deux_points_ne_vide_pas_la_colonne(
        self, tmp_path: Path
    ) -> None:
        minutes = tmp_path / "cr.md"
        minutes.write_text("# Compte rendu :\n")
        assert _readable_subject("mon-id", minutes) == "Compte rendu :"


class TestEtatDuDirect:
    """Ce que dit l'onglet du fil quand il n'a rien à montrer.

    Un onglet vide se lit « personne ne parle » alors qu'il veut souvent dire
    « rien n'écoute » : modèle absent, processus non lancé. La différence est
    celle entre attendre et perdre sa réunion.
    """

    def test_hors_reunion_on_explique_a_quoi_sert_l_onglet(self) -> None:
        dit = _live_state_line(en_reunion=False, annonce="", sentences=0)
        assert "Aucune réunion en cours" in dit

    def test_un_modele_absent_est_dit_plutot_que_montre_par_un_vide(self) -> None:
        dit = _live_state_line(
            en_reunion=True, annonce="Aucun modèle de transcription : le fil restera vide.",
            sentences=0,
        )
        assert "Aucun modèle" in dit

    def test_avant_la_premiere_tranche_on_dit_qu_on_attend(self) -> None:
        assert "attente" in _live_state_line(en_reunion=True, annonce="", sentences=0)

    def test_des_qu_il_y_a_du_texte_on_rappelle_comment_corriger(self) -> None:
        dit = _live_state_line(en_reunion=True, annonce="", sentences=14)
        assert "14 phrase(s)" in dit
        assert "corriger" in dit


class TestPastilleDOnglet:
    """Le compte posé sur un onglet qu'on ne regarde pas.

    Demandé à l'usage, sur le modèle du panier d'un site marchand : on doit
    savoir qu'il y a quelque chose à voir sans être sur l'onglet, et sans
    qu'une fenêtre surgisse au milieu d'une réunion.
    """

    def test_rien_a_signaler_ne_dessine_rien(self) -> None:
        assert _marque(0) == ""
        assert _marque(-1) == ""

    def test_le_compte_s_affiche_tel_quel(self) -> None:
        assert _marque(1) == "1"
        assert _marque(9) == "9"

    def test_au_dela_de_neuf_le_nombre_exact_n_aide_plus(self) -> None:
        """Deux chiffres déborderaient du disque, et « beaucoup » suffit."""
        assert _marque(10) == "9+"
        assert _marque(42) == "9+"


class TestBarreDeBoutons:
    """Le septième bouton de l'onglet Réunions sortait de la fenêtre.

    Invisible et inatteignable — le défaut même contre lequel le module
    d'apparence met en garde, en haut de son fichier, à propos d'un bouton
    poussé hors du cadre. Puis, une fois qu'il passait à la ligne, la
    répartition était mauvaise : cinq boutons contre deux, et des bords qui ne
    tombaient pas ensemble.
    """

    #: Les largeurs demandées dans l'onglet Réunions, dans l'ordre.
    #: « Envoyer par courriel » vaut 180 : le libellé complet, parce que
    #: « Envoyer » seul ne dit pas ce qui est envoyé.
    MEETINGS = [100, 100, 96, 180, 116, 110, 110, 116]

    def test_tout_tient_sur_un_rang_quand_la_place_est_la(self) -> None:
        by_rank, _ = _grille(self.MEETINGS, 2000)
        assert by_rank == len(self.MEETINGS)

    def test_la_place_manquante_fait_passer_a_la_ligne(self) -> None:
        by_rank, _ = _grille(self.MEETINGS, 500)
        assert by_rank < 7

    def test_les_rangs_sont_equilibres(self) -> None:
        """Huit boutons sur deux rangs donnent 4 et 4, jamais 6 et 2.

        Un premier rang plein contre un second presque vide est le défaut le
        plus visible d'une barre qui passe à la ligne.
        """
        by_rank, _ = _grille(self.MEETINGS, 775)
        assert by_rank == 4
        assert len(self.MEETINGS) - by_rank == 4

    def test_les_colonnes_ont_toutes_la_meme_largeur(self) -> None:
        """Des bords qui ne tombent pas ensemble se lisent comme bâclés."""
        _, colonne = _grille(self.MEETINGS, 775)
        assert colonne >= max(self.MEETINGS), "au moins la largeur du plus large"

    def test_l_etirement_est_plafonne(self) -> None:
        """Remplir sans limite donnait des boutons de 290 px pour un « Ouvrir »
        de 96, étirés sur du vide. Un bouton disproportionné est aussi mal
        réparti qu'un bouton qui déborde."""
        from greffier.interface.readable import ETIREMENT_MAXIMUM

        _, colonne = _grille(self.MEETINGS, 2000)
        assert colonne <= max(self.MEETINGS) * ETIREMENT_MAXIMUM

    def test_le_libelle_le_plus_long_tient_dans_la_largeur_minimale(self) -> None:
        """C'est ce qui permet de garder « Envoyer par courriel » en entier :
        quatre colonnes de 187 px tiennent dans les 775 px offerts."""
        by_rank, colonne = _grille(self.MEETINGS, 775)
        assert by_rank == 4
        assert colonne >= max(self.MEETINGS)

    def test_rien_ne_depasse_jamais_de_la_largeur(self) -> None:
        for offerte in range(200, 1500, 17):
            by_rank, colonne = _grille(self.MEETINGS, offerte)
            largeur_totale = by_rank * colonne + (by_rank - 1) * 9
            assert by_rank >= 1
            if by_rank > 1:
                assert largeur_totale <= offerte, offerte

    def test_a_l_etroit_il_reste_une_colonne(self) -> None:
        """Zéro colonne ferait disparaître la barre entière."""
        by_rank, colonne = _grille(self.MEETINGS, 10)
        assert by_rank == 1
        assert colonne == max(self.MEETINGS), "le bouton garde sa largeur minimale"

    def test_sans_bouton_le_calcul_ne_leve_pas(self) -> None:
        assert _grille([], 800) == (1, 0)


class TestEchecPublie:
    """Un échec de traitement doit s'écrire dans l'état, pas seulement à l'écran.

    Le défaut, constaté le 2026-09-10 sur une réunion de 1 h 42 : la chaîne a
    échoué à l'envoi, l'échec n'était rapporté que par une boîte de dialogue
    modale, et l'état est resté figé sur « envoi ». Écran verrouillé, personne
    pour cliquer. Tout ce qui relit cet état — la veille, la ligne de commande,
    la reconstruction de l'application — croyait qu'une réunion se traitait
    encore, deux heures après la fin de la réunion.
    """

    def _config(self, tmp_path: Path):
        from greffier.adapters.configuration import Config

        return Config(paths={"donnees": tmp_path, "modeles": tmp_path / "modeles"})

    def _etat_en_cours(self, tmp_path: Path, identifier: str) -> Path:
        import json

        state = tmp_path / "etat.json"
        state.write_text(json.dumps({
            "phase": "envoi", "message": "Envoi du compte rendu…",
            "nom": "reunion", "identifiant": identifier,
            "audio": str(tmp_path / f"{identifier}.wav"),
        }), encoding="utf-8")
        return state

    def _publish(
        self, tmp_path: Path, identifier: str, trouble: Exception,
        dans_l_etat: str | None = None,
    ) -> dict:
        import json

        from greffier.interface.window import Window

        state = self._etat_en_cours(tmp_path, dans_l_etat or identifier)
        # Sans Tk : la méthode ne lit que `self.config`, et c'est justement ce
        # qui la rend éprouvable sans écran.
        without_a_screen = type("SansEcran", (), {"config": self._config(tmp_path)})()
        Window._publish_the_failure(without_a_screen, identifier, trouble)
        return json.loads(state.read_text(encoding="utf-8"))

    def test_la_phase_cesse_de_mentir(self, tmp_path: Path) -> None:
        state = self._publish(tmp_path, "2026-09-10_10h10_reunion", RuntimeError("boum"))
        assert state["phase"] == "echec", state

    def test_la_raison_est_gardee(self, tmp_path: Path) -> None:
        """Pour la lire après coup, quand la fenêtre modale est passée."""
        state = self._publish(
            tmp_path, "2026-09-10_10h10_reunion", RuntimeError("Outlook refuse")
        )
        assert "Outlook refuse" in state["message"]

    def test_l_etat_d_une_autre_reunion_n_est_pas_touche(self, tmp_path: Path) -> None:
        """La règle du journal : il n'écrit que si l'état porte cette réunion."""
        state = self._publish(
            tmp_path, "2026-09-10_11h00_autre", RuntimeError("boum"),
            dans_l_etat="2026-09-10_10h10_reunion",
        )
        assert state["phase"] == "envoi"

    def test_un_etat_illisible_ne_releve_rien(self, tmp_path: Path) -> None:
        """On est déjà dans le traitement d'une erreur : une seconde erreur ici
        ferait perdre le message de la première."""
        from greffier.interface.window import Window

        (tmp_path / "etat.json").write_text("{ ceci n'est pas du json", encoding="utf-8")
        without_a_screen = type("SansEcran", (), {"config": self._config(tmp_path)})()
        Window._publish_the_failure(without_a_screen, "peu-importe", RuntimeError("boum"))
