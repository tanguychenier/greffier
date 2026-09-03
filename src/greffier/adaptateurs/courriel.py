"""Envoi du compte rendu par courriel.

Deux implémentations : Outlook déjà authentifié sur le poste (macOS), et SMTP
partout ailleurs. La première ne demande aucun mot de passe, ce qui explique
qu'elle soit préférée là où elle existe.

Le compte rendu part **en HTML** (`gabarit_courriel`), avec le Markdown d'origine
en repli texte. Envoyé en Markdown brut, il arrivait comme un mur de dièses et de
barres verticales, tableaux compris.
"""

from __future__ import annotations

import contextlib
import os
import smtplib
import subprocess
import tempfile
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

from greffier.adaptateurs import gabarit_courriel


class ExpediteurOutlook:
    """Passe par Microsoft Outlook déjà ouvert et authentifié.

    Aucun mot de passe ni serveur à configurer. En contrepartie, macOS exige une
    autorisation d'automatisation, dont la boîte de dialogue n'apparaît pas
    toujours quand le traitement tourne détaché — d'où le message explicite.
    """

    # Sujet et corps passent par des **fichiers**, relus explicitement en UTF-8.
    # « system attribute » les rendait en MacRoman : chaque « é » arrivait en
    # « √© » et chaque tiret cadratin en « ,Äî ». Tout compte rendu en français
    # était donc illisible. Un fichier écarte aussi le risque qu'un guillemet du
    # compte rendu casse le script.
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

    def envoyer(self, destinataire: str, sujet: str, corps: str, pieces: list[Path]) -> None:
        with tempfile.TemporaryDirectory() as dossier:
            fichier_corps = Path(dossier) / "corps.html"
            fichier_sujet = Path(dossier) / "sujet.txt"
            fichier_corps.write_text(gabarit_courriel.courriel(corps), encoding="utf-8")
            fichier_sujet.write_text(sujet, encoding="utf-8")
            resultat = subprocess.run(
                ["osascript", "-", str(fichier_corps), str(fichier_sujet), destinataire,
                 *[str(p) for p in pieces]],
                input=self.SOURCE, capture_output=True, text=True, check=False,
            )
        if resultat.returncode == 0:
            return
        sortie = (resultat.stderr or "") + (resultat.stdout or "")
        if "-1743" in sortie or "not authorized" in sortie.lower() or "autoris" in sortie.lower():
            raise PermissionError(
                "macOS refuse de piloter Outlook. Autorise « Greffier » dans "
                "Réglages Système ▸ Confidentialité et sécurité ▸ Automatisation."
            )
        raise RuntimeError(f"Envoi impossible : {sortie.strip().splitlines()[-1:] or sortie}")


class ExpediteurSmtp:
    """Envoi direct, pour les postes sans Outlook.

    Le mot de passe vient de l'environnement, jamais d'un fichier du dépôt.
    """

    def __init__(
        self,
        serveur: str,
        port: int = 587,
        utilisateur: str = "",
        expediteur: str = "",
        mot_de_passe: str = "",
    ) -> None:
        self.serveur = serveur
        self.port = port
        self.utilisateur = utilisateur
        self.expediteur = expediteur or utilisateur
        self.mot_de_passe = mot_de_passe or os.environ.get("GREFFIER_SMTP_MOT_DE_PASSE", "")

    def message(
        self, destinataire: str, sujet: str, corps: str, pieces: list[Path]
    ) -> EmailMessage:
        """Le courriel à envoyer, sans rien ouvrir.

        Séparé de l'envoi pour être vérifiable seul : ce qu'un destinataire
        reçoit — accents, double version du corps, pièce jointe — se contrôle
        sans serveur, et ne doit pas dépendre du réseau pour l'être.
        """
        message = EmailMessage()
        message["From"] = self.expediteur
        message["To"] = destinataire
        message["Subject"] = sujet
        # Repli texte d'abord, HTML ensuite : les clients affichent le dernier
        # qu'ils savent rendre, et ceux qui refusent le HTML gardent le Markdown.
        message.set_content(corps)
        message.add_alternative(gabarit_courriel.courriel(corps), subtype="html")
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
        """Une session ouverte, chiffrée, et authentifiée s'il y a de quoi.

        465 est le port du TLS implicite (la connexion est chiffrée dès
        l'ouverture) ; STARTTLS — la convention de `smtplib.SMTP` — vaut pour
        587 et le reste. Confondre les deux échoue au premier octet : le serveur
        attend un client qui parle déjà TLS, ou l'inverse.

        Séparé de l'envoi pour que le choix de la convention s'éprouve contre
        de **vrais** serveurs, sans qu'un mot de passe soit nécessaire : ouvrir
        la session et la refermer se fait sans authentifier ni expédier.
        """
        classe = smtplib.SMTP_SSL if self.port == 465 else smtplib.SMTP
        with classe(self.serveur, self.port, timeout=60) as session:
            if classe is smtplib.SMTP:
                session.starttls()
            # RFC 3207 : après STARTTLS, le client resalue — les capacités
            # annoncées en clair ne valent plus. `smtplib` le fait au moment de
            # s'authentifier ou d'expédier ; le faire ici rend la session
            # complète dès son ouverture, `AUTH` compris.
            session.ehlo()
            if self.utilisateur and self.mot_de_passe:
                session.login(self.utilisateur, self.mot_de_passe)
            yield session

    def envoyer(self, destinataire: str, sujet: str, corps: str, pieces: list[Path]) -> None:
        with self.session() as session:
            session.send_message(self.message(destinataire, sujet, corps, pieces))


class ExpediteurFichier:
    """N'envoie rien, écrit à côté. Repli quand aucun envoi n'est configuré."""

    def __init__(self, dossier: Path) -> None:
        self.dossier = dossier

    def envoyer(self, destinataire: str, sujet: str, corps: str, pieces: list[Path]) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        (self.dossier / f"{sujet}.md").write_text(corps, encoding="utf-8")
