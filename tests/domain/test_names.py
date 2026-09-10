"""Les règles d'attribution des noms, sans audio ni modèle."""

from greffier.domain.models import Span, SpeakerTurn, Utterance
from greffier.domain.names import (
    MentionKind,
    attribute,
    join_namesakes,
    spot_mentions,
)
from greffier.domain.profiles.french import FRENCH


def utterance(start: float, end: float, text: str) -> Utterance:
    return Utterance(span=Span(start, end), text=text)

def _mentions(utterances, excluded=None):
    """Le profil français, explicite, comme la chaîne le résout à l'exécution.

    Ces trente tests gardent les règles de reconnaissance des prénoms depuis les
    premières vraies réunions. Le profil les rend paramétrables ; aucune de leurs
    assertions ne change, et c'est ce qui prouve que le déplacement n'a rien
    coûté.
    """
    return spot_mentions(utterances, FRENCH, excluded)


def turn(start: float, end: float, voice: str) -> SpeakerTurn:
    return SpeakerTurn(span=Span(start, end), voice=voice)


class TestReperage:
    def test_auto_presentation(self):
        mentions = _mentions([utterance(0, 4, "Bonjour, moi c'est Tanguy, de la DSI.")])
        assert [(m.name, m.type) for m in mentions] == [
            ("Tanguy", MentionKind.AUTO_PRESENTATION)
        ]

    def test_interpellation(self):
        mentions = _mentions([utterance(0, 3, "Josiane, tu peux nous faire le point ?")])
        assert mentions[0].name == "Josiane"
        assert mentions[0].type is MentionKind.INTERPELLATION

    def test_passage_de_parole(self):
        mentions = _mentions([utterance(0, 3, "Je passe la parole à Sophie.")])
        assert (mentions[0].name, mentions[0].type) == ("Sophie", MentionKind.INTERPELLATION)

    def test_renvoi(self):
        mentions = _mentions([utterance(0, 2, "Merci Marc pour la démonstration.")])
        assert (mentions[0].name, mentions[0].type) == ("Marc", MentionKind.RENVOI)

    def test_les_outils_courants_ne_sont_pas_des_prenoms(self):
        """Sans cette exclusion, « merci Jira » créerait un participant."""
        texts = ["Merci Jira.", "Je suis Teams.", "Merci Outlook."]
        assert _mentions([utterance(0, 2, t) for t in texts]) == []

    def test_exclusions_supplementaires_de_la_configuration(self):
        mentions = _mentions(
            [utterance(0, 2, "Merci Oasis pour le retour.")],
            excluded=frozenset({"oasis"}),
        )
        assert mentions == []

    def test_une_position_ne_produit_qu_une_mention(self):
        """« C'est Marc » et « Marc, tu » se recouvrent : le motif fort gagne."""
        mentions = _mentions([utterance(0, 3, "Marc, tu peux répondre ?")])
        assert len(mentions) == 1
        assert mentions[0].type is MentionKind.INTERPELLATION


class TestAttribution:
    def test_auto_presentation_designe_celui_qui_parle(self):
        utterances = [utterance(1, 4, "Bonjour, moi c'est Tanguy.")]
        turns = [turn(0, 5, "v1"), turn(5, 10, "v2")]
        outcome = attribute(_mentions(utterances), turns)
        # Un seul indice de poids 3 : assez pour être certain.
        assert outcome.certitudes["v1"].name == "Tanguy"

    def test_interpellation_designe_le_locuteur_suivant(self):
        utterances = [utterance(2, 4, "Josiane, tu peux nous dire où on en est ?")]
        turns = [turn(0, 5, "v1"), turn(6, 20, "v2")]
        outcome = attribute(_mentions(utterances), turns)
        assert "v1" not in outcome.certitudes
        assert outcome.propositions[0].voice == "v2"
        assert outcome.propositions[0].name == "Josiane"

    def test_renvoi_designe_le_locuteur_precedent(self):
        utterances = [utterance(21, 23, "Merci Marc, c'est clair.")]
        turns = [turn(0, 20, "v2"), turn(20, 30, "v1")]
        outcome = attribute(_mentions(utterances), turns)
        assert outcome.propositions[0].voice == "v2"
        assert outcome.propositions[0].name == "Marc"

    def test_les_indices_s_accumulent_jusqu_a_la_certitude(self):
        """Trois renvois faibles valent une auto-présentation."""
        utterances = [
            utterance(21, 22, "Merci Marc."),
            utterance(41, 42, "Comme disait Marc, c'est urgent."),
            utterance(61, 62, "Marc a raison."),
        ]
        turns = [turn(0, 20, "v2"), turn(20, 23, "v1"),
                 turn(23, 40, "v2"), turn(40, 43, "v1"),
                 turn(43, 60, "v2"), turn(60, 63, "v1")]
        outcome = attribute(_mentions(utterances), turns)
        assert outcome.certitudes["v2"].name == "Marc"
        assert outcome.certitudes["v2"].score == 3

    def test_un_indice_hors_fenetre_ne_compte_pas(self):
        """Un « merci Marc » deux minutes après ne désigne plus personne."""
        utterances = [utterance(200, 202, "Merci Marc.")]
        turns = [turn(0, 20, "v2"), turn(199, 210, "v1")]
        outcome = attribute(_mentions(utterances), turns)
        assert outcome.certitudes == {}
        assert outcome.propositions == []

    def test_un_nom_ne_peut_designer_deux_voix(self):
        """Deux voix revendiquant « Marc » : la mieux étayée le garde."""
        utterances = [
            utterance(1, 3, "Moi c'est Marc."),        # v1, poids 3
            utterance(11, 12, "Merci Marc."),          # renvoie vers v1 aussi
            utterance(31, 32, "Merci Marc."),          # renvoie vers v3
        ]
        turns = [turn(0, 5, "v1"), turn(5, 10, "v2"), turn(10, 15, "v2"),
                 turn(20, 30, "v3"), turn(30, 35, "v2")]
        outcome = attribute(_mentions(utterances), turns)
        assert outcome.certitudes["v1"].name == "Marc"
        assert all(a.voice != "v1" for a in outcome.propositions)

    def test_un_rival_credible_empeche_la_certitude(self):
        utterances = [
            utterance(1, 3, "Moi c'est Marc."),
            utterance(1, 3, "Moi c'est Pascal."),
        ]
        turns = [turn(0, 10, "v1")]
        outcome = attribute(_mentions(utterances), turns)
        assert outcome.certitudes == {}
        assert {p.name for p in outcome.propositions} == {"Marc"}


class TestFauxPositifs:
    """Cas relevés sur de vraies transcriptions."""

    def test_tu_vois_est_un_tic_de_langage(self):
        """« un macro Kanban, tu vois » ne fait pas de Kanban un participant."""
        assert _mentions([utterance(0, 3, "plus un macro Kanban, tu vois,")]) == []

    def test_vous_savez_non_plus(self):
        assert _mentions([utterance(0, 3, "le déploiement Copernic, vous savez bien")]) == []

    def test_mais_une_vraie_adresse_reste_detectee(self):
        mentions = _mentions([utterance(0, 3, "Sophie, tu peux nous dire ?")])
        assert mentions and mentions[0].name == "Sophie"


class TestFormulationsReelles:
    """Phrases relevées telles quelles dans la réunion du 2026-08-20."""

    def test_toi_prenom(self):
        m = _mentions([utterance(0, 3, "Mais pour ça, toi, Josiane, c'est pas besoin ?")])
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.INTERPELLATION)]

    def test_prenom_en_tete_suivi_d_une_adresse(self):
        m = _mentions([utterance(0, 3, "Josiane, on a lu ensemble et tu nous diras")])
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.INTERPELLATION)]

    def test_un_mot_seul_ne_suffit_pas_a_creer_un_prenom(self):
        """« Ouais. », « Exact. », « Complètement. » remplissent les transcriptions."""
        texts = ["Ouais.", "Exact.", "Complètement.", "Josiane."]
        assert _mentions([utterance(i, i + 1, t) for i, t in enumerate(texts)]) == []

    def test_un_mot_seul_compte_si_le_prenom_est_connu_par_ailleurs(self):
        """« Josiane. » lancé seul est un appel — une fois qu'on sait que Josiane existe."""
        m = _mentions([
            utterance(0, 3, "Mais pour ça, toi, Josiane, c'est pas besoin ?"),
            utterance(10, 11, "Ouais."),
            utterance(20, 21, "Josiane."),
        ])
        assert [x.name for x in m] == ["Josiane", "Josiane"]

    def test_ce_que_presentait_untel(self):
        m = _mentions([utterance(0, 3, "pour ce que présentait Josiane.")])
        assert [(x.name, x.type) for x in m] == [("Josiane", MentionKind.RENVOI)]

    def test_une_ouverture_de_phrase_n_est_pas_un_prenom(self):
        """« Bref, tu vois… », « Après, on verra… » : rien à retenir."""
        texts = ["Bref, tu vois ce que je veux dire.", "Après, on verra bien.",
                  "Donc, vous avez compris.", "Mais, tu sais bien."]
        assert _mentions([utterance(0, 2, t) for t in texts]) == []


class TestInterjections:
    """Relevé sur la réunion du 2026-08-20 : « Tiens, tu as vu ? »."""

    def test_tiens_n_est_pas_un_prenom(self):
        assert _mentions([utterance(0, 3, "Tiens, tu as vu le ticket ?")]) == []

    def test_les_adverbes_en_ment_sont_ecartes(self):
        """Aucun prénom français ne finit en « -ment », les adverbes si."""
        texts = ["Effectivement, tu as raison.", "Normalement, vous livrez jeudi.",
                  "Franchement, on n'y arrivera pas."]
        assert _mentions([utterance(i, i + 2, t) for i, t in enumerate(texts)]) == []

    def test_mais_clement_reste_un_prenom(self):
        """La règle ne doit pas mordre sur les prénoms courts en « -ment »."""
        mentions = _mentions([utterance(0, 3, "Clément, tu peux nous dire ?")])
        assert [m.name for m in mentions] == ["Clément"]


class TestInterpellationSansReponse:
    """Le 25 août 2026 : trois interpellations, jamais une réponse.

    La personne visée n'a pas décroché un mot de toute l'heure. Chaque
    interpellation s'est reportée sur le locuteur suivant, et son prénom a été
    attribué de façon ferme à la voix qui totalisait 64 % du temps de parole.
    """

    def test_trois_interpellations_ne_donnent_pas_la_certitude(self):
        utterances = [
            utterance(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            utterance(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
            utterance(70, 72, "Vas-y Tanguy, je veux bien que tu partages."),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"),
                 turn(39, 42, "v1"), turn(42, 69, "v2"),
                 turn(69, 72, "v1"), turn(72, 99, "v2")]
        outcome = attribute(_mentions(utterances), turns)
        # Six points accumulés, largement au-dessus du seuil, et pourtant rien
        # n'est affirmé : ces trois indices peuvent tous viser un absent.
        assert outcome.certitudes == {}

    def test_mais_le_nom_reste_propose(self):
        # Proposer garde l'information sans la présenter comme acquise : c'est
        # à l'utilisateur de trancher, en écoutant dix secondes.
        utterances = [
            utterance(10, 12, "Tanguy, tu peux nous sortir les horaires ?"),
            utterance(40, 42, "Tanguy, tu me confirmes le déploiement ?"),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"),
                 turn(39, 42, "v1"), turn(42, 69, "v2")]
        outcome = attribute(_mentions(utterances), turns)
        assert [p.name for p in outcome.propositions] == ["Tanguy"]

    def test_une_interpellation_confirmee_par_un_renvoi_suffit(self):
        # « Sandy, tu peux… » puis « Merci Sandy » : deux directions concordent,
        # dont une qui vise quelqu'un qui a effectivement parlé.
        utterances = [
            utterance(10, 12, "Sandy, tu peux nous dire où en sont les anomalies ?"),
            utterance(40, 42, "Merci Sandy."),
        ]
        turns = [turn(0, 12, "v1"), turn(12, 39, "v2"), turn(39, 42, "v1")]
        outcome = attribute(_mentions(utterances), turns)
        assert outcome.certitudes["v2"].name == "Sandy"

    def test_une_auto_presentation_seule_suffit_toujours(self):
        # L'intéressé se nomme lui-même : rien de spéculatif là-dedans.
        utterances = [utterance(0, 4, "Bonjour, moi c'est Jacques, je commence.")]
        turns = [turn(0, 20, "v1")]
        outcome = attribute(_mentions(utterances), turns)
        assert outcome.certitudes["v1"].name == "Jacques"


class TestReunirLesHomonymes:
    """Deux voix que l'on nomme pareil sont la même personne.

    Mesuré sur une réunion réelle de 1 h 42 : la chaîne concluait « Lise » sur
    neuf voix distinctes, dont huit d'un seul tour de parole. Le compte rendu
    annonçait donc huit participants de trop. La même règle existait pour le
    direct depuis le matin ; elle manquait à la chaîne d'après réunion.
    """

    def test_neuf_voix_d_un_meme_nom_n_en_font_qu_une(self) -> None:
        names = {f"v{i}": "Lise" for i in range(9)}
        poids = {f"v{i}": float(i) for i in range(9)}
        membership = join_namesakes(names, poids)
        assert len(set(membership.values())) == 1

    def test_la_voix_la_plus_fournie_l_emporte(self) -> None:
        """C'est celle dont l'extrait est le plus représentatif."""
        names = {"maigre": "Lise", "fournie": "Lise"}
        membership = join_namesakes(names, {"maigre": 3.0, "fournie": 240.0})
        assert set(membership.values()) == {"fournie"}

    def test_deux_noms_differents_ne_se_touchent_pas(self) -> None:
        names = {"v1": "Lise", "v2": "Pascal"}
        membership = join_namesakes(names, {"v1": 10.0, "v2": 20.0})
        assert membership == {"v1": "v1", "v2": "v2"}

    def test_la_casse_et_les_accents_ne_font_pas_deux_personnes(self) -> None:
        names = {"v1": "Hélène", "v2": "helene", "v3": "HÉLÈNE"}
        membership = join_namesakes(names, {"v1": 5.0, "v2": 9.0, "v3": 1.0})
        assert set(membership.values()) == {"v2"}

    def test_une_voix_sans_poids_connu_ne_casse_rien(self) -> None:
        names = {"v1": "Lise", "v2": "Lise"}
        membership = join_namesakes(names, {})
        assert len(set(membership.values())) == 1

    def test_un_nom_vide_est_ignore(self) -> None:
        names = {"v1": "  ", "v2": "  ", "v3": "Pascal"}
        membership = join_namesakes(names, {"v1": 1.0, "v2": 2.0, "v3": 3.0})
        assert membership["v1"] == "v1"
        assert membership["v2"] == "v2"

    def test_chaque_voix_figure_dans_l_appartenance(self) -> None:
        """L'appelant applique le résultat sans avoir à combler les trous."""
        names = {"v1": "Lise", "v2": "Lise", "v3": "Pascal"}
        membership = join_namesakes(names, {"v1": 1.0, "v2": 2.0, "v3": 3.0})
        assert set(membership) == {"v1", "v2", "v3"}
