"""Les tickets proposés à partir d'un compte rendu."""

from greffier.application.tickets import Ticket, depuis_reponse, extract_json, offer


class RedacteurFactice:
    def __init__(self, response):
        self.response = response
        self.recu = None

    def write_up(self, text):
        self.recu = text
        return self.response


RESPONSE = """[
  {"titre": "Décaler la recette à jeudi",
   "description": "Deux anomalies bloquantes restent à valider.",
   "assigne": "Josiane", "echeance": "jeudi",
   "extrait": "on décale la recette à jeudi"},
  {"titre": "Prévenir les utilisateurs", "description": "",
   "assigne": "", "echeance": "mercredi soir",
   "extrait": "on prévient les utilisateurs mercredi soir"}
]"""


class TestExtraction:
    def test_un_tableau_nu_est_lu(self):
        assert len(extract_json(RESPONSE)) == 2

    def test_un_tableau_entoure_de_balises_est_lu(self):
        """Un modèle qui répond « Voici : ```json … ``` » reste utilisable."""
        assert len(extract_json(f"```json\n{RESPONSE}\n```")) == 2

    def test_un_tableau_noye_dans_du_texte_est_retrouve(self):
        assert len(extract_json(f"Voici les tickets :\n{RESPONSE}\nVoilà.")) == 2

    def test_une_reponse_incomprehensible_ne_casse_rien(self):
        assert extract_json("je n'ai pas compris la demande") == []

    def test_un_objet_seul_n_est_pas_un_tableau(self):
        assert extract_json('{"titre": "x"}') == []


class TestConstruction:
    def test_les_champs_sont_repris(self):
        proposition = depuis_reponse(RESPONSE)
        premier = proposition.tickets[0]
        assert premier.title == "Décaler la recette à jeudi"
        assert premier.assigne == "Josiane"
        assert premier.echeance == "jeudi"

    def test_un_ticket_sans_titre_est_ecarte(self):
        assert depuis_reponse('[{"description": "sans titre"}]').tickets == []

    def test_les_champs_absents_restent_vides(self):
        """N'inventer ni assignation ni échéance : l'absence se voit."""
        ticket = depuis_reponse('[{"titre": "Faire le point"}]').tickets[0]
        assert ticket.assigne == "" and ticket.echeance == ""


class TestRendu:
    def test_le_markdown_porte_l_extrait_qui_justifie(self):
        rendered = depuis_reponse(RESPONSE).as_markdown("2026-08-25_copil")
        assert "> on décale la recette à jeudi" in rendered
        assert "**Pour** Josiane" in rendered

    def test_le_document_dit_qu_il_ne_cree_rien(self):
        """Un ticket ouvert à tort coûte plus cher à retirer qu'à ne pas créer."""
        assert "pas créés" in depuis_reponse(RESPONSE).as_markdown("x")

    def test_sans_decision_on_le_dit(self):
        assert "Aucune action décidée" in depuis_reponse("[]").as_markdown("x")


class TestBoucle:
    def test_le_compte_rendu_est_transmis_au_redacteur(self):
        writer = RedacteurFactice(RESPONSE)
        proposition = offer("# Compte rendu\n\nOn décale la recette.", writer)
        assert "On décale la recette." in writer.recu
        assert "un ticket par action réellement décidée" in writer.recu
        assert len(proposition.tickets) == 2

    def test_un_ticket_se_rend_seul_en_markdown(self):
        rendered = Ticket(title="Relancer", description="Parce que.").as_markdown()
        assert rendered.startswith("### Relancer")
