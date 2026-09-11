"""La conversation gardée : elle doit survivre à une fermeture de la fenêtre."""

from greffier.adapters.conversations_file import (
    TURNS_REREAD,
    add,
    file_for,
    read,
)


class TestWhatIsKept:
    def test_a_turn_reads_back(self, tmp_path):
        file = file_for(tmp_path, "2026-09-09_10h05_reunion")
        add(file, "moi", "Qu'a-t-on décidé sur le déploiement ?")
        turns = read(file)
        assert [(t.who, t.text) for t in turns] == [
            ("moi", "Qu'a-t-on décidé sur le déploiement ?")
        ]

    def test_the_order_is_the_conversation_s(self, tmp_path):
        file = file_for(tmp_path, "essai")
        for who, text in (("moi", "première"), ("greffier", "réponse"), ("moi", "seconde")):
            add(file, who, text)
        assert [t.text for t in read(file)] == ["première", "réponse", "seconde"]

    def test_l_horodatage_est_conserve(self, tmp_path):
        file = file_for(tmp_path, "essai")
        add(file, "moi", "question")
        assert read(file)[0].when is not None

    def test_a_missing_conversation_is_not_an_error(self, tmp_path):
        assert read(file_for(tmp_path, "jamais")) == []

    def test_an_empty_text_does_not_clutter(self, tmp_path):
        file = file_for(tmp_path, "essai")
        add(file, "note", "   ")
        assert read(file) == []

    def test_only_the_last_turns_are_read_back(self, tmp_path):
        """Au-delà, on ne relit plus une conversation, on la parcourt."""
        file = file_for(tmp_path, "essai")
        for number in range(TURNS_REREAD + 20):
            add(file, "moi", f"tour {number}")
        turns = read(file)
        assert len(turns) == TURNS_REREAD
        assert turns[-1].text == f"tour {TURNS_REREAD + 19}", "les plus récents"

    def test_an_unreadable_line_does_not_lose_the_rest(self, tmp_path):
        file = file_for(tmp_path, "essai")
        add(file, "moi", "avant")
        with file.open("a", encoding="utf-8") as stream:
            stream.write("ceci n'est pas du JSON\n")
        add(file, "moi", "après")
        assert [t.text for t in read(file)] == ["avant", "après"]


class TestOneConversationPerMeeting:
    def test_two_meetings_do_not_mix(self, tmp_path):
        add(file_for(tmp_path, "reunion-a"), "moi", "sur A")
        add(file_for(tmp_path, "reunion-b"), "moi", "sur B")
        assert [t.text for t in read(file_for(tmp_path, "reunion-a"))] == ["sur A"]
        assert [t.text for t in read(file_for(tmp_path, "reunion-b"))] == ["sur B"]


class TestWritingThatBreaksNothing:
    def test_a_folder_that_cannot_be_made_does_not_raise(self, tmp_path):
        """Converser vaut mieux que planter parce qu'on ne peut pas archiver."""
        obstacle = tmp_path / "occupe"
        obstacle.write_text("je ne suis pas un dossier", encoding="utf-8")
        add(obstacle / "essai.jsonl", "moi", "question")
