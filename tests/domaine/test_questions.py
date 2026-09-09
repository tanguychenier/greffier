"""Ce sur quoi l'outil a le droit de demander — et surtout ce sur quoi il se taît.

Une file de questions qui pose une question par phrase ne se lit pas : elle se
ferme. Les faux positifs mesurés sur le vocabulaire réel du poste sont donc
verrouillés ici, au même titre que les vrais.
"""

from greffier.domaine.questions import (
    QUESTIONS_MAXIMUM,
    Interrogateur,
    Motif,
    distance,
    tolerance,
)


class TestDistance:
    def test_deux_mots_identiques_sont_a_zero(self):
        assert distance("backlog", "backlog") == 0

    def test_une_transposition_ne_compte_que_pour_un(self):
        """Une transcription inverse des lettres : c'est le même mot.

        Sans cela « bakclog »/« backlog » valait 2, au même rang que
        « point »/« sprint », et aucun seuil ne pouvait séparer les deux cas.
        """
        assert distance("bakclog", "backlog") == 1

    def test_une_lettre_de_plus_compte_pour_un(self):
        assert distance("ouasis", "oasis") == 1

    def test_deux_mots_etrangers_restent_loin(self):
        assert distance("point", "sprint") == 2


class TestTolerance:
    def test_un_terme_court_n_accepte_qu_un_ecart(self):
        assert tolerance("sprint") == 1

    def test_un_terme_long_en_accepte_deux(self):
        assert tolerance("infrastructure") == 2


class TestCeQuiDeclencheUneQuestion:
    def test_un_terme_deforme_est_releve(self):
        questions = Interrogateur(connus=("backlog",)).examiner("Le bakclog est plein.")
        assert len(questions) == 1
        assert questions[0].attendu == "backlog"
        assert questions[0].entendu == "bakclog"
        assert questions[0].motif is Motif.TERME_PROCHE

    def test_un_terme_compose_est_reconnu_mot_a_mot(self):
        """« mrege » ne rencontrait jamais « merge request » et passait inaperçu."""
        questions = Interrogateur(connus=("merge request",)).examiner("La mrege request.")
        assert questions and questions[0].attendu == "merge"

    def test_la_question_dit_ce_qu_elle_a_entendu(self):
        """Une question sans sa raison ressemble à un caprice : on n'y répond pas."""
        question = Interrogateur(connus=("Oasis",)).examiner("Point sur Ouasis.")[0]
        assert "Ouasis" in question.texte
        assert "Oasis" in question.texte


class TestCeQuiNeDoitRienDeclencher:
    def test_un_mot_courant_ne_devient_pas_un_terme(self):
        """Mesuré : « point » et « sprint » sont à 2 et n'ont aucun rapport."""
        assert Interrogateur(connus=("sprint",)).examiner("On reprend le point.") == []

    def test_le_terme_correctement_transcrit_ne_demande_rien(self):
        assert Interrogateur(connus=("backlog",)).examiner("Le backlog est trié.") == []

    def test_un_mot_simplement_inconnu_n_est_pas_un_signal(self):
        """Une réunion en contient des dizaines, tous légitimes."""
        assert Interrogateur(connus=("backlog",)).examiner("On parle de Kubernetes.") == []

    def test_les_mots_courts_sont_ecartes(self):
        """« CR » et « OR » sont à 1 et n'ont aucun rapport."""
        assert Interrogateur(connus=("prod",)).examiner("Le brod du truc.") == []

    def test_la_meme_question_ne_se_pose_pas_deux_fois(self):
        interrogateur = Interrogateur(connus=("backlog",))
        assert interrogateur.examiner("Le bakclog est plein.")
        assert interrogateur.examiner("Le bakclog encore.") == []

    def test_l_outil_finit_par_se_taire(self):
        """Au-delà d'un certain nombre, il noierait qui travaille."""
        connus = tuple(f"terme{n:03d}" for n in range(40))
        interrogateur = Interrogateur(connus=connus)
        phrase = " ".join(f"terme{n:03d}x" for n in range(40))
        assert len(interrogateur.examiner(phrase)) <= QUESTIONS_MAXIMUM
