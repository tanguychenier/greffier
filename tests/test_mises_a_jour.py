"""Savoir s'il existe une version postérieure, sans jamais faire tomber la fenêtre."""

import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adaptateurs import mises_a_jour


@pytest.fixture
def installee_0_2_0(monkeypatch):
    monkeypatch.setattr(mises_a_jour, "version_installee", lambda: "0.2.0")


def repondre(monkeypatch, contenu: dict) -> None:
    class Reponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        mises_a_jour.urllib.request, "urlopen",
        lambda *_a, **_k: Reponse(json.dumps(contenu).encode("utf-8")),
    )


def echouer(monkeypatch, souci: Exception) -> None:
    def tomber(*_args, **_options):
        raise souci

    monkeypatch.setattr(mises_a_jour.urllib.request, "urlopen", tomber)


class TestQuandIlYAMieux:
    def test_une_version_posterieure_est_proposee(self, monkeypatch, installee_0_2_0):
        repondre(monkeypatch, {"tag_name": "v0.3.0", "html_url": "https://exemple/0.3.0"})
        verdict = mises_a_jour.verifier()
        assert verdict.mise_a_jour
        assert verdict.disponible == "0.3.0"
        assert verdict.adresse == "https://exemple/0.3.0"

    def test_la_phrase_dit_les_deux_versions(self, monkeypatch, installee_0_2_0):
        repondre(monkeypatch, {"tag_name": "v0.3.0"})
        dit = mises_a_jour.verifier().dire()
        assert "0.3.0" in dit and "0.2.0" in dit


class TestQuandIlNYAPasMieux:
    def test_la_meme_version_ne_propose_rien(self, monkeypatch, installee_0_2_0):
        repondre(monkeypatch, {"tag_name": "v0.2.0"})
        assert mises_a_jour.verifier().a_jour

    def test_une_version_anterieure_ne_propose_rien(self, monkeypatch, installee_0_2_0):
        """Une release plus ancienne que l'installée ne doit rien déclencher."""
        repondre(monkeypatch, {"tag_name": "v0.1.0"})
        assert mises_a_jour.verifier().a_jour


class TestQuandRienNeRepond:
    """Une vérification qui fait tomber la fenêtre serait un très mauvais échange."""

    def test_sans_reseau_le_souci_est_rapporte(self, monkeypatch, installee_0_2_0):
        echouer(monkeypatch, urllib.error.URLError("injoignable"))
        verdict = mises_a_jour.verifier()
        assert "réseau" in verdict.souci
        assert not verdict.mise_a_jour

    def test_aucune_version_publiee_n_est_pas_une_panne(self, monkeypatch, installee_0_2_0):
        echouer(monkeypatch, urllib.error.HTTPError("u", 404, "absent", {}, None))  # type: ignore[arg-type]
        assert "aucune version publiée" in mises_a_jour.verifier().souci

    def test_une_reponse_illisible_ne_leve_rien(self, monkeypatch, installee_0_2_0):
        monkeypatch.setattr(mises_a_jour.urllib.request, "urlopen",
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("cassé")))
        assert mises_a_jour.verifier().souci

    def test_une_release_sans_etiquette_est_refusee(self, monkeypatch, installee_0_2_0):
        repondre(monkeypatch, {"html_url": "https://exemple"})
        assert "étiquette" in mises_a_jour.verifier().souci

    def test_sans_version_installee_on_ne_conclut_rien(self, monkeypatch):
        monkeypatch.setattr(mises_a_jour, "version_installee", lambda: "")
        assert mises_a_jour.verifier().souci
