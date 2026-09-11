"""Le compte rendu, mis en forme pour le courriel.

Ces tests portent sur ce qui a réellement cassé en usage : les accents rendus en
MacRoman, les tableaux réduits à des barres verticales, et l'objet du message
réduit à un nom de fichier horodaté.
"""

from __future__ import annotations

from greffier.adapters.email_template import _ancre, as_html, email
from greffier.domain.minutes import title as subject


class TestHeadings:
    def test_the_three_levels_become_tags(self) -> None:
        html = as_html("# Compte rendu\n\n## Décisions\n\n### Bug photos")
        assert "<h1" in html and "Compte rendu" in html
        assert "<h2" in html and "Décisions" in html
        assert "<h3" in html and "Bug photos" in html

    def test_a_deeper_heading_comes_back_to_the_third_level(self) -> None:
        assert "<h3" in as_html("##### Trop profond")

    def test_every_heading_carries_its_style_inline(self) -> None:
        # Les clients de messagerie suppriment volontiers une feuille de style.
        assert 'style="' in as_html("## Décisions")


class TestTables:
    ACTIONS = (
        "| Qui | Quoi | Quand |\n"
        "|---|---|---|\n"
        "| Cédric | Tests iPhone | après la réunion |\n"
        "| Sophie | Demander le rôle valideur | — |\n"
    )

    def test_a_markdown_table_becomes_a_real_one(self) -> None:
        html = as_html(self.ACTIONS)
        assert "<table" in html and "</table>" in html
        assert html.count("</th>") == 3
        assert html.count("<tr>") == 3  # une d'en-tête, deux de corps

    def test_the_cells_keep_their_content(self) -> None:
        html = as_html(self.ACTIONS)
        for expected in ("Cédric", "Tests iPhone", "après la réunion", "Sophie", "—"):
            assert expected in html

    def test_no_pipe_character_is_left(self) -> None:
        # Le symptôme constaté : un mail plein de « | ».
        assert "|" not in as_html(self.ACTIONS)

    def test_a_table_with_no_separator_row_stays_text(self) -> None:
        html = as_html("| pas | un | tableau |")
        assert "<table" not in html


class TestLists:
    def test_the_bullets_become_a_list(self) -> None:
        html = as_html("- Première décision\n- Seconde décision")
        assert "<ul" in html and html.count("<li") == 2

    def test_a_numbered_list_is_ordered(self) -> None:
        assert "<ol" in as_html("1. Premier point\n2. Second point")

    def test_a_bullet_running_over_two_lines_stays_one_item(self) -> None:
        html = as_html("- Étape de visa conservée avant la\n  signature Hervé")
        assert html.count("<li") == 1
        assert "signature Hervé" in html


class TestInlineText:
    def test_bold_and_italic(self) -> None:
        html = as_html("Une décision **ferme** et une piste *possible*.")
        assert "<strong>ferme</strong>" in html
        assert "<em>possible</em>" in html

    def test_inline_code(self) -> None:
        assert "<code" in as_html("Le champ `destinataire` est vide.")

    def test_a_link_becomes_clickable(self) -> None:
        html = as_html("Voir [le ticket](https://exemple.fr/t/12).")
        assert 'href="https://exemple.fr/t/12"' in html
        assert ">le ticket</a>" in html

    def test_a_quotation(self) -> None:
        html = as_html("> Ça ne garde pas les photos")
        assert "<blockquote" in html and "Ça ne garde pas les photos" in html


class TestAccentedCharacters:
    def test_the_accents_survive_the_conversion(self) -> None:
        # Le défaut d'origine : « réunion » arrivait en « r√©union ».
        html = as_html("## Réunion du 25 août — décisions prises")
        for expected in ("Réunion", "août", "—", "décisions"):
            assert expected in html

    def test_the_document_declares_its_encoding(self) -> None:
        assert 'charset="utf-8"' in email("# Titre")


class TestWhatMustNotBeExecuted:
    def test_html_inside_the_minutes_is_escaped(self) -> None:
        # Une transcription peut contenir n'importe quoi ; rien n'est exécuté.
        html = as_html("Il a dit <script>alert(1)</script> en réunion.")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_an_ampersand_stays_readable(self) -> None:
        assert "&amp;" in as_html("Dupont & Fils")


class TestTheSubjectLine:
    def test_the_title_of_the_minutes_becomes_the_subject(self) -> None:
        obtenu = subject("# Compte rendu — Point Casa\n\nLe 25 août.", "défaut")
        assert obtenu == "Compte rendu — Point Casa"

    def test_with_no_title_the_default_is_kept(self) -> None:
        assert subject("Pas de titre ici.", "défaut") == "défaut"

    def test_an_empty_document_keeps_the_default(self) -> None:
        assert subject("", "défaut") == "défaut"

    def test_the_asterisks_of_the_title_are_removed(self) -> None:
        assert subject("# Compte rendu **Casa**", "défaut") == "Compte rendu Casa"


class TestTheWholeDocument:
    def test_the_document_stands_on_its_own(self) -> None:
        html = email("# Titre\n\n## Décisions\n\n- Une décision")
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")

    def test_the_footer_warns_the_reader(self) -> None:
        html = email("# Titre", "Rédigé automatiquement, à relire.")
        assert "Rédigé automatiquement, à relire." in html

    def test_with_no_footer_no_signature_is_added(self) -> None:
        assert "border-top" not in email("# Titre")

    def test_a_complete_set_of_minutes_passes_whole(self) -> None:
        source = (
            "# Compte rendu — Point Casa\n\n"
            "25 août 2026 · 1 h · Sophie, Katell, Cédric\n\n"
            "## Décisions\n\n- Étape de visa conservée\n\n"
            "## Actions\n\n| Qui | Quoi | Quand |\n|---|---|---|\n"
            "| Cédric | Tests iPhone | — |\n\n"
            "## Points ouverts\n\n- Bug photos non reproduit\n"
        )
        html = email(source)
        assert html.count("<h2") == 3
        assert "<table" in html
        assert html.count("<ul") == 2


class TestTheTableOfContents:
    """Un sommaire, pour savoir ce que le document contient sans le dérouler."""

    COMPLET = (
        "# Compte rendu — Point Casa\n\n"
        "25 août 2026, environ 1 heure. Participants : Sophie, Katell.\n\n"
        "## Décisions\n\n- Une décision\n\n"
        "## Actions\n\n| Qui | Quoi | Quand |\n|---|---|---|\n| Sophie | Tester | non dit |\n\n"
        "## Points ouverts\n\n- Un point\n\n"
        "## Détail par sujet\n\n### Un sujet\n\nDu texte.\n"
    )

    def test_it_lists_the_sections_in_order(self) -> None:
        html = email(self.COMPLET)
        assert "Sommaire" in html
        position = [html.index(t) for t in ("Décisions", "Actions", "Points ouverts")]
        assert position == sorted(position)

    def test_the_sections_are_numbered(self) -> None:
        html = email(self.COMPLET)
        for number in ("1.", "2.", "3.", "4."):
            assert number in html

    def test_every_entry_leads_to_its_anchor(self) -> None:
        html = email(self.COMPLET)
        assert 'href="#s-decisions"' in html
        assert 'id="s-decisions"' in html

    def test_a_document_of_two_sections_needs_no_contents(self) -> None:
        court = "# Titre\n\nContexte.\n\n## Décisions\n\n- Une\n\n## Actions\n\n- Deux\n"
        assert "Sommaire" not in email(court)

    def test_the_sections_are_exposed_for_the_command_line(self) -> None:
        from greffier.adapters.email_template import sections

        assert sections(self.COMPLET) == [
            "Décisions", "Actions", "Points ouverts", "Détail par sujet",
        ]


class TestTheHeaderOfTheEmail:
    """Titre et ligne de contexte forment l'en-tête, pas un paragraphe de plus."""

    SOURCE = (
        "# Compte rendu — Point Casa\n\n"
        "25 août 2026, environ 1 heure. Participants : Sophie, Katell.\n\n"
        "## Décisions\n\n- Une décision\n\n## Actions\n\n- Une action\n\n"
        "## Points ouverts\n\n- Un point\n"
    )

    def test_the_title_appears_once(self) -> None:
        assert email(self.SOURCE).count("<h1") == 1

    def test_the_context_line_is_set_apart(self) -> None:
        html = email(self.SOURCE)
        assert "Participants : Sophie, Katell." in html
        # Rendue en gris pâle, sous le titre, et non comme un paragraphe normal.
        assert html.index("Participants") < html.index("Sommaire")

    def test_a_document_with_no_title_still_passes(self) -> None:
        html = email("## Décisions\n\n- Une\n\n## Actions\n\n- Deux\n\n## Points\n\n- Trois")
        assert "<h2" in html and "<h1" not in html

    def test_no_content_is_lost_by_the_splitting(self) -> None:
        html = email(self.SOURCE)
        for expected in ("Point Casa", "25 août 2026", "Une décision", "Une action", "Un point"):
            assert expected in html


class TestNonLatinAnchors:
    """Deux sections doivent avoir deux ancres.

    Un titre sans lettre ASCII se réduisait au seul préfixe : toutes les
    sections portaient « s- », le document HTML avait des identifiants en
    double, et chaque lien du sommaire menait à la première section.
    """

    def test_two_non_latin_headings_give_two_anchors(self):
        assert _ancre("決定事項") != _ancre("Действия")

    def test_an_anchor_stays_a_valid_identifier(self):
        ancre = _ancre("決定事項")
        assert ancre.startswith("s-") and len(ancre) > 2

    def test_the_latin_headings_do_not_move(self):
        assert _ancre("Décisions") == "s-decisions"

    def test_the_contents_and_the_heading_point_at_one_anchor(self):
        """La fonction est appelée des deux côtés : elles doivent coïncider."""
        assert _ancre("決定事項") == _ancre("決定事項")
