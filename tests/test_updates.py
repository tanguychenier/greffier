"""Savoir s'il existe une version postérieure, sans jamais faire tomber la fenêtre."""

import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adapters import updates


@pytest.fixture
def installee_0_2_0(monkeypatch):
    monkeypatch.setattr(updates, "installed_version", lambda: "0.2.0")


def answer(monkeypatch, content: dict) -> None:
    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        updates.urllib.request, "urlopen",
        lambda *_a, **_k: Response(json.dumps(content).encode("utf-8")),
    )


def repondre_octets(monkeypatch, bytes_read: bytes) -> None:
    """Une réponse binaire, avec sa longueur : c'est elle qui fait l'avancement."""
    class Response(BytesIO):
        headers = {"Content-Length": str(len(bytes_read))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        updates.urllib.request, "urlopen", lambda *_a, **_k: Response(bytes_read)
    )


def echouer(monkeypatch, trouble: Exception) -> None:
    def tomber(*_args, **_options):
        raise trouble

    monkeypatch.setattr(updates.urllib.request, "urlopen", tomber)


class TestQuandIlYAMieux:
    def test_une_version_posterieure_est_proposee(self, monkeypatch, installee_0_2_0):
        answer(monkeypatch, {"tag_name": "v0.3.0", "html_url": "https://exemple/0.3.0"})
        verdict = updates.check()
        assert verdict.update
        assert verdict.available == "0.3.0"
        assert verdict.adresse == "https://exemple/0.3.0"

    def test_la_phrase_dit_les_deux_versions(self, monkeypatch, installee_0_2_0):
        answer(monkeypatch, {"tag_name": "v0.3.0"})
        dit = updates.check().say()
        assert "0.3.0" in dit and "0.2.0" in dit


class TestQuandIlNYAPasMieux:
    def test_la_meme_version_ne_propose_rien(self, monkeypatch, installee_0_2_0):
        answer(monkeypatch, {"tag_name": "v0.2.0"})
        assert updates.check().up_to_date

    def test_une_version_anterieure_ne_propose_rien(self, monkeypatch, installee_0_2_0):
        """Une release plus ancienne que l'installée ne doit rien déclencher."""
        answer(monkeypatch, {"tag_name": "v0.1.0"})
        assert updates.check().up_to_date


class TestQuandRienNeRepond:
    """Une vérification qui fait tomber la fenêtre serait un très mauvais échange."""

    def test_sans_reseau_le_souci_est_rapporte(self, monkeypatch, installee_0_2_0):
        echouer(monkeypatch, urllib.error.URLError("injoignable"))
        verdict = updates.check()
        assert "réseau" in verdict.trouble
        assert not verdict.update

    def test_aucune_version_publiee_n_est_pas_une_panne(self, monkeypatch, installee_0_2_0):
        echouer(monkeypatch, urllib.error.HTTPError("u", 404, "absent", {}, None))  # type: ignore[arg-type]
        assert "aucune version publiée" in updates.check().trouble

    def test_une_reponse_illisible_ne_leve_rien(self, monkeypatch, installee_0_2_0):
        monkeypatch.setattr(updates.urllib.request, "urlopen",
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("cassé")))
        assert updates.check().trouble

    def test_une_release_sans_etiquette_est_refusee(self, monkeypatch, installee_0_2_0):
        answer(monkeypatch, {"html_url": "https://exemple"})
        assert "étiquette" in updates.check().trouble

    def test_sans_version_installee_on_ne_conclut_rien(self, monkeypatch):
        monkeypatch.setattr(updates, "installed_version", lambda: "")
        assert updates.check().trouble


class TestInstallation:
    """Une mise à jour ne doit jamais emporter le travail de qui développe."""

    def depot_git(self, tmp_path, propre: bool = True):
        import subprocess

        store = tmp_path / "greffier"
        (store / "macos").mkdir(parents=True)
        (store / "macos" / "construire.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(store), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(store), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(store), "-c", "user.email=e@x", "-c", "user.name=n",
             "commit", "-qm", "socle"],
            check=True,
        )
        if not propre:
            (store / "macos" / "construire.sh").write_text("modifié\n", encoding="utf-8")
        return store

    def test_sans_depot_grave_l_installation_est_refusee(self, monkeypatch):
        monkeypatch.delenv("GREFFIER_DEPOT_SOURCE", raising=False)
        possible, because = updates.installable()
        assert possible is False
        assert "introuvable" in because

    def test_un_dossier_qui_n_est_pas_un_depot_est_refuse(self, monkeypatch, tmp_path):
        (tmp_path / "macos").mkdir()
        (tmp_path / "macos" / "construire.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(tmp_path))
        possible, because = updates.installable()
        assert possible is False
        assert "git" in because

    def test_un_depot_propre_est_accepte(self, monkeypatch, tmp_path):
        store = self.depot_git(tmp_path)
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(store))
        possible, ou = updates.installable()
        assert possible is True
        assert ou == str(store)

    def test_un_depot_modifie_est_refuse(self, monkeypatch, tmp_path):
        """« git pull » sur un arbre sale échoue à moitié : mieux vaut refuser avant."""
        store = self.depot_git(tmp_path, propre=False)
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(store))
        possible, because = updates.installable()
        assert possible is False
        assert "non validées" in because


class TestRelais:
    """Le relais attend la mort du processus avant de toucher au paquet."""

    def test_il_attend_la_fin_du_processus(self):
        assert 'kill -0 "$2"' in updates._RELAIS

    def test_il_refuse_d_agir_si_l_application_tourne_encore(self):
        assert "n'a pas quitté" in updates._RELAIS

    def test_il_ne_fusionne_jamais(self):
        """Un dépôt divergent ne doit pas être rafistolé par une mise à jour."""
        assert "git pull --ff-only" in updates._RELAIS

    def test_un_pull_qui_echoue_laisse_le_paquet_intact(self):
        assert "le paquet est intact" in updates._RELAIS

    def test_il_relance_l_application(self):
        assert "open -a" in updates._RELAIS


class TestPaquetPlusRecentQueLeProcessus:
    """Un paquet reconstruit ne remplace pas l'application déjà lancée.

    Coût mesuré : deux heures passées à chercher trois boutons dans une fenêtre
    ouverte la veille, alors qu'ils étaient dans le paquet depuis le matin. La
    fenêtre a maintenant de quoi le dire, et `construire.sh` de quoi relancer.
    """

    def test_hors_du_paquet_la_question_ne_se_pose_pas(self):
        """Depuis la ligne de commande, le code suit le dépôt."""
        from greffier.adapters.updates import bundle_is_newer

        assert not bundle_is_newer("/usr/bin/python3")

    def test_un_paquet_pose_apres_le_demarrage_est_signale(self, tmp_path):
        from greffier.adapters import updates

        faux = tmp_path / "Greffier.app" / "Contents" / "MacOS"
        faux.mkdir(parents=True)
        executable = faux / "Greffier"
        executable.write_text("")
        # Le module a été chargé avant que ce fichier n'existe : c'est exactement
        # la situation d'un paquet reconstruit sous une application qui tourne.
        assert updates.bundle_is_newer(str(executable))

    def test_un_paquet_plus_vieux_ne_dit_rien(self, tmp_path):
        import os
        import time

        from greffier.adapters import updates

        faux = tmp_path / "Greffier.app" / "Contents" / "MacOS"
        faux.mkdir(parents=True)
        executable = faux / "Greffier"
        executable.write_text("")
        former = time.time() - 3600
        os.utime(executable, (former, former))
        assert not updates.bundle_is_newer(str(executable))

    def test_un_executable_disparu_ne_leve_pas(self, tmp_path):
        from greffier.adapters.updates import bundle_is_newer

        absent = tmp_path / "Greffier.app" / "Contents" / "MacOS" / "Greffier"
        assert not bundle_is_newer(str(absent))


class TestLArtefactDeCeSysteme:
    """Le bouton doit prendre l'archive de **ce** système, et aucune autre.

    Les trois sont attachées à la même version publiée. Installer une archive
    Windows sur un Mac ne produirait rien de lançable.
    """

    PUBLICATION = {
        "tag_name": "v0.3.0",
        "html_url": "https://exemple/0.3.0",
        "assets": [
            {"name": "Greffier-macos.zip",
             "browser_download_url": "https://exemple/Greffier-macos.zip"},
            {"name": "Greffier-windows.zip",
             "browser_download_url": "https://exemple/Greffier-windows.zip"},
            {"name": "Greffier-linux.tar.gz",
             "browser_download_url": "https://exemple/Greffier-linux.tar.gz"},
        ],
    }

    @pytest.mark.parametrize("system,expected", [
        ("Darwin", "Greffier-macos.zip"),
        ("Windows", "Greffier-windows.zip"),
        ("Linux", "Greffier-linux.tar.gz"),
    ])
    def test_chaque_systeme_prend_la_sienne(
        self, monkeypatch, installee_0_2_0, system, expected
    ):
        monkeypatch.setattr(updates.platform, "system", lambda: system)
        answer(monkeypatch, self.PUBLICATION)
        verdict = updates.check()
        assert verdict.artefact_nom == expected
        assert verdict.artefact.endswith(expected)
        assert verdict.downloadable

    def test_un_systeme_inconnu_ne_propose_rien(
        self, monkeypatch, installee_0_2_0
    ):
        monkeypatch.setattr(updates.platform, "system", lambda: "Haiku")
        answer(monkeypatch, self.PUBLICATION)
        verdict = updates.check()
        assert not verdict.downloadable
        assert verdict.update, "la version reste annoncée, seule l'archive manque"

    def test_une_publication_sans_archive_le_dit(
        self, monkeypatch, installee_0_2_0
    ):
        """Arrive quand la construction a échoué pour un système : ça se dit."""
        monkeypatch.setattr(updates.platform, "system", lambda: "Darwin")
        answer(monkeypatch, {"tag_name": "v0.3.0", "assets": []})
        verdict = updates.check()
        assert verdict.update and not verdict.downloadable

    def test_une_version_a_jour_ne_telecharge_rien(self, monkeypatch):
        monkeypatch.setattr(updates, "installed_version", lambda: "0.3.0")
        monkeypatch.setattr(updates.platform, "system", lambda: "Darwin")
        answer(monkeypatch, self.PUBLICATION)
        assert not updates.check().downloadable


class TestTelechargerEtDeballer:
    def test_l_archive_est_ecrite_et_l_avancement_dit(self, monkeypatch, tmp_path):
        bytes_read = b"x" * 300000
        repondre_octets(monkeypatch, bytes_read)
        vus: list[tuple[int, int]] = []
        recu, ou = updates.download(
            "https://exemple/a.zip", tmp_path / "a.zip",
            progress=lambda r, t: vus.append((r, t)),
        )
        assert recu, ou
        assert (tmp_path / "a.zip").read_bytes() == bytes_read
        assert vus and vus[-1][0] == len(bytes_read)

    def test_une_archive_vide_est_refusee(self, monkeypatch, tmp_path):
        """Mieux vaut refuser que remplacer l'application par du vide."""
        repondre_octets(monkeypatch, b"")
        recu, trouble = updates.download(
            "https://exemple/a.zip", tmp_path / "a.zip"
        )
        assert not recu and "vide" in trouble

    def test_sans_reseau_rien_n_est_ecrit(self, monkeypatch, tmp_path):
        echouer(monkeypatch, urllib.error.URLError("coupé"))
        recu, trouble = updates.download(
            "https://exemple/a.zip", tmp_path / "a.zip"
        )
        assert not recu and trouble == "pas de réseau"

    def test_un_zip_s_ouvre(self, tmp_path):
        import zipfile

        archive = tmp_path / "Greffier-macos.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Greffier.app/Contents/Info.plist", "<plist/>")
        ouvert, ou = updates.unpack(archive, tmp_path / "dedans")
        assert ouvert, ou
        assert (tmp_path / "dedans" / "Greffier.app" / "Contents").is_dir()

    def test_un_tar_gz_s_ouvre(self, tmp_path):
        import tarfile

        source = tmp_path / "greffier"
        source.mkdir()
        (source / "LISEZMOI.md").write_text("bonjour", encoding="utf-8")
        archive = tmp_path / "Greffier-linux.tar.gz"
        with tarfile.open(archive, "w:gz") as a:
            a.add(source, arcname="greffier")
        ouvert, ou = updates.unpack(archive, tmp_path / "dedans")
        assert ouvert, ou
        assert (tmp_path / "dedans" / "greffier" / "LISEZMOI.md").exists()

    def test_un_format_inconnu_est_refuse(self, tmp_path):
        archive = tmp_path / "Greffier.rar"
        archive.write_bytes(b"nope")
        ouvert, trouble = updates.unpack(archive, tmp_path / "dedans")
        assert not ouvert and "format inconnu" in trouble


class TestLaMiseAJourNePerdRien:
    """La seule question de qui appuie sur ce bouton.

    Les réunions, les comptes rendus, la banque de voix, les conversations et
    les réglages vivent dans le dossier de données, hors de l'application. Le
    relais ne touche **que** le paquet, et ce test le tient : une mise à jour
    qui ferait perdre une réunion de quatre-vingt-douze minutes serait pire que
    pas de mise à jour du tout.
    """

    def test_le_relais_ne_nomme_jamais_le_dossier_de_donnees(self):
        relais = updates._RELAIS_BINAIRE
        for interdit in ("Application Support", "banque-de-voix", "reunions",
                         "conversations", "comptes-rendus", "config.toml",
                         "enregistrements"):
            assert interdit not in relais, interdit

    def test_le_relais_garde_l_ancien_paquet_avant_de_le_remplacer(self):
        """Et le remet si le neuf ne démarre pas : constaté aujourd'hui, une
        mise à jour a laissé le poste sans application du tout."""
        relais = updates._RELAIS_BINAIRE
        assert ".precedent" in relais
        assert relais.count('mv "$DE_COTE" "$APP"') >= 2, "restauré dans les deux échecs"

    def test_le_relais_attend_la_fermeture(self):
        relais = updates._RELAIS_BINAIRE
        assert 'kill -0 "$PID"' in relais
        assert "n'a pas quitte" in relais or "n'a pas quitté" in relais

    def test_rien_n_est_installe_quand_il_n_y_a_rien_a_prendre(self):
        verdict = updates.Verdict(installed="0.2.0", available="0.3.0")
        pose, trouble = updates.install_from_release(verdict)
        assert not pose and "aucun binaire" in trouble


class TestLePaquetDeCeProcessus:
    def test_le_paquet_se_deduit_du_chemin(self, tmp_path):
        executable = tmp_path / "Greffier.app" / "Contents" / "MacOS" / "Greffier"
        executable.parent.mkdir(parents=True)
        executable.write_text("", encoding="utf-8")
        trouve = updates.bundle_of_this_process(str(executable))
        assert trouve is not None and trouve.name == "Greffier.app"

    def test_hors_du_paquet_il_n_y_a_rien_a_remplacer(self):
        assert updates.bundle_of_this_process("/usr/local/bin/greffier") is None
