"""Ce sur quoi l'outil a le droit de demander — et surtout ce sur quoi il se taît.

Une file de questions qui pose une question par phrase ne se lit pas : elle se
ferme. Les faux positifs mesurés sur le vocabulaire réel du poste sont donc
verrouillés ici, au même titre que les vrais.
"""

import pytest

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


class TestUnPlurielNEstPasUneDeformation:
    """Trois questions sur quatre étaient de cette nature, et absurdes.

    Relevé sur une réunion réelle : « J'ai entendu "bailleurs". Fallait-il
    comprendre "bailleur" ? », « J'ai entendu "pre-prod". Fallait-il comprendre
    "pré-prod" ? ». Un écart de un, donc sous le seuil, donc posé — et sans
    objet, puisque la réponse est déjà connue et qu'elle ne corrige rien. Le
    coût n'est pas la question : c'est qu'on cesse de lire les autres.
    """

    @pytest.mark.parametrize("entendu,connu", [
        ("bailleurs", "bailleur"),
        ("serveurs", "serveur"),
        ("recettes", "recette"),
        ("pre-prod", "pré-prod"),
        ("PRE-PROD", "pré-prod"),
        ("Backlog", "backlog"),
        ("sprints", "sprint"),
    ])
    def test_aucune_question_sur_une_variante(self, entendu, connu):
        from greffier.domaine.questions import Interrogateur

        assert Interrogateur(connus=[connu]).examiner(f"on parle du {entendu}") == []

    @pytest.mark.parametrize("entendu,connu", [
        ("Ouasis", "Oasis"),
        ("bakclog", "backlog"),
        ("Coppernic", "Copernic"),
    ])
    def test_une_vraie_deformation_est_toujours_relevee(self, entendu, connu):
        """La correction ne doit pas emporter ce pour quoi l'outil existe."""
        from greffier.domaine.questions import Interrogateur

        posees = Interrogateur(connus=[connu]).examiner(f"on parle de {entendu}")
        assert len(posees) == 1 and posees[0].attendu == connu

    def test_le_terme_exact_ne_declenche_rien(self):
        from greffier.domaine.questions import Interrogateur

        assert Interrogateur(connus=["Oasis"]).examiner("on parle d'Oasis") == []


class TestFormeCanonique:
    """Elle ne sert qu'à se taire, jamais à identifier."""

    def test_elle_retire_ce_qui_ne_change_pas_le_mot(self):
        from greffier.domaine.questions import forme_canonique

        assert forme_canonique("Pré-Prods") == forme_canonique("pre prod")

    def test_elle_ne_confond_pas_deux_termes_distincts(self):
        from greffier.domaine.questions import forme_canonique

        assert forme_canonique("Oasis") != forme_canonique("Ouasis")


class TestCeQuiRevientNEstPasUnAccident:
    """Une déformation ne se répète pas à l'identique.

    Le modèle rend « s'enature » une fois, pas trois. Un mot français revient,
    et c'est ce qui sépare « marge », qui est un mot, de « merve », qui n'en est
    pas un — sans avoir besoin d'un dictionnaire que le domaine n'a pas.
    """

    def test_un_mot_entendu_deux_fois_ne_se_demande_plus(self):
        from greffier.domaine.questions import Interrogateur

        interrogateur = Interrogateur(connus=["merge"])
        interrogateur.examiner("il reste de la marge sur ce sprint")
        interrogateur.examiner("on garde cette marge pour la dette")
        interrogateur.examiner("la marge sert à absorber les retours")
        # La première occurrence a pu poser sa question ; les suivantes, non.
        assert len(interrogateur.posees) <= 1

    def test_un_terme_deja_bien_transcrit_fait_taire_ses_voisins(self):
        """Si le modèle sait écrire « merge », il n'a pas déformé ici."""
        from greffier.domaine.questions import Interrogateur

        interrogateur = Interrogateur(connus=["merge"])
        interrogateur.examiner("j'ai fait le merge ce matin")
        assert interrogateur.examiner("il reste de la marge") == []

    def test_une_deformation_isolee_est_toujours_relevee(self):
        from greffier.domaine.questions import Interrogateur

        posees = Interrogateur(connus=["signature"]).examiner(
            "la s'enature n'est pas passée")
        assert len(posees) == 1 and posees[0].attendu == "signature"


class TestMotDerive:
    """Un terme précédé d'un préfixe est un autre mot, pas une faute."""

    @pytest.mark.parametrize("entendu,connu", [
        ("rétablissements", "établissement"),
        ("reprod", "prod"),
        ("déploiement", "ploiement"),
    ])
    def test_un_derive_ne_declenche_rien(self, entendu, connu):
        from greffier.domaine.questions import mot_derive

        assert mot_derive(entendu, connu)

    def test_l_elision_compte(self):
        """« ré- » devant une voyelle donne « rétablissement ».

        Sans elle, le cas qui a motivé la règle passait au travers.
        """
        from greffier.domaine.questions import mot_derive

        assert mot_derive("rétablissement", "établissement")

    @pytest.mark.parametrize("entendu,connu", [
        ("Ouasis", "Oasis"),
        ("merde", "merge"),
        ("bakclog", "backlog"),
    ])
    def test_une_deformation_n_est_pas_un_derive(self, entendu, connu):
        from greffier.domaine.questions import mot_derive

        assert not mot_derive(entendu, connu)

    def test_un_faux_positif_ne_coute_qu_un_silence(self):
        """« recette » passe pour « re » + « cette », et c'est assumé.

        La règle ne sert qu'à se taire : ne pas poser une question coûte moins
        qu'en poser une absurde, et « cette » n'a rien à faire dans un
        vocabulaire métier.
        """
        from greffier.domaine.questions import mot_derive

        assert mot_derive("recette", "cette")
