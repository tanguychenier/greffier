"""The accounts a person connects, what Claude may do with them, and what he did."""

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from greffier.domain.accounts import (
    TOOL_PREFIX,
    Consent,
    Manner,
    Power,
    Server,
    Service,
    allowed_tools,
    deed_of,
    guidance_for,
    now_iso,
    servers_to_start,
)
from greffier.domain.accounts_catalogue import (
    CATALOGUE,
    GITLAB,
    GOOGLE,
    MICROSOFT,
    TRELLO,
    service,
)

A_MOMENT = "2026-09-16T10:00:00+00:00"


def _odd_service(power: Power, env: dict[str, str] | None = None) -> Service:
    """A service the catalogue does not carry, to reach what the real ones never do."""
    return Service(
        key="bizarre", name="Bizarre", manner=Manner.DEVICE, powers=(power,),
        server=Server(command="npx", args=(), env=env or {}),
    )


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

    def test_a_power_is_found_by_its_key_with_its_tools(self):
        reading = TRELLO.power("lire")
        assert reading is not None
        assert reading.key == "lire" and reading.reading
        assert "list_boards" in reading.tools

    def test_a_power_nobody_declared_is_nothing(self):
        assert TRELLO.power("supprimer") is None

    def test_a_service_nobody_declared_is_nothing(self):
        assert service("inconnu") is None


class TestWhatTheModelMayRun:
    def test_only_the_ticked_powers_are_handed_over(self):
        consents = {"trello": Consent("trello", frozenset({"lire"}))}
        tools = allowed_tools(consents, CATALOGUE)
        assert f"{TOOL_PREFIX}trello__get_lists" in tools
        assert f"{TOOL_PREFIX}trello__add_card_to_list" not in tools
        assert not any(tool.startswith(f"{TOOL_PREFIX}gitlab") for tool in tools)

    def test_an_empty_consent_hands_nothing_over(self):
        assert allowed_tools({"trello": Consent("trello", frozenset())}, CATALOGUE) == []

    def test_every_consented_account_is_handed_over_whatever_lies_between_them(self):
        # Trello opens the catalogue and Microsoft comes after GitLab and
        # Jira, which have no consent here: skipping one must not end the walk.
        consents = {
            "trello": Consent("trello", frozenset({"lire"})),
            "microsoft": Consent("microsoft", frozenset({"lire_agenda"})),
        }
        tools = allowed_tools(consents, CATALOGUE)
        assert f"{TOOL_PREFIX}trello__list_boards" in tools
        assert f"{TOOL_PREFIX}microsoft__list-calendars" in tools

    @given(ticked=st.frozensets(st.sampled_from([p.key for p in MICROSOFT.powers])))
    def test_every_tool_handed_over_reads_back_as_a_ticked_power(self, ticked):
        # The round trip that holds the rule together: what allowed_tools hands
        # the model, deed_of must read back as one of the powers the person
        # ticked, and nothing else must come with it.
        tools = allowed_tools({"microsoft": Consent("microsoft", ticked)}, CATALOGUE)
        deeds = [deed_of(tool, CATALOGUE, at=A_MOMENT) for tool in tools]
        assert all(deed is not None and deed.power in ticked for deed in deeds)
        assert len(tools) == sum(len(p.tools) for p in MICROSOFT.powers if p.key in ticked)


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

    def test_a_blank_field_is_a_missing_account(self):
        # A token pasted as nothing would start a server that answers 401 to
        # every call; the person must be told the account is not there.
        consents = {"gitlab": Consent("gitlab", frozenset({"lire"}))}
        secrets = {"gitlab": {"adresse": "https://gitlab.exemple.fr", "jeton": ""}}
        assert servers_to_start(consents, CATALOGUE, secrets) == {}

    def test_an_account_left_out_does_not_stop_the_ones_after_it(self):
        # GitLab comes before Microsoft in the catalogue and has no secrets here.
        consents = {
            "gitlab": Consent("gitlab", frozenset({"lire"})),
            "microsoft": Consent("microsoft", frozenset({"lire_agenda"})),
        }
        assert list(servers_to_start(consents, CATALOGUE, {})) == ["microsoft"]

    def test_a_service_waiting_for_an_application_does_not_stop_the_ones_after_it(self):
        consents = {
            "google": Consent("google", frozenset({"lire_agenda"})),
            "microsoft": Consent("microsoft", frozenset({"lire_agenda"})),
        }
        assert list(servers_to_start(consents, [GOOGLE, MICROSOFT], {})) == ["microsoft"]

    def test_a_recipe_asking_for_a_field_the_account_never_had_is_left_out(self):
        # The catalogue declares the fields a recipe reads; one that reads a
        # field nobody fills in must not take the other accounts down with it.
        odd = _odd_service(Power("lire", True, ("x",)), env={"CLE": "{absente}"})
        consents = {
            "bizarre": Consent("bizarre", frozenset({"lire"})),
            "microsoft": Consent("microsoft", frozenset({"lire_agenda"})),
        }
        assert list(servers_to_start(consents, [odd, MICROSOFT], {})) == ["microsoft"]

    def test_manners(self):
        assert GITLAB.manner is Manner.TOKEN and MICROSOFT.manner is Manner.DEVICE


class TestWhatADeedMeans:
    def test_a_tool_of_an_account_is_read_back_as_a_power(self):
        deed = deed_of(f"{TOOL_PREFIX}microsoft__list-calendar-events", CATALOGUE, at=A_MOMENT)
        assert deed is not None
        assert (deed.service, deed.power, deed.reading) == ("microsoft", "lire_agenda", True)
        assert deed.tool == "list-calendar-events"
        assert deed.at == A_MOMENT

    def test_a_writing_tool_says_so(self):
        deed = deed_of(f"{TOOL_PREFIX}trello__add_card_to_list", CATALOGUE)
        assert deed is not None and not deed.reading and deed.at

    def test_the_model_s_own_tools_are_not_deeds(self):
        assert deed_of("WebSearch", CATALOGUE) is None
        assert deed_of(f"{TOOL_PREFIX}nobody__x", CATALOGUE) is None
        assert deed_of(f"{TOOL_PREFIX}trello__delete_comment", CATALOGUE) is None

    def test_a_deed_without_a_given_moment_is_stamped_now(self):
        deed = deed_of(f"{TOOL_PREFIX}trello__add_card_to_list", CATALOGUE)
        assert deed is not None
        stamped = datetime.fromisoformat(deed.at)
        assert abs((datetime.now(UTC) - stamped).total_seconds()) < 60

    def test_the_first_double_underscore_separates_the_service_from_its_tool(self):
        # Nothing forbids a server from naming a tool with a double underscore
        # of its own; the service is still the first segment, and the deed
        # keeps the tool's whole name.
        odd = _odd_service(Power("lire", True, ("get__card",)))
        deed = deed_of(f"{TOOL_PREFIX}bizarre__get__card", [odd], at=A_MOMENT)
        assert deed is not None
        assert (deed.service, deed.tool) == ("bizarre", "get__card")


class TestTheMomentOfADeed:
    def test_it_is_utc_to_the_second(self):
        # Deeds are read back by a person and compared across machines: a
        # local time without its offset, or microseconds, would make two
        # readings of the same deed disagree.
        moment = datetime.fromisoformat(now_iso())
        assert moment.utcoffset() == timedelta(0)
        assert moment.microsecond == 0
        assert abs((datetime.now(UTC) - moment).total_seconds()) < 60


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

    def test_the_whole_of_what_she_is_told(self):
        # Word for word: this is the rule she is held to, and a sentence with a
        # word missing is a rule that no longer says it.
        consents = {
            "trello": Consent("trello", frozenset({"lire"})),
            "microsoft": Consent("microsoft", frozenset({"lire_agenda", "preparer_courriel"})),
        }
        assert guidance_for(consents, CATALOGUE) == (
            "Comptes connectés, avec ce que la personne t'a autorisé à y faire :\n"
            "- Trello : lire.\n"
            "- Microsoft 365 (Outlook, agenda, tâches) : lire l'agenda, "
            "préparer des brouillons de courriel (jamais les envoyer).\n"
            "Tu t'en sers par leurs outils quand la question le demande, et rien de "
            "plus : ce qui n'est pas listé t'est interdit, et tu ne supprimes ni "
            "n'envoies jamais rien. Chaque fois que tu t'en sers, dis-le en une "
            "phrase, « j'ai lu ton agenda de jeudi », « j'ai créé la carte Trello ».\n"
        )

    def test_the_powers_of_one_account_are_listed_in_the_catalogue_s_order(self):
        consents = {"trello": Consent("trello", frozenset({"ecrire", "lire"}))}
        assert (
            "- Trello : lire, écrire (créer, commenter, déplacer, jamais supprimer).\n"
            in guidance_for(consents, CATALOGUE)
        )

    def test_a_power_without_words_is_named_by_its_key(self):
        # The catalogue may grow faster than the words: a bare key still says
        # more than nothing, and never shows as « None ».
        odd = _odd_service(Power("chanter", False, ("sing",)))
        words = guidance_for({"bizarre": Consent("bizarre", frozenset({"chanter"}))}, [odd])
        assert "- Bizarre : chanter.\n" in words
