"""La conversation gardée : elle doit survivre à une fermeture de la fenêtre."""

from greffier.adapters.conversations_file import (
    TURNS_REREAD,
    add,
    file_for,
    read,
)


class TestCeQuiEstGarde:
    def test_un_tour_se_relit(self, tmp_path):
        file = file_for(tmp_path, "2026-09-09_10h05_reunion")
        add(file, "moi", "Qu'a-t-on décidé sur le déploiement ?")
        turns = read(file)
        assert [(t.who, t.text) for t in turns] == [
            ("moi", "Qu'a-t-on décidé sur le déploiement ?")
        ]

    def test_l_ordre_est_celui_de_la_conversation(self, tmp_path):
        file = file_for(tmp_path, "essai")
        for who, text in (("moi", "première"), ("greffier", "réponse"), ("moi", "seconde")):
            add(file, who, text)
        assert [t.text for t in read(file)] == ["première", "réponse", "seconde"]

    def test_l_horodatage_est_conserve(self, tmp_path):
        file = file_for(tmp_path, "essai")
        add(file, "moi", "question")
        assert read(file)[0].when is not None

    def test_une_conversation_absente_n_est_pas_une_erreur(self, tmp_path):
        assert read(file_for(tmp_path, "jamais")) == []

    def test_un_texte_vide_n_encombre_pas(self, tmp_path):
        file = file_for(tmp_path, "essai")
        add(file, "note", "   ")
        assert read(file) == []

    def test_seuls_les_derniers_tours_sont_relus(self, tmp_path):
        """Au-delà, on ne relit plus une conversation, on la parcourt."""
        file = file_for(tmp_path, "essai")
        for number in range(TURNS_REREAD + 20):
            add(file, "moi", f"tour {number}")
        turns = read(file)
        assert len(turns) == TURNS_REREAD
        assert turns[-1].text == f"tour {TURNS_REREAD + 19}", "les plus récents"

    def test_une_ligne_illisible_ne_perd_pas_le_reste(self, tmp_path):
        file = file_for(tmp_path, "essai")
        add(file, "moi", "avant")
        with file.open("a", encoding="utf-8") as stream:
            stream.write("ceci n'est pas du JSON\n")
        add(file, "moi", "après")
        assert [t.text for t in read(file)] == ["avant", "après"]


class TestChaqueReunionSaConversation:
    def test_deux_reunions_ne_se_melangent_pas(self, tmp_path):
        add(file_for(tmp_path, "reunion-a"), "moi", "sur A")
        add(file_for(tmp_path, "reunion-b"), "moi", "sur B")
        assert [t.text for t in read(file_for(tmp_path, "reunion-a"))] == ["sur A"]
        assert [t.text for t in read(file_for(tmp_path, "reunion-b"))] == ["sur B"]


class TestEcritureQuiNeCasseRien:
    def test_un_dossier_impossible_ne_leve_pas(self, tmp_path):
        """Converser vaut mieux que planter parce qu'on ne peut pas archiver."""
        obstacle = tmp_path / "occupe"
        obstacle.write_text("je ne suis pas un dossier", encoding="utf-8")
        add(obstacle / "essai.jsonl", "moi", "question")
