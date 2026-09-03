"""Les tickets proposés à partir d'un compte rendu."""

from greffier.application.tickets import Ticket, depuis_reponse, extraire_json, proposer


class RedacteurFactice:
    def __init__(self, reponse):
        self.reponse = reponse
        self.recu = None

    def rediger(self, texte):
        self.recu = texte
        return self.reponse


REPONSE = """[
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
        assert len(extraire_json(REPONSE)) == 2

    def test_un_tableau_entoure_de_balises_est_lu(self):
        """Un modèle qui répond « Voici : ```json … ``` » reste utilisable."""
        assert len(extraire_json(f"```json\n{REPONSE}\n```")) == 2

    def test_un_tableau_noye_dans_du_texte_est_retrouve(self):
        assert len(extraire_json(f"Voici les tickets :\n{REPONSE}\nVoilà.")) == 2

    def test_une_reponse_incomprehensible_ne_casse_rien(self):
        assert extraire_json("je n'ai pas compris la demande") == []

    def test_un_objet_seul_n_est_pas_un_tableau(self):
        assert extraire_json('{"titre": "x"}') == []


class TestConstruction:
    def test_les_champs_sont_repris(self):
        proposition = depuis_reponse(REPONSE)
        premier = proposition.tickets[0]
        assert premier.titre == "Décaler la recette à jeudi"
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
        rendu = depuis_reponse(REPONSE).en_markdown("2026-08-25_copil")
        assert "> on décale la recette à jeudi" in rendu
        assert "**Pour** Josiane" in rendu

    def test_le_document_dit_qu_il_ne_cree_rien(self):
        """Un ticket ouvert à tort coûte plus cher à retirer qu'à ne pas créer."""
        assert "pas créés" in depuis_reponse(REPONSE).en_markdown("x")

    def test_sans_decision_on_le_dit(self):
        assert "Aucune action décidée" in depuis_reponse("[]").en_markdown("x")


class TestBoucle:
    def test_le_compte_rendu_est_transmis_au_redacteur(self):
        redacteur = RedacteurFactice(REPONSE)
        proposition = proposer("# Compte rendu\n\nOn décale la recette.", redacteur)
        assert "On décale la recette." in redacteur.recu
        assert "un ticket par action réellement décidée" in redacteur.recu
        assert len(proposition.tickets) == 2

    def test_un_ticket_se_rend_seul_en_markdown(self):
        rendu = Ticket(titre="Relancer", description="Parce que.").en_markdown()
        assert rendu.startswith("### Relancer")
