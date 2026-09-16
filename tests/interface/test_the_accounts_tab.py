"""The Comptes tab on the real window: consents ticked, accounts connected, deeds read."""

from __future__ import annotations

import pytest

from greffier.adapters import accounts_file
from greffier.domain.accounts import Deed
from greffier.domain.accounts_catalogue import CATALOGUE


@pytest.fixture
def own_files(tmp_path, monkeypatch):
    """The consents and the tokens in the test's own folder, never the machine's."""
    monkeypatch.setattr(accounts_file, "consents_file", lambda: tmp_path / "comptes.json")
    monkeypatch.setattr(accounts_file, "tokens_file", lambda: tmp_path / "jetons.toml")
    return tmp_path


class TestTheCards:
    def test_one_card_per_service_of_the_catalogue(self, own_files, window) -> None:
        tab = window.accounts
        assert set(tab.boxes) == {s.key for s in CATALOGUE}
        assert set(tab.states) == {s.key for s in CATALOGUE}

    def test_a_service_waiting_for_an_application_says_so_and_cannot_be_ticked(
        self, own_files, window
    ) -> None:
        tab = window.accounts
        assert tab.states["google"].cget("text") == window.says("comptes.attend_application")
        assert "google" not in tab.fields and "google" not in tab.codes

    def test_a_tick_is_a_consent_written_at_once(self, own_files, window) -> None:
        tab = window.accounts
        tab.boxes["trello"]["lire"].set(True)
        tab._consent_changed("trello")
        consents = accounts_file.read_consents()
        assert consents["trello"].powers == frozenset({"lire"})
        tab.boxes["trello"]["lire"].set(False)
        tab._consent_changed("trello")
        assert "trello" not in accounts_file.read_consents()


class TestConnectingByKey:
    def test_the_fields_pasted_make_the_account_connected(self, own_files, window) -> None:
        tab = window.accounts
        tab.fields["trello"]["cle"].insert(0, "k")
        tab.fields["trello"]["jeton"].insert(0, "t")
        tab._connect_by_token("trello")
        assert tab.states["trello"].cget("text") == window.says("comptes.connecte")
        assert accounts_file.secrets_of(next(s for s in CATALOGUE if s.key == "trello")) == {
            "cle": "k", "jeton": "t"}

    def test_a_field_missing_connects_nothing(self, own_files, window) -> None:
        tab = window.accounts
        tab.fields["trello"]["cle"].insert(0, "k")
        tab._connect_by_token("trello")
        assert tab.states["trello"].cget("text") == window.says("comptes.non_connecte")
        assert tab.word.cget("text") == window.says("comptes.champ_manquant")

    def test_disconnecting_forgets_the_secrets_and_the_consent(self, own_files, window) -> None:
        tab = window.accounts
        tab.fields["gitlab"]["adresse"].insert(0, "https://gitlab.x")
        tab.fields["gitlab"]["jeton"].insert(0, "glpat")
        tab._connect_by_token("gitlab")
        tab.boxes["gitlab"]["lire"].set(True)
        tab._consent_changed("gitlab")
        tab._disconnect("gitlab")
        assert tab.states["gitlab"].cget("text") == window.says("comptes.non_connecte")
        assert "gitlab" not in accounts_file.read_consents()
        assert tab.fields["gitlab"]["jeton"].get() == ""
        assert not tab.boxes["gitlab"]["lire"].get()

    def test_the_key_page_needs_the_address_when_it_is_built_from_it(
        self, own_files, window, monkeypatch
    ) -> None:
        opened = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
        tab = window.accounts
        tab._open_the_key_page("gitlab")
        assert opened == [] and tab.word.cget("text") == window.says("comptes.adresse_d_abord")
        tab.fields["gitlab"]["adresse"].insert(0, "https://gitlab.x")
        tab._open_the_key_page("gitlab")
        assert opened == ["https://gitlab.x/-/user_settings/personal_access_tokens"]


class TestTheJournal:
    def test_what_she_did_reads_as_sentences_latest_first(self, own_files, window) -> None:
        data = window.config.paths.data
        accounts_file.record(data, Deed("2026-09-16T10:00:00+00:00", "trello", "lire",
                                        "get_lists", True))
        accounts_file.record(data, Deed("2026-09-16T10:05:00+00:00", "microsoft",
                                        "ecrire_agenda", "create-calendar-event", False))
        window.accounts._say_the_journal()
        lines = window.accounts.journal.cget("text").splitlines()
        assert lines[0].startswith("10:05")
        assert window.says("comptes.fait_ecrire_agenda") in lines[0]
        assert window.config.assistant.name in lines[0]
        assert window.says("comptes.fait_lire", service="Trello") in lines[1]

    def test_nothing_done_yet_says_so(self, own_files, window) -> None:
        window.accounts._say_the_journal()
        assert window.accounts.journal.cget("text") == window.says("comptes.journal_vide")
