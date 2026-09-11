"""Knowing whether a later version exists, without ever bringing the window down."""

import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adapters import updates


@pytest.fixture
def installed_0_2_0(monkeypatch):
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


def answer_bytes(monkeypatch, bytes_read: bytes) -> None:
    """A binary answer with its length: the length is what makes the progress."""
    class Response(BytesIO):
        headers = {"Content-Length": str(len(bytes_read))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        updates.urllib.request, "urlopen", lambda *_a, **_k: Response(bytes_read)
    )


def fail_to_answer(monkeypatch, trouble: Exception) -> None:
    def tomber(*_args, **_options):
        raise trouble

    monkeypatch.setattr(updates.urllib.request, "urlopen", tomber)


class TestWhenThereIsSomethingBetter:
    def test_a_later_version_is_offered(self, monkeypatch, installed_0_2_0):
        answer(monkeypatch, {"tag_name": "v0.3.0", "html_url": "https://exemple/0.3.0"})
        verdict = updates.check()
        assert verdict.update
        assert verdict.available == "0.3.0"
        assert verdict.adresse == "https://exemple/0.3.0"

    def test_the_sentence_says_both_versions(self, monkeypatch, installed_0_2_0):
        answer(monkeypatch, {"tag_name": "v0.3.0"})
        said = updates.check().say()
        assert "0.3.0" in said and "0.2.0" in said


class TestWhenThereIsNothingBetter:
    def test_the_same_version_offers_nothing(self, monkeypatch, installed_0_2_0):
        answer(monkeypatch, {"tag_name": "v0.2.0"})
        assert updates.check().up_to_date

    def test_an_earlier_version_offers_nothing(self, monkeypatch, installed_0_2_0):
        """A release older than the installed one must trigger nothing."""
        answer(monkeypatch, {"tag_name": "v0.1.0"})
        assert updates.check().up_to_date


class TestWhenNothingAnswers:
    """A check that brought the window down would be a very poor trade."""

    def test_with_no_network_the_trouble_is_reported(self, monkeypatch, installed_0_2_0):
        fail_to_answer(monkeypatch, urllib.error.URLError("injoignable"))
        verdict = updates.check()
        assert "réseau" in verdict.trouble
        assert not verdict.update

    def test_no_published_version_is_not_a_failure(self, monkeypatch, installed_0_2_0):
        fail_to_answer(monkeypatch, urllib.error.HTTPError("u", 404, "absent", {}, None))  # type: ignore[arg-type]
        assert "aucune version publiée" in updates.check().trouble

    def test_an_unreadable_answer_raises_nothing(self, monkeypatch, installed_0_2_0):
        monkeypatch.setattr(updates.urllib.request, "urlopen",
                            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("cassé")))
        assert updates.check().trouble

    def test_a_release_with_no_tag_is_refused(self, monkeypatch, installed_0_2_0):
        answer(monkeypatch, {"html_url": "https://exemple"})
        assert "étiquette" in updates.check().trouble

    def test_with_no_installed_version_nothing_is_concluded(self, monkeypatch):
        monkeypatch.setattr(updates, "installed_version", lambda: "")
        assert updates.check().trouble


class TestInstallingFromTheSources:
    """An update must never carry away the work of whoever is developing."""

    def a_git_repository(self, tmp_path, clean: bool = True):
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
        if not clean:
            (store / "macos" / "construire.sh").write_text("modifié\n", encoding="utf-8")
        return store

    def test_with_no_repository_recorded_installing_is_refused(self, monkeypatch):
        monkeypatch.delenv("GREFFIER_DEPOT_SOURCE", raising=False)
        possible, because = updates.installable()
        assert possible is False
        assert "introuvable" in because

    def test_a_folder_that_is_not_a_repository_is_refused(self, monkeypatch, tmp_path):
        (tmp_path / "macos").mkdir()
        (tmp_path / "macos" / "construire.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(tmp_path))
        possible, because = updates.installable()
        assert possible is False
        assert "git" in because

    def test_a_clean_repository_is_accepted(self, monkeypatch, tmp_path):
        store = self.a_git_repository(tmp_path)
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(store))
        possible, where_in = updates.installable()
        assert possible is True
        assert where_in == str(store)

    def test_a_modified_repository_is_refused(self, monkeypatch, tmp_path):
        """« git pull » sur un arbre sale échoue à moitié : mieux vaut refuser avant."""
        store = self.a_git_repository(tmp_path, clean=False)
        monkeypatch.setenv("GREFFIER_DEPOT_SOURCE", str(store))
        possible, because = updates.installable()
        assert possible is False
        assert "non validées" in because


class TestTheRelayScript:
    """The relay waits for the process to die before touching the bundle."""

    def test_it_waits_for_the_process_to_end(self):
        assert 'kill -0 "$2"' in updates._RELAIS

    def test_it_refuses_to_act_while_the_application_still_runs(self):
        assert "n'a pas quitté" in updates._RELAIS

    def test_it_never_merges(self):
        """Un dépôt divergent ne doit pas être rafistolé par une mise à jour."""
        assert "git pull --ff-only" in updates._RELAIS

    def test_a_pull_that_fails_leaves_the_bundle_untouched(self):
        assert "le paquet est intact" in updates._RELAIS

    def test_it_starts_the_application_again(self):
        assert "open -a" in updates._RELAIS


class TestABundleNewerThanTheProcess:
    """A rebuilt bundle does not replace the application already running.

    Measured cost: two hours spent looking for three buttons in a window opened
    the day before, when they had been in the bundle since the morning. The window
    can now say so, and `construire.sh` can relaunch.
    """

    def test_outside_a_bundle_the_question_does_not_arise(self):
        """Depuis la ligne de commande, le code suit le dépôt."""
        from greffier.adapters.updates import bundle_is_newer

        assert not bundle_is_newer("/usr/bin/python3")

    def test_a_bundle_laid_down_after_startup_is_flagged(self, tmp_path):
        from greffier.adapters import updates

        faux = tmp_path / "Greffier.app" / "Contents" / "MacOS"
        faux.mkdir(parents=True)
        executable = faux / "Greffier"
        executable.write_text("")
        # Le module a été chargé avant que ce fichier n'existe : c'est exactement
        # la situation d'un paquet reconstruit sous une application qui tourne.
        assert updates.bundle_is_newer(str(executable))

    def test_an_older_bundle_says_nothing(self, tmp_path):
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

    def test_a_vanished_executable_does_not_raise(self, tmp_path):
        from greffier.adapters.updates import bundle_is_newer

        absent = tmp_path / "Greffier.app" / "Contents" / "MacOS" / "Greffier"
        assert not bundle_is_newer(str(absent))


class TestTheArtefactForThisSystem:
    """The button has to take the archive of **this** system, and no other.

    All three are attached to the same published version. Installing a Windows
    archive on a Mac would produce nothing that launches.
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
    def test_every_system_takes_its_own(
        self, monkeypatch, installed_0_2_0, system, expected
    ):
        monkeypatch.setattr(updates.platform, "system", lambda: system)
        answer(monkeypatch, self.PUBLICATION)
        verdict = updates.check()
        assert verdict.artefact_nom == expected
        assert verdict.artefact.endswith(expected)
        assert verdict.downloadable

    def test_an_unknown_system_offers_nothing(
        self, monkeypatch, installed_0_2_0
    ):
        monkeypatch.setattr(updates.platform, "system", lambda: "Haiku")
        answer(monkeypatch, self.PUBLICATION)
        verdict = updates.check()
        assert not verdict.downloadable
        assert verdict.update, "la version reste annoncée, seule l'archive manque"

    def test_a_release_with_no_archive_says_so(
        self, monkeypatch, installed_0_2_0
    ):
        """Arrive quand la construction a échoué pour un système : ça se dit."""
        monkeypatch.setattr(updates.platform, "system", lambda: "Darwin")
        answer(monkeypatch, {"tag_name": "v0.3.0", "assets": []})
        verdict = updates.check()
        assert verdict.update and not verdict.downloadable

    def test_an_up_to_date_version_downloads_nothing(self, monkeypatch):
        monkeypatch.setattr(updates, "installed_version", lambda: "0.3.0")
        monkeypatch.setattr(updates.platform, "system", lambda: "Darwin")
        answer(monkeypatch, self.PUBLICATION)
        assert not updates.check().downloadable


class TestDownloadingAndUnpacking:
    def test_the_archive_is_written_and_the_progress_told(self, monkeypatch, tmp_path):
        bytes_read = b"x" * 300000
        answer_bytes(monkeypatch, bytes_read)
        vus: list[tuple[int, int]] = []
        recu, where_in = updates.download(
            "https://exemple/a.zip", tmp_path / "a.zip",
            progress=lambda r, t: vus.append((r, t)),
        )
        assert recu, where_in
        assert (tmp_path / "a.zip").read_bytes() == bytes_read
        assert vus and vus[-1][0] == len(bytes_read)

    def test_an_empty_archive_is_refused(self, monkeypatch, tmp_path):
        """Mieux vaut refuser que remplacer l'application par du vide."""
        answer_bytes(monkeypatch, b"")
        recu, trouble = updates.download(
            "https://exemple/a.zip", tmp_path / "a.zip"
        )
        assert not recu and "vide" in trouble

    def test_with_no_network_nothing_is_written(self, monkeypatch, tmp_path):
        fail_to_answer(monkeypatch, urllib.error.URLError("coupé"))
        recu, trouble = updates.download(
            "https://exemple/a.zip", tmp_path / "a.zip"
        )
        assert not recu and trouble == "pas de réseau"

    def test_a_zip_opens(self, tmp_path):
        import zipfile

        archive = tmp_path / "Greffier-macos.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Greffier.app/Contents/Info.plist", "<plist/>")
        ouvert, where_in = updates.unpack(archive, tmp_path / "dedans")
        assert ouvert, where_in
        assert (tmp_path / "dedans" / "Greffier.app" / "Contents").is_dir()

    def test_a_tar_gz_opens(self, tmp_path):
        import tarfile

        source = tmp_path / "greffier"
        source.mkdir()
        (source / "LISEZMOI.md").write_text("bonjour", encoding="utf-8")
        archive = tmp_path / "Greffier-linux.tar.gz"
        with tarfile.open(archive, "w:gz") as a:
            a.add(source, arcname="greffier")
        ouvert, where_in = updates.unpack(archive, tmp_path / "dedans")
        assert ouvert, where_in
        assert (tmp_path / "dedans" / "greffier" / "LISEZMOI.md").exists()

    def test_an_unknown_format_is_refused(self, tmp_path):
        archive = tmp_path / "Greffier.rar"
        archive.write_bytes(b"nope")
        ouvert, trouble = updates.unpack(archive, tmp_path / "dedans")
        assert not ouvert and "format inconnu" in trouble


class TestAnUpdateLosesNothing:
    """The only question whoever presses that button has.

    The meetings, the minutes, the voice bank, the conversations and the settings
    live in the data folder, outside the application. The relay touches **only**
    the bundle, and this test holds it to that: an update that lost a meeting of
    ninety-two minutes would be worse than no update at all.
    """

    def test_the_relay_never_names_the_data_folder(self):
        relais = updates._RELAIS_BINAIRE
        for interdit in ("Application Support", "banque-de-voix", "reunions",
                         "conversations", "comptes-rendus", "config.toml",
                         "enregistrements"):
            assert interdit not in relais, interdit

    def test_the_relay_keeps_the_old_bundle_before_replacing_it(self):
        """Et le remet si le neuf ne démarre pas : constaté aujourd'hui, une
        mise à jour a laissé le poste sans application du tout."""
        relais = updates._RELAIS_BINAIRE
        assert ".precedent" in relais
        assert relais.count('mv "$DE_COTE" "$APP"') >= 2, "restauré dans les deux échecs"

    def test_the_relay_waits_for_the_application_to_close(self):
        relais = updates._RELAIS_BINAIRE
        assert 'kill -0 "$PID"' in relais
        assert "n'a pas quitte" in relais or "n'a pas quitté" in relais

    def test_nothing_is_installed_when_there_is_nothing_to_take(self):
        verdict = updates.Verdict(installed="0.2.0", available="0.3.0")
        pose, trouble = updates.install_from_release(verdict)
        assert not pose and "aucun binaire" in trouble


class TestTheBundleOfThisProcess:
    def test_the_bundle_follows_from_the_path(self, tmp_path):
        executable = tmp_path / "Greffier.app" / "Contents" / "MacOS" / "Greffier"
        executable.parent.mkdir(parents=True)
        executable.write_text("", encoding="utf-8")
        found = updates.bundle_of_this_process(str(executable))
        assert found is not None and found.name == "Greffier.app"

    def test_outside_a_bundle_there_is_nothing_to_replace(self):
        assert updates.bundle_of_this_process("/usr/local/bin/greffier") is None
