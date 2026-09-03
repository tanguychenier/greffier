"""Le compte rendu, mis en forme pour le courriel.

Ces tests portent sur ce qui a réellement cassé en usage : les accents rendus en
MacRoman, les tableaux réduits à des barres verticales, et l'objet du message
réduit à un nom de fichier horodaté.
"""

from __future__ import annotations

from greffier.adaptateurs.gabarit_courriel import courriel, en_html, sujet


class TestTitres:
    def test_les_trois_niveaux_deviennent_des_balises(self) -> None:
        html = en_html("# Compte rendu\n\n## Décisions\n\n### Bug photos")
        assert "<h1" in html and "Compte rendu" in html
        assert "<h2" in html and "Décisions" in html
        assert "<h3" in html and "Bug photos" in html

    def test_un_titre_plus_profond_est_ramene_au_troisieme_niveau(self) -> None:
        assert "<h3" in en_html("##### Trop profond")

    def test_chaque_titre_porte_son_style_en_ligne(self) -> None:
        # Les clients de messagerie suppriment volontiers une feuille de style.
        assert 'style="' in en_html("## Décisions")


class TestTableaux:
    ACTIONS = (
        "| Qui | Quoi | Quand |\n"
        "|---|---|---|\n"
        "| Camilo | Tests iPhone | après la réunion |\n"
        "| Sophie | Demander le rôle valideur | — |\n"
    )

    def test_un_tableau_markdown_devient_un_vrai_tableau(self) -> None:
        html = en_html(self.ACTIONS)
        assert "<table" in html and "</table>" in html
        assert html.count("</th>") == 3
        assert html.count("<tr>") == 3  # une d'en-tête, deux de corps

    def test_les_cellules_gardent_leur_contenu(self) -> None:
        html = en_html(self.ACTIONS)
        for attendu in ("Camilo", "Tests iPhone", "après la réunion", "Sophie", "—"):
            assert attendu in html

    def test_aucune_barre_verticale_ne_subsiste(self) -> None:
        # Le symptôme constaté : un mail plein de « | ».
        assert "|" not in en_html(self.ACTIONS)

    def test_un_tableau_sans_ligne_de_separateurs_reste_du_texte(self) -> None:
        html = en_html("| pas | un | tableau |")
        assert "<table" not in html


class TestListes:
    def test_les_puces_deviennent_une_liste(self) -> None:
        html = en_html("- Première décision\n- Seconde décision")
        assert "<ul" in html and html.count("<li") == 2

    def test_une_liste_numerotee_est_ordonnee(self) -> None:
        assert "<ol" in en_html("1. Premier point\n2. Second point")

    def test_une_puce_qui_court_sur_deux_lignes_reste_un_seul_item(self) -> None:
        html = en_html("- Étape de visa conservée avant la\n  signature Hervé")
        assert html.count("<li") == 1
        assert "signature Hervé" in html


class TestTexteEnLigne:
    def test_le_gras_et_l_italique(self) -> None:
        html = en_html("Une décision **ferme** et une piste *possible*.")
        assert "<strong>ferme</strong>" in html
        assert "<em>possible</em>" in html

    def test_le_code_en_ligne(self) -> None:
        assert "<code" in en_html("Le champ `destinataire` est vide.")

    def test_un_lien_devient_cliquable(self) -> None:
        html = en_html("Voir [le ticket](https://exemple.fr/t/12).")
        assert 'href="https://exemple.fr/t/12"' in html
        assert ">le ticket</a>" in html

    def test_une_citation(self) -> None:
        html = en_html("> Ça ne garde pas les photos")
        assert "<blockquote" in html and "Ça ne garde pas les photos" in html


class TestAccents:
    def test_les_accents_traversent_la_conversion(self) -> None:
        # Le défaut d'origine : « réunion » arrivait en « r√©union ».
        html = en_html("## Réunion du 25 août — décisions prises")
        for attendu in ("Réunion", "août", "—", "décisions"):
            assert attendu in html

    def test_le_document_declare_son_encodage(self) -> None:
        assert 'charset="utf-8"' in courriel("# Titre")


class TestSurete:
    def test_le_html_du_compte_rendu_est_echappe(self) -> None:
        # Une transcription peut contenir n'importe quoi ; rien n'est exécuté.
        html = en_html("Il a dit <script>alert(1)</script> en réunion.")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_une_esperluette_reste_lisible(self) -> None:
        assert "&amp;" in en_html("Dupont & Fils")


class TestSujet:
    def test_le_titre_du_compte_rendu_devient_l_objet(self) -> None:
        obtenu = sujet("# Compte rendu — Point Casa\n\nLe 25 août.", "défaut")
        assert obtenu == "Compte rendu — Point Casa"

    def test_sans_titre_on_garde_le_defaut(self) -> None:
        assert sujet("Pas de titre ici.", "défaut") == "défaut"

    def test_un_document_vide_garde_le_defaut(self) -> None:
        assert sujet("", "défaut") == "défaut"

    def test_les_etoiles_du_titre_sont_retirees(self) -> None:
        assert sujet("# Compte rendu **Casa**", "défaut") == "Compte rendu Casa"


class TestDocumentComplet:
    def test_le_document_est_autonome(self) -> None:
        html = courriel("# Titre\n\n## Décisions\n\n- Une décision")
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")

    def test_le_pied_de_page_avertit_le_lecteur(self) -> None:
        html = courriel("# Titre", "Rédigé automatiquement, à relire.")
        assert "Rédigé automatiquement, à relire." in html

    def test_sans_pied_aucune_signature_n_est_ajoutee(self) -> None:
        assert "border-top" not in courriel("# Titre")

    def test_un_compte_rendu_complet_passe_entier(self) -> None:
        source = (
            "# Compte rendu — Point Casa\n\n"
            "25 août 2026 · 1 h · Sophie, Kerann, Camilo\n\n"
            "## Décisions\n\n- Étape de visa conservée\n\n"
            "## Actions\n\n| Qui | Quoi | Quand |\n|---|---|---|\n"
            "| Camilo | Tests iPhone | — |\n\n"
            "## Points ouverts\n\n- Bug photos non reproduit\n"
        )
        html = courriel(source)
        assert html.count("<h2") == 3
        assert "<table" in html
        assert html.count("<ul") == 2


class TestSommaire:
    """Un sommaire, pour savoir ce que le document contient sans le dérouler."""

    COMPLET = (
        "# Compte rendu — Point Casa\n\n"
        "25 août 2026, environ 1 heure. Participants : Sophie, Kerann.\n\n"
        "## Décisions\n\n- Une décision\n\n"
        "## Actions\n\n| Qui | Quoi | Quand |\n|---|---|---|\n| Sophie | Tester | non dit |\n\n"
        "## Points ouverts\n\n- Un point\n\n"
        "## Détail par sujet\n\n### Un sujet\n\nDu texte.\n"
    )

    def test_le_sommaire_liste_les_sections_dans_l_ordre(self) -> None:
        html = courriel(self.COMPLET)
        assert "Sommaire" in html
        position = [html.index(t) for t in ("Décisions", "Actions", "Points ouverts")]
        assert position == sorted(position)

    def test_les_sections_sont_numerotees(self) -> None:
        html = courriel(self.COMPLET)
        for numero in ("1.", "2.", "3.", "4."):
            assert numero in html

    def test_chaque_entree_mene_a_son_ancre(self) -> None:
        html = courriel(self.COMPLET)
        assert 'href="#s-decisions"' in html
        assert 'id="s-decisions"' in html

    def test_un_document_a_deux_sections_n_a_pas_besoin_de_sommaire(self) -> None:
        court = "# Titre\n\nContexte.\n\n## Décisions\n\n- Une\n\n## Actions\n\n- Deux\n"
        assert "Sommaire" not in courriel(court)

    def test_les_sections_sont_exposees_pour_la_ligne_de_commande(self) -> None:
        from greffier.adaptateurs.gabarit_courriel import sections

        assert sections(self.COMPLET) == [
            "Décisions", "Actions", "Points ouverts", "Détail par sujet",
        ]


class TestEnteteDuCourriel:
    """Titre et ligne de contexte forment l'en-tête, pas un paragraphe de plus."""

    SOURCE = (
        "# Compte rendu — Point Casa\n\n"
        "25 août 2026, environ 1 heure. Participants : Sophie, Kerann.\n\n"
        "## Décisions\n\n- Une décision\n\n## Actions\n\n- Une action\n\n"
        "## Points ouverts\n\n- Un point\n"
    )

    def test_le_titre_apparait_une_seule_fois(self) -> None:
        assert courriel(self.SOURCE).count("<h1") == 1

    def test_la_ligne_de_contexte_est_mise_en_retrait(self) -> None:
        html = courriel(self.SOURCE)
        assert "Participants : Sophie, Kerann." in html
        # Rendue en gris pâle, sous le titre, et non comme un paragraphe normal.
        assert html.index("Participants") < html.index("Sommaire")

    def test_un_document_sans_titre_passe_quand_meme(self) -> None:
        html = courriel("## Décisions\n\n- Une\n\n## Actions\n\n- Deux\n\n## Points\n\n- Trois")
        assert "<h2" in html and "<h1" not in html

    def test_aucun_contenu_n_est_perdu_par_le_decoupage(self) -> None:
        html = courriel(self.SOURCE)
        for attendu in ("Point Casa", "25 août 2026", "Une décision", "Une action", "Un point"):
            assert attendu in html
