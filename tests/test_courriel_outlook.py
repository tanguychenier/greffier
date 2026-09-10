"""La sonde d'envoi : savoir au début de la réunion si le compte rendu partira.

Le défaut, constaté le 2026-09-10 : l'envoi d'une réunion de 1 h 42 a échoué à
12 h 17 devant un écran verrouillé, deux heures après le moment où quelqu'un
était au clavier et où un clic aurait suffi. macOS demande une autorisation
d'automatisation la première fois, et sa boîte de dialogue n'apparaît pas
toujours quand le traitement tourne détaché.

Aucun `osascript` n'est lancé ici : c'est le sous-processus qui est remplacé, ce
qui rend chaque code d'erreur d'AppleScript éprouvable sans Outlook ni macOS.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from greffier.adaptateurs.courriel import ExpediteurOutlook


class Sortie:
    def __init__(self, returncode: int, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


def _repondre(monkeypatch: pytest.MonkeyPatch, sortie: Any) -> list[list[str]]:
    appels: list[list[str]] = []

    def faux_run(commande: list[str], **_options: Any) -> Any:
        appels.append(commande)
        if isinstance(sortie, Exception):
            raise sortie
        return sortie

    monkeypatch.setattr(subprocess, "run", faux_run)
    return appels


class TestSondeDEnvoi:
    def test_la_voie_libre_ne_dit_rien(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _repondre(monkeypatch, Sortie(0, stdout="Microsoft Outlook"))
        assert ExpediteurOutlook().eprouver() is None

    def test_la_sonde_n_envoie_rien(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Elle demande son nom à Outlook, et rien de plus."""
        appels = _repondre(monkeypatch, Sortie(0))
        ExpediteurOutlook().eprouver()
        script = " ".join(appels[0])
        assert "get name" in script
        assert "send" not in script
        assert "outgoing message" not in script

    def test_l_autorisation_manquante_dit_où_cliquer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un message qui ne dit pas quoi faire fait croire que tout est perdu."""
        _repondre(monkeypatch, Sortie(1, stderr="execution error: ... (-1743)"))
        empeche = ExpediteurOutlook().eprouver()
        assert empeche is not None
        assert "Automatisation" in empeche
        assert "ne partira pas" in empeche

    def test_outlook_ferme_est_dit_autrement(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repondre(monkeypatch, Sortie(1, stderr="Application isn't running (-1728)"))
        empeche = ExpediteurOutlook().eprouver()
        assert empeche is not None
        assert "lancé" in empeche

    def test_une_erreur_inconnue_est_rapportée_telle_quelle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repondre(monkeypatch, Sortie(1, stderr="quelque chose d'inédit"))
        empeche = ExpediteurOutlook().eprouver()
        assert empeche is not None
        assert "inédit" in empeche

    def test_une_sonde_qui_n_en_finit_pas_ne_bloque_pas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Elle est appelée au démarrage d'une réunion : elle doit rendre la main."""
        _repondre(monkeypatch, subprocess.TimeoutExpired(cmd="osascript", timeout=20))
        assert ExpediteurOutlook().eprouver() == "Outlook ne répond pas."

    def test_osascript_absent_ne_releve_rien(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repondre(monkeypatch, FileNotFoundError("osascript"))
        assert ExpediteurOutlook().eprouver() == "Outlook ne répond pas."
