"""Les tickets proposés à partir d'un compte rendu."""

from greffier.application.tickets import Ticket, depuis_reponse, extract_json, offer


class FakeWriter:
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


class TestWhatIsAskedOfTheWriter:
    def test_a_bare_array_is_read(self):
        assert len(extract_json(RESPONSE)) == 2

    def test_an_array_wrapped_in_a_fence_is_read(self):
        """Un modèle qui répond « Voici : ```json … ``` » reste utilisable."""
        assert len(extract_json(f"```json\n{RESPONSE}\n```")) == 2

    def test_an_array_buried_in_text_is_found(self):
        assert len(extract_json(f"Voici les tickets :\n{RESPONSE}\nVoilà.")) == 2

    def test_an_answer_it_cannot_make_out_breaks_nothing(self):
        assert extract_json("je n'ai pas compris la demande") == []

    def test_a_lone_object_is_not_an_array(self):
        assert extract_json('{"titre": "x"}') == []


class TestBuildingTheTickets:
    def test_the_fields_are_carried_over(self):
        proposition = depuis_reponse(RESPONSE)
        first_call = proposition.tickets[0]
        assert first_call.title == "Décaler la recette à jeudi"
        assert first_call.assigne == "Josiane"
        assert first_call.echeance == "jeudi"

    def test_a_ticket_with_no_title_is_dropped(self):
        assert depuis_reponse('[{"description": "sans titre"}]').tickets == []

    def test_the_missing_fields_stay_empty(self):
        """N'inventer ni assignation ni échéance : l'absence se voit."""
        ticket = depuis_reponse('[{"titre": "Faire le point"}]').tickets[0]
        assert ticket.assigne == "" and ticket.echeance == ""


class TestWhatIsWrittenOut:
    def test_the_markdown_carries_the_quote_that_justifies_it(self):
        rendered = depuis_reponse(RESPONSE).as_markdown("2026-08-25_copil")
        assert "> on décale la recette à jeudi" in rendered
        assert "**Pour** Josiane" in rendered

    def test_the_document_says_it_creates_nothing(self):
        """Un ticket ouvert à tort coûte plus cher à retirer qu'à ne pas créer."""
        assert "pas créés" in depuis_reponse(RESPONSE).as_markdown("x")

    def test_with_no_decision_it_says_so(self):
        assert "Aucune action décidée" in depuis_reponse("[]").as_markdown("x")


class TestTheWholeLoop:
    def test_the_minutes_are_passed_to_the_writer(self):
        writer = FakeWriter(RESPONSE)
        proposition = offer("# Compte rendu\n\nOn décale la recette.", writer)
        assert "On décale la recette." in writer.recu
        assert "un ticket par action réellement décidée" in writer.recu
        assert len(proposition.tickets) == 2

    def test_a_ticket_renders_itself_in_markdown(self):
        rendered = Ticket(title="Relancer", description="Parce que.").as_markdown()
        assert rendered.startswith("### Relancer")
