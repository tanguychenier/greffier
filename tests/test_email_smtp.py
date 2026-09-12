"""What a recipient receives, checked without opening anything.

Composing the email depends on no server: `SmtpSender.message` returns it on its
own, and that is where the defects that spoil the minutes live, the encoding of
the accents, the two versions of the body, the attachment.

The connection is covered against real servers, in
`tests/integration/test_smtp_real_servers.py`.
"""

from __future__ import annotations

from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

import pytest

from greffier.adapters.email import SmtpSender

SUBJECT = "Compte rendu : réunion du 3 septembre"
CORPS = "## Décisions\n\n- La recette est décalée à jeudi.\n- Marcel prévient les usagers.\n"


@pytest.fixture
def piece(tmp_path: Path) -> Path:
    path = tmp_path / "compte-rendu.md"
    path.write_text(CORPS, encoding="utf-8")
    return path


@pytest.fixture
def message(piece: Path) -> Message:
    sender = SmtpSender(server="smtp.exemple.fr", sender="greffier@exemple.fr")
    return sender.message("destinataire@exemple.fr", SUBJECT, CORPS, [piece])


def decoded_subject(message: Message) -> str:
    """The subject as a client shows it, glued back from all its pieces."""
    return str(make_header(decode_header(message["Subject"])))


class TestMessage:
    def test_an_accented_subject_arrives_whole(self, message: Message):
        assert decoded_subject(message) == SUBJECT

    def test_both_versions_of_the_body_are_there(self, message: Message):
        """Markdown for whoever refuses HTML, HTML for the others."""
        types = [p.get_content_type() for p in message.walk()]
        assert "text/plain" in types
        assert "text/html" in types

    def test_the_minutes_are_attached(self, message: Message):
        names = [p.get_filename() for p in message.walk() if p.get_filename()]
        assert names == ["compte-rendu.md"]

    def test_the_french_text_is_in_utf8(self, message: Message):
        """The defect as it was: every French set of minutes arrived as "r√©union"."""
        for partie in message.walk():
            if partie.get_content_type() == "text/plain" and not partie.get_filename():
                charset = partie.get_content_charset()
                assert charset == "utf-8"
                text = partie.get_payload(decode=True).decode(charset)
                assert "décalée" in text
                return
        pytest.fail("aucune partie texte trouvée")

    def test_the_sender_and_the_recipient_are_carried(self, message: Message):
        assert message["From"] == "greffier@exemple.fr"
        assert message["To"] == "destinataire@exemple.fr"
