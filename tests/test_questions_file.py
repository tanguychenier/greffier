"""La file des questions : déposée par un processus, lue et répondue par l'autre."""

from greffier.adapters.questions_file import (
    answer,
    keys_already_placed,
    publish,
    questions_file,
    read,
)
from greffier.domain.questions import Question, Reason


def question(number: int = 1, heard: str = "bakclog", expected: str = "backlog") -> Question:
    return Question(
        number=number,
        text=f"J'ai entendu « {heard} ». Fallait-il comprendre « {expected} » ?",
        motif=Reason.NEAR_TERM,
        heard=heard,
        expected=expected,
    )


class TestFile:
    def test_a_question_dropped_in_reads_back(self, tmp_path):
        file = questions_file(tmp_path, "2026-09-09_10h05_reunion")
        publish(file, question())
        awaiting, answers = read(file)
        assert [en_attente.question.expected for en_attente in awaiting] == ["backlog"]
        assert answers == {}

    def test_une_question_repondue_quitte_l_attente(self, tmp_path):
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        answer(file, 1, "backlog")
        awaiting, answers = read(file)
        assert awaiting == []
        assert answers == {1: "backlog"}

    def test_answering_does_not_lose_the_question(self, tmp_path):
        """La trace de ce qui a été demandé est ce dont le contexte apprend."""
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        answer(file, 1, "backlog")
        assert "bakclog" in file.read_text(encoding="utf-8")

    def test_a_missing_queue_is_not_an_error(self, tmp_path):
        assert read(questions_file(tmp_path, "jamais")) == ([], {})

    def test_a_truncated_line_does_not_lose_the_rest(self, tmp_path):
        """La file est écrite par un autre processus, qui peut être interrompu."""
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        with file.open("a", encoding="utf-8") as stream:
            stream.write('{"genre": "question", "nume')
        awaiting, _ = read(file)
        assert len(awaiting) == 1

    def test_the_order_of_the_questions_is_the_numbers(self, tmp_path):
        file = questions_file(tmp_path, "essai")
        publish(file, question(number=2, heard="mrege", expected="merge"))
        publish(file, question(number=1))
        awaiting, _ = read(file)
        assert [en_attente.number for en_attente in awaiting] == [1, 2]


class TestMemoireApresRedemarrage:
    """Le processus qui écoute peut être relancé en cours de réunion."""

    def test_the_questions_already_asked_are_found(self, tmp_path):
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        assert question().key in keys_already_placed(file)

    def test_a_question_answered_does_not_come_back(self, tmp_path):
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        answer(file, 1, "backlog")
        assert question().key in keys_already_placed(file), "y revenir serait pire"

    def test_with_no_file_nothing_has_been_asked(self, tmp_path):
        assert keys_already_placed(questions_file(tmp_path, "jamais")) == set()
