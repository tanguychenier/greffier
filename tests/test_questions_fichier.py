"""La file des questions : déposée par un processus, lue et répondue par l'autre."""

from greffier.adaptateurs.questions_fichier import (
    clefs_deja_posees,
    deposer,
    fichier_des_questions,
    lire,
    repondre,
)
from greffier.domaine.questions import Motif, Question


def question(numero: int = 1, entendu: str = "bakclog", attendu: str = "backlog") -> Question:
    return Question(
        numero=numero,
        texte=f"J'ai entendu « {entendu} ». Fallait-il comprendre « {attendu} » ?",
        motif=Motif.TERME_PROCHE,
        entendu=entendu,
        attendu=attendu,
    )


class TestFile:
    def test_une_question_deposee_se_relit(self, tmp_path):
        fichier = fichier_des_questions(tmp_path, "2026-09-09_10h05_reunion")
        deposer(fichier, question())
        attente, reponses = lire(fichier)
        assert [en_attente.question.attendu for en_attente in attente] == ["backlog"]
        assert reponses == {}

    def test_une_question_repondue_quitte_l_attente(self, tmp_path):
        fichier = fichier_des_questions(tmp_path, "essai")
        deposer(fichier, question())
        repondre(fichier, 1, "backlog")
        attente, reponses = lire(fichier)
        assert attente == []
        assert reponses == {1: "backlog"}

    def test_repondre_ne_perd_pas_la_question(self, tmp_path):
        """La trace de ce qui a été demandé est ce dont le contexte apprend."""
        fichier = fichier_des_questions(tmp_path, "essai")
        deposer(fichier, question())
        repondre(fichier, 1, "backlog")
        assert "bakclog" in fichier.read_text(encoding="utf-8")

    def test_une_file_absente_n_est_pas_une_erreur(self, tmp_path):
        assert lire(fichier_des_questions(tmp_path, "jamais")) == ([], {})

    def test_une_ligne_tronquee_ne_perd_pas_le_reste(self, tmp_path):
        """La file est écrite par un autre processus, qui peut être interrompu."""
        fichier = fichier_des_questions(tmp_path, "essai")
        deposer(fichier, question())
        with fichier.open("a", encoding="utf-8") as flux:
            flux.write('{"genre": "question", "nume')
        attente, _ = lire(fichier)
        assert len(attente) == 1

    def test_l_ordre_des_questions_est_celui_des_numeros(self, tmp_path):
        fichier = fichier_des_questions(tmp_path, "essai")
        deposer(fichier, question(numero=2, entendu="mrege", attendu="merge"))
        deposer(fichier, question(numero=1))
        attente, _ = lire(fichier)
        assert [en_attente.numero for en_attente in attente] == [1, 2]


class TestMemoireApresRedemarrage:
    """Le processus qui écoute peut être relancé en cours de réunion."""

    def test_les_questions_deja_posees_sont_retrouvees(self, tmp_path):
        fichier = fichier_des_questions(tmp_path, "essai")
        deposer(fichier, question())
        assert question().clef in clefs_deja_posees(fichier)

    def test_une_question_repondue_ne_revient_pas(self, tmp_path):
        fichier = fichier_des_questions(tmp_path, "essai")
        deposer(fichier, question())
        repondre(fichier, 1, "backlog")
        assert question().clef in clefs_deja_posees(fichier), "y revenir serait pire"

    def test_sans_fichier_rien_n_a_ete_pose(self, tmp_path):
        assert clefs_deja_posees(fichier_des_questions(tmp_path, "jamais")) == set()
