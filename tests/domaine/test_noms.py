"""Les règles d'attribution des noms, sans audio ni modèle."""

from greffier.domaine.modeles import Intervalle, Replique, TourDeParole
from greffier.domaine.noms import (
    TypeMention,
    attribuer,
    reperer_mentions,
)


def replique(debut: float, fin: float, texte: str) -> Replique:
    return Replique(intervalle=Intervalle(debut, fin), texte=texte)


def tour(debut: float, fin: float, voix: str) -> TourDeParole:
    return TourDeParole(intervalle=Intervalle(debut, fin), voix=voix)


class TestReperage:
    def test_auto_presentation(self):
        mentions = reperer_mentions([replique(0, 4, "Bonjour, moi c'est Tanguy, de la DSI.")])
        assert [(m.nom, m.type) for m in mentions] == [
            ("Tanguy", TypeMention.AUTO_PRESENTATION)
        ]

    def test_interpellation(self):
        mentions = reperer_mentions([replique(0, 3, "Josiane, tu peux nous faire le point ?")])
        assert mentions[0].nom == "Josiane"
        assert mentions[0].type is TypeMention.INTERPELLATION

    def test_passage_de_parole(self):
        mentions = reperer_mentions([replique(0, 3, "Je passe la parole à Sophie.")])
        assert (mentions[0].nom, mentions[0].type) == ("Sophie", TypeMention.INTERPELLATION)

    def test_renvoi(self):
        mentions = reperer_mentions([replique(0, 2, "Merci Marc pour la démonstration.")])
        assert (mentions[0].nom, mentions[0].type) == ("Marc", TypeMention.RENVOI)

    def test_les_outils_courants_ne_sont_pas_des_prenoms(self):
        """Sans cette exclusion, « merci Jira » créerait un participant."""
        textes = ["Merci Jira.", "Je suis Teams.", "Merci Outlook."]
        assert reperer_mentions([replique(0, 2, t) for t in textes]) == []

    def test_exclusions_supplementaires_de_la_configuration(self):
        mentions = reperer_mentions(
            [replique(0, 2, "Merci Oasis pour le retour.")],
            exclus=frozenset({"oasis"}),
        )
        assert mentions == []

    def test_une_position_ne_produit_qu_une_mention(self):
        """« C'est Marc » et « Marc, tu » se recouvrent : le motif fort gagne."""
        mentions = reperer_mentions([replique(0, 3, "Marc, tu peux répondre ?")])
        assert len(mentions) == 1
        assert mentions[0].type is TypeMention.INTERPELLATION


class TestAttribution:
    def test_auto_presentation_designe_celui_qui_parle(self):
        repliques = [replique(1, 4, "Bonjour, moi c'est Tanguy.")]
        tours = [tour(0, 5, "v1"), tour(5, 10, "v2")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        # Un seul indice de poids 3 : assez pour être certain.
        assert resultat.certitudes["v1"].nom == "Tanguy"

    def test_interpellation_designe_le_locuteur_suivant(self):
        repliques = [replique(2, 4, "Josiane, tu peux nous dire où on en est ?")]
        tours = [tour(0, 5, "v1"), tour(6, 20, "v2")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert "v1" not in resultat.certitudes
        assert resultat.propositions[0].voix == "v2"
        assert resultat.propositions[0].nom == "Josiane"

    def test_renvoi_designe_le_locuteur_precedent(self):
        repliques = [replique(21, 23, "Merci Marc, c'est clair.")]
        tours = [tour(0, 20, "v2"), tour(20, 30, "v1")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert resultat.propositions[0].voix == "v2"
        assert resultat.propositions[0].nom == "Marc"

    def test_les_indices_s_accumulent_jusqu_a_la_certitude(self):
        """Trois renvois faibles valent une auto-présentation."""
        repliques = [
            replique(21, 22, "Merci Marc."),
            replique(41, 42, "Comme disait Marc, c'est urgent."),
            replique(61, 62, "Marc a raison."),
        ]
        tours = [tour(0, 20, "v2"), tour(20, 23, "v1"),
                 tour(23, 40, "v2"), tour(40, 43, "v1"),
                 tour(43, 60, "v2"), tour(60, 63, "v1")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert resultat.certitudes["v2"].nom == "Marc"
        assert resultat.certitudes["v2"].score == 3

    def test_un_indice_hors_fenetre_ne_compte_pas(self):
        """Un « merci Marc » deux minutes après ne désigne plus personne."""
        repliques = [replique(200, 202, "Merci Marc.")]
        tours = [tour(0, 20, "v2"), tour(199, 210, "v1")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert resultat.certitudes == {}
        assert resultat.propositions == []

    def test_un_nom_ne_peut_designer_deux_voix(self):
        """Deux voix revendiquant « Marc » : la mieux étayée le garde."""
        repliques = [
            replique(1, 3, "Moi c'est Marc."),        # v1, poids 3
            replique(11, 12, "Merci Marc."),          # renvoie vers v1 aussi
            replique(31, 32, "Merci Marc."),          # renvoie vers v3
        ]
        tours = [tour(0, 5, "v1"), tour(5, 10, "v2"), tour(10, 15, "v2"),
                 tour(20, 30, "v3"), tour(30, 35, "v2")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert resultat.certitudes["v1"].nom == "Marc"
        assert all(a.voix != "v1" for a in resultat.propositions)

    def test_un_rival_credible_empeche_la_certitude(self):
        repliques = [
            replique(1, 3, "Moi c'est Marc."),
            replique(1, 3, "Moi c'est Paul."),
        ]
        tours = [tour(0, 10, "v1")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert resultat.certitudes == {}
        assert {p.nom for p in resultat.propositions} == {"Marc"}


class TestFauxPositifs:
    """Cas relevés sur de vraies transcriptions."""

    def test_tu_vois_est_un_tic_de_langage(self):
        """« un macro Kanban, tu vois » ne fait pas de Kanban un participant."""
        assert reperer_mentions([replique(0, 3, "plus un macro Kanban, tu vois,")]) == []

    def test_vous_savez_non_plus(self):
        assert reperer_mentions([replique(0, 3, "le déploiement Copernic, vous savez bien")]) == []

    def test_mais_une_vraie_adresse_reste_detectee(self):
        mentions = reperer_mentions([replique(0, 3, "Sophie, tu peux nous dire ?")])
        assert mentions and mentions[0].nom == "Sophie"


class TestFormulationsReelles:
    """Phrases relevées telles quelles dans la réunion du 2026-08-20."""

    def test_toi_prenom(self):
        m = reperer_mentions([replique(0, 3, "Mais pour ça, toi, Josiane, c'est pas besoin ?")])
        assert [(x.nom, x.type) for x in m] == [("Josiane", TypeMention.INTERPELLATION)]

    def test_prenom_en_tete_suivi_d_une_adresse(self):
        m = reperer_mentions([replique(0, 3, "Josiane, on a lu ensemble et tu nous diras")])
        assert [(x.nom, x.type) for x in m] == [("Josiane", TypeMention.INTERPELLATION)]

    def test_un_mot_seul_ne_suffit_pas_a_creer_un_prenom(self):
        """« Ouais. », « Exact. », « Complètement. » remplissent les transcriptions."""
        textes = ["Ouais.", "Exact.", "Complètement.", "Josiane."]
        assert reperer_mentions([replique(i, i + 1, t) for i, t in enumerate(textes)]) == []

    def test_un_mot_seul_compte_si_le_prenom_est_connu_par_ailleurs(self):
        """« Josiane. » lancé seul est un appel — une fois qu'on sait que Josiane existe."""
        m = reperer_mentions([
            replique(0, 3, "Mais pour ça, toi, Josiane, c'est pas besoin ?"),
            replique(10, 11, "Ouais."),
            replique(20, 21, "Josiane."),
        ])
        assert [x.nom for x in m] == ["Josiane", "Josiane"]

    def test_ce_que_presentait_untel(self):
        m = reperer_mentions([replique(0, 3, "pour ce que présentait Josiane.")])
        assert [(x.nom, x.type) for x in m] == [("Josiane", TypeMention.RENVOI)]

    def test_une_ouverture_de_phrase_n_est_pas_un_prenom(self):
        """« Bref, tu vois… », « Après, on verra… » : rien à retenir."""
        textes = ["Bref, tu vois ce que je veux dire.", "Après, on verra bien.",
                  "Donc, vous avez compris.", "Mais, tu sais bien."]
        assert reperer_mentions([replique(0, 2, t) for t in textes]) == []


class TestInterjections:
    """Relevé sur la réunion du 2026-08-20 : « Tiens, tu as vu ? »."""

    def test_tiens_n_est_pas_un_prenom(self):
        assert reperer_mentions([replique(0, 3, "Tiens, tu as vu le ticket ?")]) == []

    def test_les_adverbes_en_ment_sont_ecartes(self):
        """Aucun prénom français ne finit en « -ment », les adverbes si."""
        textes = ["Effectivement, tu as raison.", "Normalement, vous livrez jeudi.",
                  "Franchement, on n'y arrivera pas."]
        assert reperer_mentions([replique(i, i + 2, t) for i, t in enumerate(textes)]) == []

    def test_mais_clement_reste_un_prenom(self):
        """La règle ne doit pas mordre sur les prénoms courts en « -ment »."""
        mentions = reperer_mentions([replique(0, 3, "Clément, tu peux nous dire ?")])
        assert [m.nom for m in mentions] == ["Clément"]


class TestInterpellationSansReponse:
    """Le 25 août 2026 : trois interpellations, jamais une réponse.

    La personne visée n'a pas décroché un mot de toute l'heure. Chaque
    interpellation s'est reportée sur le locuteur suivant, et son prénom a été
    attribué de façon ferme à la voix qui totalisait 64 % du temps de parole.
    """

    def test_trois_interpellations_ne_donnent_pas_la_certitude(self):
        repliques = [
            replique(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            replique(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
            replique(70, 72, "Vas-y Tanguy, je veux bien que tu partages."),
        ]
        tours = [tour(0, 12, "v1"), tour(12, 39, "v2"),
                 tour(39, 42, "v1"), tour(42, 69, "v2"),
                 tour(69, 72, "v1"), tour(72, 99, "v2")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        # Six points accumulés, largement au-dessus du seuil, et pourtant rien
        # n'est affirmé : ces trois indices peuvent tous viser un absent.
        assert resultat.certitudes == {}

    def test_mais_le_nom_reste_propose(self):
        # Proposer garde l'information sans la présenter comme acquise : c'est
        # à l'utilisateur de trancher, en écoutant dix secondes.
        repliques = [
            replique(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            replique(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
        ]
        tours = [tour(0, 12, "v1"), tour(12, 39, "v2"),
                 tour(39, 42, "v1"), tour(42, 69, "v2")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert [p.nom for p in resultat.propositions] == ["Tanguy"]

    def test_une_interpellation_confirmee_par_un_renvoi_suffit(self):
        # « Sandy, tu peux… » puis « Merci Sandy » : deux directions concordent,
        # dont une qui vise quelqu'un qui a effectivement parlé.
        repliques = [
            replique(10, 12, "Sandy, tu peux nous dire où en sont les anomalies ?"),
            replique(40, 42, "Merci Sandy."),
        ]
        tours = [tour(0, 12, "v1"), tour(12, 39, "v2"), tour(39, 42, "v1")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert resultat.certitudes["v2"].nom == "Sandy"

    def test_une_auto_presentation_seule_suffit_toujours(self):
        # L'intéressé se nomme lui-même : rien de spéculatif là-dedans.
        repliques = [replique(0, 4, "Bonjour, moi c'est Jacques, je commence.")]
        tours = [tour(0, 20, "v1")]
        resultat = attribuer(reperer_mentions(repliques), tours)
        assert resultat.certitudes["v1"].nom == "Jacques"
