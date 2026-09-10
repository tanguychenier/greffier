"""Sending the minutes by email."""

from __future__ import annotations

import contextlib
import os
import smtplib
import subprocess
import tempfile
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

from greffier.adapters import email_template


class OutlookSender:
    """Goes through Microsoft Outlook, already open and signed in.

    No password and no server to configure. In exchange macOS requires automation
    consent, whose dialog does not always appear when the processing runs detached.
    """

    SOURCE = """on run argv
  set cheminCorps to item 1 of argv
  set cheminSujet to item 2 of argv
  set leDest to item 3 of argv
  set leCorps to (read (POSIX file cheminCorps) as «class utf8»)
  set leSujet to (read (POSIX file cheminSujet) as «class utf8»)
  tell application "Microsoft Outlook"
    set m to make new outgoing message with properties {subject:leSujet, content:leCorps}
    make new recipient at m with properties {email address:{address:leDest}}
    repeat with i from 4 to (count of argv)
      make new attachment at m with properties {file:(POSIX file (item i of argv))}
    end repeat
    send m
  end tell
end run
"""

    SONDE = 'tell application "Microsoft Outlook" to get name'

    def probe(self) -> str | None:
        """What would stop the send, or nothing when the way is clear.

        Called at the start of the meeting and not at the end, and that is the whole
        point: on 2026-09-10 a send failed at 12:17 in front of a locked screen, two
        hours after the question could have been settled with one click.
        """
        try:
            outcome = subprocess.run(
                ["osascript", "-e", self.SONDE],
                capture_output=True, text=True, check=False, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "Outlook ne répond pas."
        if outcome.returncode == 0:
            return None
        output = (outcome.stderr or "") + (outcome.stdout or "")
        if "-1743" in output or "not authorized" in output.lower():
            return (
                "macOS n'autorise pas encore Greffier à piloter Outlook. "
                "Réglages Système ▸ Confidentialité et sécurité ▸ Automatisation, "
                "coche Outlook sous Greffier. Sans cela, le compte rendu ne "
                "partira pas."
            )
        if "-1728" in output or "not running" in output.lower():
            return "Outlook n'est pas lancé : ouvre-le avant la fin de la réunion."
        latest = output.strip().splitlines()[-1:] or [output.strip()]
        return f"Outlook ne répond pas comme prévu : {latest[0]}"

    def send(self, recipient: str, subject: str, corps: str, pieces: list[Path]) -> None:
        with tempfile.TemporaryDirectory() as folder:
            fichier_corps = Path(folder) / "corps.html"
            fichier_sujet = Path(folder) / "sujet.txt"
            fichier_corps.write_text(email_template.email(corps), encoding="utf-8")
            fichier_sujet.write_text(subject, encoding="utf-8")
            outcome = subprocess.run(
                ["osascript", "-", str(fichier_corps), str(fichier_sujet), recipient,
                 *[str(p) for p in pieces]],
                input=self.SOURCE, capture_output=True, text=True, check=False,
            )
        if outcome.returncode == 0:
            return
        output = (outcome.stderr or "") + (outcome.stdout or "")
        if "-1743" in output or "not authorized" in output.lower() or "autoris" in output.lower():
            raise PermissionError(
                "macOS refuse de piloter Outlook. Autorise « Greffier » dans "
                "Réglages Système ▸ Confidentialité et sécurité ▸ Automatisation."
            )
        raise RuntimeError(f"Envoi impossible : {output.strip().splitlines()[-1:] or output}")

class SmtpSender:
    """Direct sending, for machines without Outlook."""

    def __init__(
        self,
        server: str,
        port: int = 587,
        user: str = "",
        sender: str = "",
        mot_de_passe: str = "",
    ) -> None:
        self.server = server
        self.port = port
        self.user = user
        self.sender = sender or user
        self.mot_de_passe = mot_de_passe or os.environ.get("GREFFIER_SMTP_MOT_DE_PASSE", "")

    def message(
        self, recipient: str, subject: str, corps: str, pieces: list[Path]
    ) -> EmailMessage:
        """The email to send, without opening anything."""
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(corps)
        message.add_alternative(email_template.email(corps), subtype="html")
        for piece in pieces:
            message.add_attachment(
                piece.read_bytes(),
                maintype="text",
                subtype="markdown" if piece.suffix == ".md" else "plain",
                filename=piece.name,
            )
        return message

    @contextlib.contextmanager
    def session(self) -> Iterator[smtplib.SMTP]:
        """A session, opened, encrypted and authenticated."""
        classe = smtplib.SMTP_SSL if self.port == 465 else smtplib.SMTP
        with classe(self.server, self.port, timeout=60) as session:
            if classe is smtplib.SMTP:
                session.starttls()
            session.ehlo()
            if self.user and self.mot_de_passe:
                session.login(self.user, self.mot_de_passe)
            yield session

    def send(self, recipient: str, subject: str, corps: str, pieces: list[Path]) -> None:
        with self.session() as session:
            session.send_message(self.message(recipient, subject, corps, pieces))

class FileSender:
    """Sends nothing, writes alongside. Fallback when nothing else is set."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def send(self, recipient: str, subject: str, corps: str, pieces: list[Path]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{subject}.md").write_text(corps, encoding="utf-8")
