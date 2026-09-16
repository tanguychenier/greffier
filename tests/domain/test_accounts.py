"""The accounts a person connects, what Claude may do with them, and what he did."""

from greffier.domain.accounts import (
    TOOL_PREFIX,
    Consent,
    Manner,
    allowed_tools,
    deed_of,
    guidance_for,
    servers_to_start,
)
from greffier.domain.accounts_catalogue import CATALOGUE, GITLAB, MICROSOFT, TRELLO, service


class TestTheCatalogue:
    def test_every_service_has_a_key_a_name_and_powers(self):
        for one in CATALOGUE:
            assert one.key and one.name and one.powers, one.key
            assert len({p.key for p in one.powers}) == len(one.powers)

    def test_no_tool_deletes_sends_or_shares(self):
        # The person sends and deletes herself.
        for one in CATALOGUE:
            for power in one.powers:
                for tool in power.tools:
                    lowered = tool.lower()
                    assert not any(word in lowered for word in (
                        "delete", "archive", "send", "share", "remove", "cancel", "repair",
                    )), f"{one.key} {tool}"

    def test_a_reading_power_never_carries_a_writing_tool(self):
        for one in CATALOGUE:
            for power in one.powers:
                if power.reading:
                    assert not any(
                        tool.split("_")[0] in ("create", "add", "update", "move")
                        or tool.split("-")[0] in ("create", "add", "update", "move")
                        for tool in power.tools
                    ), f"{one.key} {power.key}"

    def test_a_service_waiting_for_an_application_cannot_be_connected(self):
        assert not service("google").connectable
        assert TRELLO.connectable and MICROSOFT.connectable

    def test_the_tools_are_named_the_way_the_model_sees_them(self):
        assert TRELLO.tools_of(frozenset({"lire"}))[0] == f"{TOOL_PREFIX}trello__list_boards"
        assert TRELLO.tools_of(frozenset()) == []


class TestWhatTheModelMayRun:
    def test_only_the_ticked_powers_are_handed_over(self):
        consents = {"trello": Consent("trello", frozenset({"lire"}))}
        tools = allowed_tools(consents, CATALOGUE)
        assert f"{TOOL_PREFIX}trello__get_lists" in tools
        assert f"{TOOL_PREFIX}trello__add_card_to_list" not in tools
        assert not any(tool.startswith(f"{TOOL_PREFIX}gitlab") for tool in tools)

    def test_an_empty_consent_hands_nothing_over(self):
        assert allowed_tools({"trello": Consent("trello", frozenset())}, CATALOGUE) == []


class TestTheServersToStart:
    def test_a_connected_service_with_a_consent_starts_with_its_secrets(self):
        consents = {"gitlab": Consent("gitlab", frozenset({"lire"}))}
        secrets = {"gitlab": {"adresse": "https://gitlab.exemple.fr", "jeton": "glpat-x"}}
        started = servers_to_start(consents, CATALOGUE, secrets)
        assert started == {"gitlab": {
            "command": "npx", "args": ["-y", "@zereight/mcp-gitlab"],
            "env": {"GITLAB_API_URL": "https://gitlab.exemple.fr/api/v4",
                    "GITLAB_PERSONAL_ACCESS_TOKEN": "glpat-x"},
        }}

    def test_a_consent_without_the_account_behind_it_starts_nothing(self):
        consents = {"gitlab": Consent("gitlab", frozenset({"lire"}))}
        assert servers_to_start(consents, CATALOGUE, {}) == {}
        assert servers_to_start(consents, CATALOGUE, {"gitlab": {"adresse": "https://x"}}) == {}

    def test_a_service_signed_in_by_code_starts_without_a_secret(self):
        consents = {"microsoft": Consent("microsoft", frozenset({"lire_agenda"}))}
        started = servers_to_start(consents, CATALOGUE, {})
        assert started["microsoft"]["command"] == "npx"
        assert "env" not in started["microsoft"]

    def test_a_service_waiting_for_an_application_never_starts(self):
        consents = {"google": Consent("google", frozenset({"lire_agenda"}))}
        assert servers_to_start(consents, CATALOGUE, {}) == {}

    def test_manners(self):
        assert GITLAB.manner is Manner.TOKEN and MICROSOFT.manner is Manner.DEVICE


class TestWhatADeedMeans:
    def test_a_tool_of_an_account_is_read_back_as_a_power(self):
        deed = deed_of(f"{TOOL_PREFIX}microsoft__list-calendar-events", CATALOGUE,
                       at="2026-09-16T10:00:00+00:00")
        assert deed is not None
        assert (deed.service, deed.power, deed.reading) == ("microsoft", "lire_agenda", True)
        assert deed.at == "2026-09-16T10:00:00+00:00"

    def test_a_writing_tool_says_so(self):
        deed = deed_of(f"{TOOL_PREFIX}trello__add_card_to_list", CATALOGUE)
        assert deed is not None and not deed.reading and deed.at

    def test_the_model_s_own_tools_are_not_deeds(self):
        assert deed_of("WebSearch", CATALOGUE) is None
        assert deed_of(f"{TOOL_PREFIX}nobody__x", CATALOGUE) is None
        assert deed_of(f"{TOOL_PREFIX}trello__delete_comment", CATALOGUE) is None


class TestWhatSheIsTold:
    def test_the_accounts_and_their_powers_in_her_own_words(self):
        consents = {
            "trello": Consent("trello", frozenset({"lire"})),
            "microsoft": Consent("microsoft", frozenset({"lire_agenda", "preparer_courriel"})),
        }
        words = guidance_for(consents, CATALOGUE)
        assert "Trello : lire." in words
        assert "lire l'agenda" in words and "brouillons" in words
        assert "jamais" in words and "dis-le" in words

    def test_nothing_consented_means_nothing_said(self):
        assert guidance_for({}, CATALOGUE) == ""
        assert guidance_for({"trello": Consent("trello", frozenset())}, CATALOGUE) == ""
