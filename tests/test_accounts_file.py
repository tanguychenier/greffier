"""The connected accounts on disk: consents, secrets, journal, the model's servers."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from greffier.adapters import accounts_file
from greffier.domain.accounts import Consent, Deed
from greffier.domain.accounts_catalogue import GITLAB, MICROSOFT, TRELLO


class TestTheConsents:
    def test_a_consent_is_kept_with_its_moment(self, tmp_path: Path) -> None:
        file = tmp_path / "comptes.json"
        accounts_file.write_consent(Consent("trello", frozenset({"lire", "ecrire"})), file)
        read = accounts_file.read_consents(file)
        assert read["trello"].powers == frozenset({"lire", "ecrire"})
        assert read["trello"].given_at

    def test_an_empty_consent_takes_the_service_out(self, tmp_path: Path) -> None:
        file = tmp_path / "comptes.json"
        accounts_file.write_consent(Consent("trello", frozenset({"lire"})), file)
        accounts_file.write_consent(Consent("trello", frozenset()), file)
        assert accounts_file.read_consents(file) == {}

    def test_a_damaged_file_reads_as_nothing(self, tmp_path: Path) -> None:
        file = tmp_path / "comptes.json"
        file.write_text("{", encoding="utf-8")
        assert accounts_file.read_consents(file) == {}
        assert accounts_file.read_consents(tmp_path / "absent.json") == {}


class TestTheSecrets:
    def test_the_fields_go_to_the_tokens_file_for_the_owner_alone(self, tmp_path: Path) -> None:
        file = tmp_path / "jetons.toml"
        fields = {"adresse": "https://gitlab.x", "jeton": "glpat"}
        accounts_file.store_secrets(GITLAB, fields, file)
        assert accounts_file.secrets_of(GITLAB, file) == fields
        assert accounts_file.connected(GITLAB, file)
        if os.name == "posix":
            assert stat.S_IMODE(file.stat().st_mode) == 0o600

    def test_a_field_missing_means_not_connected(self, tmp_path: Path) -> None:
        file = tmp_path / "jetons.toml"
        accounts_file.store_secrets(TRELLO, {"cle": "k"}, file)
        assert not accounts_file.connected(TRELLO, file)

    def test_forgetting_takes_every_field_out(self, tmp_path: Path) -> None:
        file = tmp_path / "jetons.toml"
        accounts_file.store_secrets(TRELLO, {"cle": "k", "jeton": "t"}, file)
        accounts_file.forget_secrets(TRELLO, file)
        assert accounts_file.secrets_of(TRELLO, file) == {}

    def test_all_secrets_are_read_per_service(self, tmp_path: Path) -> None:
        file = tmp_path / "jetons.toml"
        accounts_file.store_secrets(TRELLO, {"cle": "k", "jeton": "t"}, file)
        assert accounts_file.all_secrets([TRELLO, GITLAB], file) == {
            "trello": {"cle": "k", "jeton": "t"}, "gitlab": {},
        }


class TestTheJournal:
    def test_what_claude_did_is_appended_and_read_back(self, tmp_path: Path) -> None:
        deed = Deed("2026-09-16T10:00:00+00:00", "trello", "lire", "get_lists", True)
        accounts_file.record(tmp_path, deed)
        accounts_file.record(tmp_path, Deed("2026-09-16T10:01:00+00:00", "trello", "ecrire",
                                            "add_card_to_list", False))
        read = accounts_file.deeds(tmp_path)
        assert [d.tool for d in read] == ["get_lists", "add_card_to_list"]
        assert read[0] == deed

    def test_only_the_last_ones_are_read(self, tmp_path: Path) -> None:
        for number in range(5):
            accounts_file.record(tmp_path, Deed(f"t{number}", "trello", "lire", "get_lists", True))
        assert [d.at for d in accounts_file.deeds(tmp_path, last=2)] == ["t3", "t4"]

    def test_a_broken_line_does_not_stop_the_others(self, tmp_path: Path) -> None:
        accounts_file.record(tmp_path, Deed("t0", "trello", "lire", "get_lists", True))
        with accounts_file.journal_file(tmp_path).open("a") as stream:
            stream.write("{broken\n")
        accounts_file.record(tmp_path, Deed("t1", "trello", "lire", "get_lists", True))
        assert len(accounts_file.deeds(tmp_path)) == 2
        assert accounts_file.deeds(tmp_path / "nothing") == []


class TestTheServersForTheModel:
    def test_the_file_is_the_command_line_s_shape_and_the_owner_s_alone(
        self, tmp_path: Path
    ) -> None:
        servers = {"trello": {"command": "npx", "args": ["-y", "x"], "env": {"TRELLO_TOKEN": "t"}}}
        file = accounts_file.write_servers(tmp_path, servers)
        assert file is not None
        assert json.loads(file.read_text())["mcpServers"] == servers
        if os.name == "posix":
            assert stat.S_IMODE(file.stat().st_mode) == 0o600

    def test_no_server_means_no_file(self, tmp_path: Path) -> None:
        accounts_file.write_servers(tmp_path, {"a": {"command": "x", "args": []}})
        assert accounts_file.write_servers(tmp_path, {}) is None
        assert not (tmp_path / accounts_file.SERVERS).exists()


class TestSigningInByCode:
    def test_the_address_and_the_code_are_read_off_the_server_s_words(self, tmp_path, monkeypatch):
        script = tmp_path / "server"
        script.write_text(
            "#!/bin/sh\necho 'To sign in, use a web browser to open the page "
            "https://microsoft.com/devicelogin and enter the code ABCD1234 to authenticate.'\n"
            "exit 0\n"
        )
        script.chmod(0o755)
        shown = []
        service = MICROSOFT.__class__(
            key="microsoft", name="M", manner=MICROSOFT.manner, powers=MICROSOFT.powers,
            server=MICROSOFT.server.__class__(command=str(script), args=()),
        )
        assert accounts_file.sign_in(service, lambda url, code: shown.append((url, code)))
        assert shown == [("https://microsoft.com/devicelogin", "ABCD1234")]

    def test_a_missing_server_command_signs_nobody_in(self):
        service = MICROSOFT.__class__(
            key="microsoft", name="M", manner=MICROSOFT.manner, powers=MICROSOFT.powers,
            server=MICROSOFT.server.__class__(command="no-such-command-here", args=()),
        )
        assert not accounts_file.sign_in(service, lambda url, code: None)
        assert not accounts_file.signed_in(service)
