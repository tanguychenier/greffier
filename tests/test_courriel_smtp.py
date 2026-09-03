"""Ce qu'un destinataire reçoit, vérifié sans rien ouvrir.

La composition du courriel ne dépend d'aucun serveur : `ExpediteurSmtp.message`
la rend seule, et c'est là que se jouent les défauts qui abîment le compte rendu
— l'encodage des accents, la double version du corps, la pièce jointe.

La connexion, elle, s'éprouve contre de vrais serveurs :
`tests/integration/test_smtp_vrais_serveurs.py`.
"""

from __future__ import annotations

from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

import pytest

from greffier.adaptateurs.courriel import ExpediteurSmtp

SUJET = "Compte rendu — réunion du 3 septembre"
CORPS = "## Décisions\n\n- La recette est décalée à jeudi.\n- Michel prévient les usagers.\n"


@pytest.fixture
def piece(tmp_path: Path) -> Path:
    chemin = tmp_path / "compte-rendu.md"
    chemin.write_text(CORPS, encoding="utf-8")
    return chemin


@pytest.fixture
def message(piece: Path) -> Message:
    expediteur = ExpediteurSmtp(serveur="smtp.exemple.fr", expediteur="greffier@exemple.fr")
    return expediteur.message("destinataire@exemple.fr", SUJET, CORPS, [piece])


def sujet_decode(message: Message) -> str:
    """Le sujet tel qu'un client l'affiche, recollé de tous ses morceaux."""
    return str(make_header(decode_header(message["Subject"])))


class TestMessage:
    def test_le_sujet_accentue_arrive_entier(self, message: Message):
        assert sujet_decode(message) == SUJET

    def test_les_deux_versions_du_corps_sont_presentes(self, message: Message):
        """Markdown pour qui refuse le HTML, HTML pour les autres."""
        types = [p.get_content_type() for p in message.walk()]
        assert "text/plain" in types
        assert "text/html" in types

    def test_le_compte_rendu_est_en_piece_jointe(self, message: Message):
        noms = [p.get_filename() for p in message.walk() if p.get_filename()]
        assert noms == ["compte-rendu.md"]

    def test_le_texte_francais_est_en_utf8(self, message: Message):
        """Le défaut passé : tout compte rendu français arrivait en « r√©union »."""
        for partie in message.walk():
            if partie.get_content_type() == "text/plain" and not partie.get_filename():
                charset = partie.get_content_charset()
                assert charset == "utf-8"
                texte = partie.get_payload(decode=True).decode(charset)
                assert "décalée" in texte
                return
        pytest.fail("aucune partie texte trouvée")

    def test_l_expediteur_et_le_destinataire_sont_portes(self, message: Message):
        assert message["From"] == "greffier@exemple.fr"
        assert message["To"] == "destinataire@exemple.fr"
