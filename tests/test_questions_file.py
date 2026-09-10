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
    def test_une_question_deposee_se_relit(self, tmp_path):
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

    def test_repondre_ne_perd_pas_la_question(self, tmp_path):
        """La trace de ce qui a été demandé est ce dont le contexte apprend."""
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        answer(file, 1, "backlog")
        assert "bakclog" in file.read_text(encoding="utf-8")

    def test_une_file_absente_n_est_pas_une_erreur(self, tmp_path):
        assert read(questions_file(tmp_path, "jamais")) == ([], {})

    def test_une_ligne_tronquee_ne_perd_pas_le_reste(self, tmp_path):
        """La file est écrite par un autre processus, qui peut être interrompu."""
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        with file.open("a", encoding="utf-8") as flux:
            flux.write('{"genre": "question", "nume')
        awaiting, _ = read(file)
        assert len(awaiting) == 1

    def test_l_ordre_des_questions_est_celui_des_numeros(self, tmp_path):
        file = questions_file(tmp_path, "essai")
        publish(file, question(number=2, heard="mrege", expected="merge"))
        publish(file, question(number=1))
        awaiting, _ = read(file)
        assert [en_attente.number for en_attente in awaiting] == [1, 2]


class TestMemoireApresRedemarrage:
    """Le processus qui écoute peut être relancé en cours de réunion."""

    def test_les_questions_deja_posees_sont_retrouvees(self, tmp_path):
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        assert question().key in keys_already_placed(file)

    def test_une_question_repondue_ne_revient_pas(self, tmp_path):
        file = questions_file(tmp_path, "essai")
        publish(file, question())
        answer(file, 1, "backlog")
        assert question().key in keys_already_placed(file), "y revenir serait pire"

    def test_sans_fichier_rien_n_a_ete_pose(self, tmp_path):
        assert keys_already_placed(questions_file(tmp_path, "jamais")) == set()
