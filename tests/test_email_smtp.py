"""What a recipient receives, and who is allowed to receive the password.

Composing the email depends on no server: `SmtpSender.message` returns it on its
own, and that is where the defects that spoil the minutes live, the encoding of
the accents, the two versions of the body, the attachment.

Opening the session is tested against a mail server started in a thread, with a
self-signed certificate the system does not know (`tests/fixtures/tls/`). What
is measured is whether that server ever receives the password: it did, on both
ports, until the sender checked the certificate. Real servers are covered in
`tests/integration/test_smtp_real_servers.py`.
"""

from __future__ import annotations

import base64
import os
import smtplib
import socket
import ssl
import threading
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.adapters.email import SmtpSender

SUBJECT = "Compte rendu : réunion du 3 septembre"
CORPS = "## Décisions\n\n- La recette est décalée à jeudi.\n- Marcel prévient les usagers.\n"

TLS_FIXTURES = Path(__file__).parent / "fixtures" / "tls"
CERTIFICATE = TLS_FIXTURES / "certificat.pem"
KEY = TLS_FIXTURES / "cle.pem"


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
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                charset = part.get_content_charset()
                assert charset == "utf-8"
                text = part.get_payload(decode=True).decode(charset)
                assert "décalée" in text
                return
        pytest.fail("aucune partie texte trouvée")

    def test_the_sender_and_the_recipient_are_carried(self, message: Message):
        assert message["From"] == "greffier@exemple.fr"
        assert message["To"] == "destinataire@exemple.fr"


class MailServer:
    """A mail server on the loopback that writes down the credentials it is given.

    It carries the fixture's self-signed certificate, so it stands for any server
    the system does not vouch for: a box on the hotel Wi-Fi as much as a company
    relay. It speaks the few lines `SmtpSender.session` needs and nothing more.
    `AUTH` is announced only once the connection is encrypted, as real servers do.
    """

    def __init__(self, implicit_tls: bool) -> None:
        self.implicit_tls = implicit_tls
        self.credentials: list[tuple[str, str]] = []
        self.messages: list[bytes] = []
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(CERTIFICATE, KEY)
        self.door = socket.socket()
        self.door.bind(("127.0.0.1", 0))
        self.door.listen()
        self.port: int = self.door.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def join(self) -> None:
        """Waits for the conversation to end, so that what was recorded is final."""
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise TimeoutError("the test server has not finished its conversation")

    def _serve(self) -> None:
        self._attach(self.door.accept()[0])
        self.door.close()
        try:
            if self.implicit_tls:
                self._encrypt()
            self._converse()
        except OSError:
            # A refused handshake, or a client that hung up: the outcomes measured.
            pass
        finally:
            self.connection.close()

    def _attach(self, connection: socket.socket) -> None:
        self.connection = connection
        self.stream = connection.makefile("rwb")

    def _encrypt(self) -> None:
        self._attach(self.context.wrap_socket(self.connection, server_side=True))

    def _say(self, *lines: str) -> None:
        for line in lines:
            self.stream.write(line.encode() + b"\r\n")
        self.stream.flush()

    def _converse(self) -> None:
        self._say("220 serveur d'essai")
        while line := self.stream.readline().decode().strip():
            verb = line.upper()
            if verb.startswith(("EHLO", "HELO")):
                self._say(*self._features())
            elif verb == "STARTTLS":
                self._say("220 vas-y")
                self._encrypt()
            elif verb.startswith("AUTH PLAIN"):
                self._note(line.split()[2])
                self._say("235 ok")
            elif verb == "DATA":
                self._say("354 envoie")
                self.messages.append(self._read_message())
                self._say("250 ok")
            elif verb == "QUIT":
                self._say("221 au revoir")
                return
            else:
                self._say("250 ok")

    def _features(self) -> list[str]:
        if isinstance(self.connection, ssl.SSLSocket):
            return ["250-essai", "250 AUTH PLAIN LOGIN"]
        return ["250-essai", "250 STARTTLS"]

    def _note(self, token: str) -> None:
        _, user, password = base64.b64decode(token).split(b"\0")
        self.credentials.append((user.decode(), password.decode()))

    def _read_message(self) -> bytes:
        """Everything up to the lone dot; an empty read means the client is gone."""
        lines = []
        while (line := self.stream.readline()) not in (b".\r\n", b""):
            lines.append(line)
        return b"".join(lines)


def redirected(monkeypatch: pytest.MonkeyPatch, name: str, port: int) -> None:
    """The smtplib class the sender will pick, made to connect to the test server.

    The sender reads the convention off the port number alone, 465 for implicit
    TLS and anything else for STARTTLS, so a test has to say 465 or 587 to reach
    the branch it means while the server listens wherever the system allowed.
    One class at a time: `SMTP_SSL.__init__` calls the module's `SMTP` by name,
    and patching both sends it through the wrong subclass.
    """
    original = getattr(smtplib, name)

    class Redirected(original):
        def __init__(self, host: str = "", _port: int = 0, *args: object, **kwargs: object):
            super().__init__(host, port, *args, **kwargs)

    monkeypatch.setattr(smtplib, name, Redirected)


@pytest.fixture(params=[465, 587], ids=["465-implicit-tls", "587-starttls"])
def convention(request, monkeypatch) -> tuple[int, MailServer]:
    """The port the sender is told, and a server listening behind it."""
    port: int = request.param
    implicit_tls = port == 465
    server = MailServer(implicit_tls)
    redirected(monkeypatch, "SMTP_SSL" if implicit_tls else "SMTP", server.port)
    return port, server


class TestTheServerHasToProveWhoItIs:
    """The defect as it was: an encrypted connection to whoever answered.

    Without a context of its own, smtplib verifies nothing. A self-signed server
    received the user name and the password on both conventions; the connection
    was encrypted against nobody in particular.
    """

    def test_an_unknown_certificate_is_refused_before_the_password(self, convention):
        port, server = convention
        sender = SmtpSender("127.0.0.1", port=port, user="greffier", password="secret")
        with pytest.raises(ssl.SSLCertVerificationError), sender.session():
            pass
        server.join()
        assert server.credentials == []

    def test_the_declared_authority_opens_the_session(self, convention):
        """An in-house server, vouched for by a file rather than by the system."""
        port, server = convention
        sender = SmtpSender(
            "127.0.0.1", port=port, user="greffier", password="secret",
            certificate=str(CERTIFICATE),
        )
        with sender.session() as session:
            assert isinstance(session.sock, ssl.SSLSocket)
        server.join()
        assert server.credentials == [("greffier", "secret")]

    def test_the_minutes_travel_through_the_checked_session(self, convention, piece):
        port, server = convention
        sender = SmtpSender(
            "127.0.0.1", port=port, user="greffier", password="secret",
            sender="greffier@exemple.fr", certificate=str(CERTIFICATE),
        )
        sender.send("equipe@exemple.fr", SUBJECT, CORPS, [piece])
        server.join()
        assert server.credentials == [("greffier", "secret")]
        assert b"compte-rendu.md" in server.messages[0]


class TestTheContext:
    @pytest.mark.parametrize("certificate", ["", str(CERTIFICATE)], ids=["system", "own-file"])
    def test_it_demands_a_certificate_and_checks_the_name(self, certificate):
        """An authority file changes who is trusted, never how much."""
        context = SmtpSender("smtp.exemple.fr", certificate=certificate).tls_context()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True


class TestTheSettingReachesTheSender:
    """The authority file is a setting like the others: French in the file."""

    @pytest.fixture(autouse=True)
    def without_an_environment(self, monkeypatch, tmp_path):
        for key in list(os.environ):
            if key.startswith("GREFFIER_"):
                monkeypatch.delenv(key)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
        monkeypatch.chdir(tmp_path)

    def test_the_toml_file_names_it_in_french(self, tmp_path):
        file = tmp_path / "config.toml"
        file.write_text(
            '[courriel]\nserveur = "smtp.exemple.fr"\ncertificat = "/etc/ssl/entreprise.pem"\n',
            encoding="utf-8",
        )
        assert Config.load(file).email.certificate == "/etc/ssl/entreprise.pem"

    def test_the_environment_names_it_too(self, monkeypatch):
        """To force it for one command, the way `GREFFIER_MINUTES__MODEL` is forced."""
        monkeypatch.setenv("GREFFIER_EMAIL__CERTIFICATE", "/etc/ssl/entreprise.pem")
        assert Config().email.certificate == "/etc/ssl/entreprise.pem"

    def test_without_it_the_system_store_decides(self):
        assert Config().email.certificate == ""
