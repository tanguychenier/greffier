"""The accounts a person connects, what Claude may do with them, and what he did.

Nothing here talks to a service. A service is a recipe for a tool server
and a list of powers, each power a handful of that server's tools; a
consent is the powers a person ticked for one service; a deed is one
thing Claude did with an account, kept so that the person can read it.
What is not in the catalogue does not exist, and no tool outside the
ticked powers is ever handed to the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

#: What a tool of a connected account is called on the model's side:
#: « mcp__<service>__<tool> ».
TOOL_PREFIX = "mcp__"


class Manner(StrEnum):
    """How an account gets connected."""

    TOKEN = "jeton"                # the person pastes a key from the service
    DEVICE = "code"                # the service shows a code, the person signs in
    APPLICATION = "application"    # waits for an application Tansoftware declares


@dataclass(frozen=True, slots=True)
class Power:
    """One thing Claude may do with an account, and the tools behind it."""

    key: str
    reading: bool
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Server:
    """The tool server recipe: a command, its arguments, the secrets it reads."""

    command: str
    args: tuple[str, ...]
    #: Environment variable → what it carries, written with the account's
    #: fields between braces, « {adresse}/api/v4 » for instance.
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Service:
    """A service of the catalogue."""

    key: str
    name: str
    manner: Manner
    powers: tuple[Power, ...]
    server: Server
    #: What the person fills in to connect, in order.
    fields: tuple[str, ...] = ()
    #: Where the person gets the key, when there is one to get.
    key_page: str = ""

    def power(self, key: str) -> Power | None:
        return next((p for p in self.powers if p.key == key), None)

    def tools_of(self, powers: frozenset[str]) -> list[str]:
        """The model-side names of the tools the ticked powers allow."""
        return [
            f"{TOOL_PREFIX}{self.key}__{tool}"
            for power in self.powers if power.key in powers
            for tool in power.tools
        ]

    @property
    def connectable(self) -> bool:
        return self.manner is not Manner.APPLICATION


@dataclass(frozen=True, slots=True)
class Consent:
    """The powers a person ticked for one service, and when."""

    service: str
    powers: frozenset[str]
    given_at: str = ""

    @property
    def empty(self) -> bool:
        return not self.powers


@dataclass(frozen=True, slots=True)
class Deed:
    """One thing Claude did with an account."""

    at: str
    service: str
    power: str
    tool: str
    reading: bool


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def deed_of(tool_name: str, catalogue: list[Service], at: str = "") -> Deed | None:
    """What a tool the model called means, or nothing for a tool that is not an account's."""
    if not tool_name.startswith(TOOL_PREFIX):
        return None
    rest = tool_name[len(TOOL_PREFIX):]
    service_key, separator, tool = rest.partition("__")
    if not separator:
        return None
    service = next((s for s in catalogue if s.key == service_key), None)
    if service is None:
        return None
    for power in service.powers:
        if tool in power.tools:
            return Deed(at or now_iso(), service.key, power.key, tool, power.reading)
    return None


def allowed_tools(consents: dict[str, Consent], catalogue: list[Service]) -> list[str]:
    """Every tool the model may run, over all the accounts with a consent."""
    found: list[str] = []
    for service in catalogue:
        consent = consents.get(service.key)
        if consent is None or consent.empty:
            continue
        found.extend(service.tools_of(consent.powers))
    return found


def servers_to_start(
    consents: dict[str, Consent],
    catalogue: list[Service],
    secrets: dict[str, dict[str, str]],
) -> dict[str, dict[str, object]]:
    """The tool servers to hand the model, only those consented to and connected.

    The shape is the one the model's command line reads, one entry per
    service: the command, its arguments and the environment carrying the
    account's secrets. A service whose secrets are missing is left out,
    a consent being worth nothing without the account behind it.
    """
    started: dict[str, dict[str, object]] = {}
    for service in catalogue:
        consent = consents.get(service.key)
        if consent is None or consent.empty:
            continue
        known = secrets.get(service.key, {})
        if service.manner is Manner.TOKEN and any(not known.get(f) for f in service.fields):
            continue
        if service.manner is Manner.APPLICATION:
            continue
        try:
            env = {
                variable: template.format(**known)
                for variable, template in service.server.env.items()
            }
        except KeyError:
            continue
        started[service.key] = {
            "command": service.server.command,
            "args": list(service.server.args),
            **({"env": env} if env else {}),
        }
    return started


POWER_WORDS = {
    "lire": "lire",
    "ecrire": "écrire (créer, commenter, déplacer, jamais supprimer)",
    "lire_agenda": "lire l'agenda",
    "ecrire_agenda": "créer ou modifier des rendez-vous",
    "lire_courriel": "lire les courriels",
    "preparer_courriel": "préparer des brouillons de courriel (jamais les envoyer)",
    "taches": "lire et créer des tâches",
}


def guidance_for(consents: dict[str, Consent], catalogue: list[Service]) -> str:
    """What the assistant is told about the accounts, in the language she is spoken to.

    Only the accounts with a consent, only the powers ticked, and the rule
    that holds for all of them, saying what she did with them.
    """
    lines: list[str] = []
    for service in catalogue:
        consent = consents.get(service.key)
        if consent is None or consent.empty:
            continue
        powers = ", ".join(
            POWER_WORDS.get(power.key, power.key)
            for power in service.powers if power.key in consent.powers
        )
        lines.append(f"- {service.name} : {powers}.")
    if not lines:
        return ""
    return (
        "Comptes connectés, avec ce que la personne t'a autorisé à y faire :\n"
        + "\n".join(lines)
        + "\nTu t'en sers par leurs outils quand la question le demande, et rien de "
        "plus : ce qui n'est pas listé t'est interdit, et tu ne supprimes ni "
        "n'envoies jamais rien. Chaque fois que tu t'en sers, dis-le en une "
        "phrase, « j'ai lu ton agenda de jeudi », « j'ai créé la carte Trello ».\n"
    )
