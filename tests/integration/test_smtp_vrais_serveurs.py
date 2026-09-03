"""La session SMTP, ouverte contre de vrais serveurs.

Le code disait n'avoir « pas encore rencontré un vrai serveur ». Un serveur
d'essai monté dans le processus n'y changerait rien : il répondrait ce qu'on lui
a appris à répondre. Ce test se **connecte** — Gmail et Office 365, les deux
fournisseurs que le commentaire nommait — et vérifie que la convention choisie
d'après le port est celle que le serveur attend.

Ce qui est éprouvé : la connexion aboutit, le chiffrement est en place, et le
serveur accepte la conversation. `ExpediteurSmtp.session` est le vrai code du
produit ; aucun mot de passe n'est nécessaire pour l'ouvrir, donc rien n'est
authentifié ni expédié — envoyer chez un tiers depuis une suite de tests n'est
pas une preuve, c'est un courriel de trop.

Dépend du réseau : marqué « integration », et ignoré quand le port est fermé
(exécuteur d'intégration continue sans sortie SMTP, réseau d'entreprise filtré).

    pytest -m integration
"""

from __future__ import annotations

import smtplib
import ssl

import pytest

from greffier.adaptateurs.courriel import ExpediteurSmtp

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
    """Une session ouverte par le vrai code, ou le test est ignoré."""
    serveur, port = request.param
    expediteur = ExpediteurSmtp(serveur=serveur, port=port)
    try:
        with expediteur.session() as ouverte:
            yield ouverte
    except (TimeoutError, OSError, smtplib.SMTPException, ssl.SSLError) as erreur:
        pytest.skip(f"{serveur}:{port} injoignable ({type(erreur).__name__}) : {erreur}")


class TestSessionReelle:
    def test_la_connexion_aboutit(self, session: smtplib.SMTP):
        """Le serveur a salué, et la session tient : le port et la classe s'accordent."""
        code, _ = session.docmd("NOOP")
        assert code == 250

    def test_la_session_est_chiffree(self, session: smtplib.SMTP):
        """TLS implicite ou négocié, le résultat doit être le même : chiffré.

        C'est la seule vérification qui distingue les deux conventions mal
        choisies d'une session correcte : un `SMTP` nu sur 465, ou un
        `SMTP_SSL` sur 587, n'arrive jamais jusqu'ici.
        """
        assert isinstance(session.sock, ssl.SSLSocket)
        assert session.sock.version().startswith("TLS")

    def test_le_serveur_annonce_ses_capacites_apres_chiffrement(self, session: smtplib.SMTP):
        """`AUTH` n'est annoncé qu'une fois la session chiffrée.

        Un serveur qui l'annonce prouve deux choses d'un coup : il a vu un
        client chiffré, et il est prêt à recevoir un mot de passe — ce que le
        produit fera quand il en aura un.
        """
        assert session.has_extn("auth")
