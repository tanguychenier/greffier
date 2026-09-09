"""La carte d'un sujet : on ajoute, on ne détruit pas."""

from greffier.domaine.carte import (
    Apport,
    Carte,
    Etat,
    Genre,
    Noeud,
    clef,
    fusionner,
    marquer_depasse,
)


class TestReconnaissanceDeFormulation:
    def test_les_accents_et_la_casse_ne_comptent_pas(self):
        assert clef("L'accès au SI") == clef("acces au si")

    def test_l_ordre_des_mots_ne_compte_pas(self):
        """« recette externalisée » et « externalisée, la recette » : un point."""
        assert clef("recette externalisée") == clef("externalisée recette")

    def test_deux_points_distincts_restent_distincts(self):
        assert clef("monter la recette") != clef("monter la production")

    def test_un_libelle_fait_de_mots_vides_garde_son_identite(self):
        """« A » et « D » sont deux mots vides français.

        Avec une clef vide, deux branches distinctes n'en faisaient plus qu'une
        et la seconde écrasait la première. Fusionner à tort perd de
        l'information, ce qui est pire que d'en dupliquer.
        """
        assert clef("A") != clef("D")
        assert clef("A") != ""

    def test_les_mots_vides_sont_bien_retires_quand_il_reste_du_sens(self):
        assert clef("le déploiement") == clef("déploiement")


class TestFusion:
    def test_un_point_nouveau_s_ajoute(self):
        carte = Carte("Oasis")
        bilan = fusionner(carte, [Apport("Le PDF ne se régénère pas")])
        assert bilan.ajoutes == ("Le PDF ne se régénère pas",)
        assert carte.compte == 2

    def test_un_point_deja_present_ne_se_duplique_pas(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Le PDF ne se régénère pas")])
        bilan = fusionner(carte, [Apport("le pdf ne se regenere pas")])
        assert bilan.ajoutes == ()
        assert carte.compte == 2, "la reformulation ne crée pas une seconde branche"

    def test_une_piste_s_accroche_sous_son_probleme(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Le PDF ne se régénère pas", genre=Genre.PROBLEME)])
        fusionner(carte, [Apport("Forcer la régénération", genre=Genre.PISTE,
                                 sous="Le PDF ne se régénère pas")])
        assert carte.racine is not None
        probleme = carte.racine.enfant("Le PDF ne se régénère pas")
        assert probleme is not None
        assert [enfant.texte for enfant in probleme.enfants] == ["Forcer la régénération"]

    def test_un_parent_introuvable_ne_perd_pas_l_apport(self):
        """Mal placé, il reste corrigeable ; perdu, il faut réécouter la réunion."""
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Une piste", sous="un parent qui n'existe pas")])
        assert carte.racine is not None
        assert carte.racine.enfant("Une piste") is not None

    def test_la_reunion_d_origine_est_notee(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Un point")], reunion="2026-09-09_10h05_reunion")
        assert carte.racine is not None
        noeud = carte.racine.enfant("Un point")
        assert noeud is not None
        assert noeud.reunions == ["2026-09-09_10h05_reunion"]

    def test_deux_reunions_sur_le_meme_point_sont_toutes_deux_notees(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Un point")], reunion="premiere")
        fusionner(carte, [Apport("Un point")], reunion="seconde")
        assert carte.racine is not None
        noeud = carte.racine.enfant("Un point")
        assert noeud is not None
        assert noeud.reunions == ["premiere", "seconde"]

    def test_un_apport_vide_est_ignore(self):
        carte = Carte("Oasis")
        assert fusionner(carte, [Apport("   ")]).vide


class TestEtats:
    """Ce qui est en discussion ne doit pas passer pour une décision."""

    def test_le_defaut_est_en_discussion(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Une idée lancée à l'oral")])
        assert carte.racine is not None
        noeud = carte.racine.enfant("Une idée lancée à l'oral")
        assert noeud is not None
        assert noeud.etat is Etat.EN_DISCUSSION

    def test_une_decision_releve_l_etat(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Monter la recette en interne", genre=Genre.PISTE)])
        bilan = fusionner(carte, [Apport("Monter la recette en interne",
                                         genre=Genre.PISTE, etat=Etat.ACTE)])
        assert bilan.actes == ("Monter la recette en interne",)
        assert carte.racine is not None
        noeud = carte.racine.enfant("Monter la recette en interne")
        assert noeud is not None
        assert noeud.etat is Etat.ACTE

    def test_un_probleme_ne_peut_pas_etre_acte(self):
        """« Acté » se lirait « le groupe a décidé ce problème ».

        Mesuré sur une extraction réelle : sept problèmes sur douze revenaient
        marqués « acté », le rédacteur ayant lu « acté » comme « établi ».
        """
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Le PDF ne se régénère pas",
                                 genre=Genre.PROBLEME, etat=Etat.ACTE)])
        assert carte.racine is not None
        noeud = carte.racine.enfant("Le PDF ne se régénère pas")
        assert noeud is not None
        assert noeud.etat is Etat.EN_DISCUSSION

    def test_une_piste_et_une_action_peuvent_etre_actees(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Monter la recette", genre=Genre.PISTE, etat=Etat.ACTE),
                          Apport("Chiffrer le coût", genre=Genre.ACTION, etat=Etat.ACTE)])
        assert carte.racine is not None
        for texte in ("Monter la recette", "Chiffrer le coût"):
            noeud = carte.racine.enfant(texte)
            assert noeud is not None and noeud.etat is Etat.ACTE

    def test_un_probleme_peut_etre_depasse(self):
        """Un problème peut avoir cessé d'en être un."""
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Un souci", genre=Genre.PROBLEME)])
        assert marquer_depasse(carte, "Un souci") is True

    def test_une_decision_ne_redevient_pas_une_discussion(self):
        """« Acté » qui redeviendrait « en discussion » ferait douter de tout."""
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Monter la recette", genre=Genre.PISTE, etat=Etat.ACTE)])
        fusionner(carte, [Apport("Monter la recette", genre=Genre.PISTE,
                                 etat=Etat.EN_DISCUSSION)])
        assert carte.racine is not None
        noeud = carte.racine.enfant("Monter la recette")
        assert noeud is not None
        assert noeud.etat is Etat.ACTE


class TestRienNeDisparait:
    """Une carte partagée porte le travail de plusieurs personnes."""

    def test_marquer_depasse_garde_le_noeud(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("Une piste écartée")])
        assert marquer_depasse(carte, "Une piste écartée") is True
        assert carte.compte == 2, "le nœud reste"
        assert carte.racine is not None
        noeud = carte.racine.enfant("Une piste écartée")
        assert noeud is not None
        assert noeud.etat is Etat.DEPASSE

    def test_la_racine_ne_se_marque_pas(self):
        assert marquer_depasse(Carte("Oasis"), "Oasis") is False

    def test_marquer_ce_qui_n_existe_pas_le_dit(self):
        assert marquer_depasse(Carte("Oasis"), "jamais évoqué") is False

    def test_une_fusion_ne_retire_aucun_noeud_existant(self):
        carte = Carte("Oasis")
        fusionner(carte, [Apport("A"), Apport("B"), Apport("C")])
        avant = carte.compte
        fusionner(carte, [Apport("D")])
        assert carte.compte == avant + 1, "rien n'a été remplacé"


class TestComptage:
    def test_un_noeud_seul_compte_pour_un(self):
        assert Noeud("seul").compte() == 1

    def test_les_enfants_comptent(self):
        racine = Noeud("racine", enfants=[Noeud("a"), Noeud("b", enfants=[Noeud("c")])])
        assert racine.compte() == 4
