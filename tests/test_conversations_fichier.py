"""La conversation gardée : elle doit survivre à une fermeture de la fenêtre."""

from greffier.adaptateurs.conversations_fichier import (
    TOURS_RELUS,
    ajouter,
    fichier_de,
    lire,
)


class TestCeQuiEstGarde:
    def test_un_tour_se_relit(self, tmp_path):
        fichier = fichier_de(tmp_path, "2026-09-09_10h05_reunion")
        ajouter(fichier, "moi", "Qu'a-t-on décidé sur le déploiement ?")
        tours = lire(fichier)
        assert [(t.qui, t.texte) for t in tours] == [
            ("moi", "Qu'a-t-on décidé sur le déploiement ?")
        ]

    def test_l_ordre_est_celui_de_la_conversation(self, tmp_path):
        fichier = fichier_de(tmp_path, "essai")
        for qui, texte in (("moi", "première"), ("greffier", "réponse"), ("moi", "seconde")):
            ajouter(fichier, qui, texte)
        assert [t.texte for t in lire(fichier)] == ["première", "réponse", "seconde"]

    def test_l_horodatage_est_conserve(self, tmp_path):
        fichier = fichier_de(tmp_path, "essai")
        ajouter(fichier, "moi", "question")
        assert lire(fichier)[0].quand is not None

    def test_une_conversation_absente_n_est_pas_une_erreur(self, tmp_path):
        assert lire(fichier_de(tmp_path, "jamais")) == []

    def test_un_texte_vide_n_encombre_pas(self, tmp_path):
        fichier = fichier_de(tmp_path, "essai")
        ajouter(fichier, "note", "   ")
        assert lire(fichier) == []

    def test_seuls_les_derniers_tours_sont_relus(self, tmp_path):
        """Au-delà, on ne relit plus une conversation, on la parcourt."""
        fichier = fichier_de(tmp_path, "essai")
        for numero in range(TOURS_RELUS + 20):
            ajouter(fichier, "moi", f"tour {numero}")
        tours = lire(fichier)
        assert len(tours) == TOURS_RELUS
        assert tours[-1].texte == f"tour {TOURS_RELUS + 19}", "les plus récents"

    def test_une_ligne_illisible_ne_perd_pas_le_reste(self, tmp_path):
        fichier = fichier_de(tmp_path, "essai")
        ajouter(fichier, "moi", "avant")
        with fichier.open("a", encoding="utf-8") as flux:
            flux.write("ceci n'est pas du JSON\n")
        ajouter(fichier, "moi", "après")
        assert [t.texte for t in lire(fichier)] == ["avant", "après"]


class TestChaqueReunionSaConversation:
    def test_deux_reunions_ne_se_melangent_pas(self, tmp_path):
        ajouter(fichier_de(tmp_path, "reunion-a"), "moi", "sur A")
        ajouter(fichier_de(tmp_path, "reunion-b"), "moi", "sur B")
        assert [t.texte for t in lire(fichier_de(tmp_path, "reunion-a"))] == ["sur A"]
        assert [t.texte for t in lire(fichier_de(tmp_path, "reunion-b"))] == ["sur B"]


class TestEcritureQuiNeCasseRien:
    def test_un_dossier_impossible_ne_leve_pas(self, tmp_path):
        """Converser vaut mieux que planter parce qu'on ne peut pas archiver."""
        obstacle = tmp_path / "occupe"
        obstacle.write_text("je ne suis pas un dossier", encoding="utf-8")
        ajouter(obstacle / "essai.jsonl", "moi", "question")
