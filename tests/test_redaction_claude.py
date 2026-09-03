"""L'appel à Claude Code : ce qui part sur la ligne de commande.

Le modèle est passé explicitement. Sans cela, l'outil suivrait le réglage
personnel de qui l'a installé : le compte rendu changerait de rédacteur sans
que personne ne l'ait décidé, et pourrait consommer le haut de la gamme là où
le second suffit.
"""

import subprocess

import pytest

from greffier.adaptateurs.redaction_claude import RedacteurClaude


@pytest.fixture
def espion(monkeypatch):
    """Retient la commande lancée, sans jamais appeler Claude Code."""
    vu: dict[str, list[str]] = {}

    def faux_run(commande, **options):
        vu["commande"] = list(commande)
        vu["entree"] = options.get("input", "")
        return subprocess.CompletedProcess(commande, 0, stdout="# Compte rendu\n", stderr="")

    monkeypatch.setattr("greffier.adaptateurs.redaction_claude.shutil.which",
                        lambda _nom: "/usr/local/bin/claude")
    monkeypatch.setattr("greffier.adaptateurs.redaction_claude.subprocess.run", faux_run)
    return vu


class TestModele:
    def test_le_modele_demande_est_transmis(self, espion):
        RedacteurClaude("opus").rediger("Sandy : bonjour.")
        assert "--model" in espion["commande"]
        assert espion["commande"][espion["commande"].index("--model") + 1] == "opus"

    def test_sans_modele_rien_n_est_impose(self, espion):
        """Utile pour éprouver l'outil tel qu'il est réglé sur le poste."""
        RedacteurClaude().rediger("Sandy : bonjour.")
        assert "--model" not in espion["commande"]

    def test_la_transcription_passe_par_l_entree_standard(self, espion):
        """Une transcription d'une heure dépasse la taille admise pour un argument."""
        RedacteurClaude("opus").rediger("Sandy : bonjour.")
        assert "Sandy : bonjour." in espion["entree"]
        assert not any("Sandy" in morceau for morceau in espion["commande"])

    def test_aucun_outil_n_est_autorise(self, espion):
        """Le rédacteur écrit un document, il n'a rien à lire ni à exécuter."""
        commande = espion if False else None
        RedacteurClaude("opus").rediger("x")
        assert "--allowed-tools" in espion["commande"]
        assert espion["commande"][espion["commande"].index("--allowed-tools") + 1] == ""
        assert commande is None


class TestEchecs:
    def test_claude_absent_le_dit_et_propose_la_solution(self, monkeypatch):
        monkeypatch.setattr("greffier.adaptateurs.redaction_claude.shutil.which",
                            lambda _nom: None)
        with pytest.raises(RuntimeError, match="ollama"):
            RedacteurClaude("opus").rediger("x")

    def test_une_sortie_vide_est_une_erreur(self, monkeypatch):
        monkeypatch.setattr("greffier.adaptateurs.redaction_claude.shutil.which",
                            lambda _nom: "/usr/local/bin/claude")
        monkeypatch.setattr(
            "greffier.adaptateurs.redaction_claude.subprocess.run",
            lambda commande, **o: subprocess.CompletedProcess(commande, 0, "", "quota atteint"),
        )
        with pytest.raises(RuntimeError, match="quota atteint"):
            RedacteurClaude("opus").rediger("x")
