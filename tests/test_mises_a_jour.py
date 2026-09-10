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


class TestInstallation:
    """Une mise à jour ne doit jamais emporter le travail de qui développe."""

    def depot_git(self, tmp_path, propre: bool = True):
        import subprocess

        depot = tmp_path / "greffier"
        (depot / "macos").mkdir(parents=True)
        (depot / "macos" / "construire.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(depot), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(depot), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(depot), "-c", "user.email=e@x", "-c", "user.name=n",
             "commit", "-qm", "socle"],
            check=True,
        )
        if not propre:
            (depot / "macos" / "construire.sh").write_text("modifié\n", encoding="utf-8")
        return depot

    def test_sans_depot_grave_l_installation_est_refusee(self, monkeypatch):
        monkeypatch.delenv("GREFFIER_DEPOT_SOURCE", raising=False)
        possible, raison = mises_a_jour.installable()
        assert possible is False
        assert "introuvable" in raison

    def test_un_dossier_qui_n_est_pas_un_depot_est_refuse(self, monkeypatch, tmp_path):
        (tmp_path / "macos").mkdir()
        (tmp_path / "macos" / "construire.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(tmp_path))
        possible, raison = mises_a_jour.installable()
        assert possible is False
        assert "git" in raison

    def test_un_depot_propre_est_accepte(self, monkeypatch, tmp_path):
        depot = self.depot_git(tmp_path)
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(depot))
        possible, ou = mises_a_jour.installable()
        assert possible is True
        assert ou == str(depot)

    def test_un_depot_modifie_est_refuse(self, monkeypatch, tmp_path):
        """« git pull » sur un arbre sale échoue à moitié : mieux vaut refuser avant."""
        depot = self.depot_git(tmp_path, propre=False)
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(depot))
        possible, raison = mises_a_jour.installable()
        assert possible is False
        assert "non validées" in raison


class TestRelais:
    """Le relais attend la mort du processus avant de toucher au paquet."""

    def test_il_attend_la_fin_du_processus(self):
        assert 'kill -0 "$2"' in mises_a_jour._RELAIS

    def test_il_refuse_d_agir_si_l_application_tourne_encore(self):
        assert "n'a pas quitté" in mises_a_jour._RELAIS

    def test_il_ne_fusionne_jamais(self):
        """Un dépôt divergent ne doit pas être rafistolé par une mise à jour."""
        assert "git pull --ff-only" in mises_a_jour._RELAIS

    def test_un_pull_qui_echoue_laisse_le_paquet_intact(self):
        assert "le paquet est intact" in mises_a_jour._RELAIS

    def test_il_relance_l_application(self):
        assert "open -a" in mises_a_jour._RELAIS


class TestPaquetPlusRecentQueLeProcessus:
    """Un paquet reconstruit ne remplace pas l'application déjà lancée.

    Coût mesuré : deux heures passées à chercher trois boutons dans une fenêtre
    ouverte la veille, alors qu'ils étaient dans le paquet depuis le matin. La
    fenêtre a maintenant de quoi le dire, et `construire.sh` de quoi relancer.
    """

    def test_hors_du_paquet_la_question_ne_se_pose_pas(self):
        """Depuis la ligne de commande, le code suit le dépôt."""
        from greffier.adaptateurs.mises_a_jour import paquet_plus_recent

        assert not paquet_plus_recent("/usr/bin/python3")

    def test_un_paquet_pose_apres_le_demarrage_est_signale(self, tmp_path):
        from greffier.adaptateurs import mises_a_jour

        faux = tmp_path / "Greffier.app" / "Contents" / "MacOS"
        faux.mkdir(parents=True)
        executable = faux / "Greffier"
        executable.write_text("")
        # Le module a été chargé avant que ce fichier n'existe : c'est exactement
        # la situation d'un paquet reconstruit sous une application qui tourne.
        assert mises_a_jour.paquet_plus_recent(str(executable))

    def test_un_paquet_plus_vieux_ne_dit_rien(self, tmp_path):
        import os
        import time

        from greffier.adaptateurs import mises_a_jour

        faux = tmp_path / "Greffier.app" / "Contents" / "MacOS"
        faux.mkdir(parents=True)
        executable = faux / "Greffier"
        executable.write_text("")
        ancien = time.time() - 3600
        os.utime(executable, (ancien, ancien))
        assert not mises_a_jour.paquet_plus_recent(str(executable))

    def test_un_executable_disparu_ne_leve_pas(self, tmp_path):
        from greffier.adaptateurs.mises_a_jour import paquet_plus_recent

        absent = tmp_path / "Greffier.app" / "Contents" / "MacOS" / "Greffier"
        assert not paquet_plus_recent(str(absent))
