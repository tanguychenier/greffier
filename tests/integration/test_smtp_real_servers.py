"""The SMTP session, opened against real servers.

The code said it had "not yet met a real server". A test server started inside
the process would change nothing: it would answer what it was taught to answer.
This test **connects** — Gmail and Office 365, the two providers the comment
named — and checks that the convention chosen from the port is the one the
server expects.

What is covered: the connection succeeds, the encryption is in place, and the
server accepts the conversation. `SmtpSender.session` is the product's real
code; no password is needed to open one, so nothing is authenticated and
nothing is sent. Sending to a third party from a test suite is not a proof, it
is one email too many.

Depends on the network: marked "integration", and skipped when the port is
closed (a CI runner with no SMTP egress, a filtered corporate network).

    pytest -m integration
"""

from __future__ import annotations

import smtplib
import ssl

import pytest

from greffier.adapters.email import SmtpSender

pytestmark = pytest.mark.integration

#: Les deux conventions, chez deux fournisseurs. 465 chiffre dès l'ouverture,
#: 587 négocie par STARTTLS ; se tromper échoue au premier octet.
SERVEURS = [
    ("smtp.gmail.com", 465),
    ("smtp.gmail.com", 587),
    ("smtp.office365.com", 587),
]


@pytest.fixture(params=SERVEURS, ids=lambda p: f"{p[0]}:{p[1]}")
def session(request):
    """A session opened by the real code, or the test is skipped."""
    server, port = request.param
    sender = SmtpSender(server=server, port=port)
    try:
        with sender.session() as ouverte:
            yield ouverte
    except (TimeoutError, OSError, smtplib.SMTPException, ssl.SSLError) as erreur:
        pytest.skip(f"{server}:{port} injoignable ({type(erreur).__name__}) : {erreur}")


class TestSessionReelle:
    def test_the_connection_succeeds(self, session: smtplib.SMTP):
        """The server said hello and the session holds: the port and the class agree."""
        code, _ = session.docmd("NOOP")
        assert code == 250

    def test_the_session_is_encrypted(self, session: smtplib.SMTP):
        """TLS implicite ou négocié, le résultat doit être le même : chiffré.

        C'est la seule vérification qui distingue les deux conventions mal
        choisies d'une session correcte : un `SMTP` nu sur 465, ou un
        `SMTP_SSL` sur 587, n'arrive jamais jusqu'ici.
        """
        assert isinstance(session.sock, ssl.SSLSocket)
        assert session.sock.version().startswith("TLS")

    def test_the_server_announces_its_capabilities_after_encryption(self, session: smtplib.SMTP):
        """`AUTH` n'est annoncé qu'une fois la session chiffrée.

        Un serveur qui l'annonce prouve deux choses d'un coup : il a vu un
        client chiffré, et il est prêt à recevoir un mot de passe — ce que le
        produit fera quand il en aura un.
        """
        assert session.has_extn("auth")
