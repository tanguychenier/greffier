"""Where the connected accounts live on disk, and how one is signed into.

Three files, all the person's own. The consents, in the configuration
folder next to the settings. The secrets, in the tokens file the window
already writes, readable by the owner alone. The journal of what Claude
did with the accounts, in the data folder next to the meetings. And one
more written for the model on every start, the list of tool servers it
may open, secrets included, so it is owner-only too.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from greffier.adapters.sources_file import store_token, stored_tokens, tokens_file
from greffier.domain.accounts import Consent, Deed, Service, now_iso
from greffier.locations import config_folder

CONSENTS = "comptes.json"
JOURNAL = "comptes-journal.jsonl"
SERVERS = "outils-du-modele.json"

#: How a secret is named in the tokens file, « compte-<service>-<field> »;
#: no dot in it, a dot being a table in that file's syntax.
SECRET_PREFIX = "compte-"

#: What the sign-in by code prints, on the line that carries the address and the code.
DEVICE_CODE = re.compile(r"(https?://\S+).*?\b([A-Z0-9]{6,12})\b")


def consents_file() -> Path:
    return config_folder() / CONSENTS


def read_consents(file: Path | None = None) -> dict[str, Consent]:
    file = file or consents_file()
    if not file.exists():
        return {}
    try:
        content = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    found: dict[str, Consent] = {}
    for key, entry in (content.get("consents") or {}).items():
        if isinstance(entry, dict):
            found[str(key)] = Consent(
                str(key), frozenset(str(p) for p in entry.get("powers", [])),
                str(entry.get("given_at", "")),
            )
    return found


def write_consent(consent: Consent, file: Path | None = None) -> None:
    """Keeps one service's consent; an empty one takes the service out."""
    file = file or consents_file()
    kept = read_consents(file)
    if consent.empty:
        kept.pop(consent.service, None)
    else:
        kept[consent.service] = consent if consent.given_at else Consent(
            consent.service, consent.powers, now_iso())
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"consents": {
        key: {"powers": sorted(c.powers), "given_at": c.given_at} for key, c in kept.items()
    }}, ensure_ascii=False, indent=1), encoding="utf-8")


def secrets_of(service: Service, file: Path | None = None) -> dict[str, str]:
    """The fields the person filled for this service, from the tokens file."""
    kept = stored_tokens(file or tokens_file())
    return {
        field: kept[f"{SECRET_PREFIX}{service.key}-{field}"]
        for field in service.fields
        if kept.get(f"{SECRET_PREFIX}{service.key}-{field}")
    }


def all_secrets(services: list[Service], file: Path | None = None) -> dict[str, dict[str, str]]:
    return {s.key: secrets_of(s, file) for s in services}


def store_secrets(service: Service, values: dict[str, str], file: Path | None = None) -> None:
    file = file or tokens_file()
    for field in service.fields:
        store_token(file, f"{SECRET_PREFIX}{service.key}-{field}", values.get(field, ""))


def forget_secrets(service: Service, file: Path | None = None) -> None:
    store_secrets(service, {}, file)


def connected(service: Service, file: Path | None = None) -> bool:
    """Whether the account is there: every field filled, or signed in by code."""
    if service.fields:
        return all(secrets_of(service, file).get(f) for f in service.fields)
    if service.manner.value == "code":
        return signed_in(service)
    return False


def journal_file(data: Path) -> Path:
    return data / JOURNAL


def record(data: Path, deed: Deed) -> None:
    file = journal_file(data)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(deed), ensure_ascii=False) + "\n")


def deeds(data: Path, last: int = 50) -> list[Deed]:
    file = journal_file(data)
    if not file.exists():
        return []
    found: list[Deed] = []
    with contextlib.suppress(OSError):
        for line in file.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError, TypeError, KeyError):
                entry = json.loads(line)
                found.append(Deed(entry["at"], entry["service"], entry["power"],
                                  entry["tool"], bool(entry["reading"])))
    return found[-last:]


def write_servers(data: Path, servers: dict[str, dict[str, object]]) -> Path | None:
    """The tool servers for the model's command line, or nothing when there are none."""
    file = data / SERVERS
    if not servers:
        file.unlink(missing_ok=True)
        return None
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"mcpServers": servers}, indent=1), encoding="utf-8")
    if os.name == "posix":
        file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return file


def signed_in(service: Service) -> bool:
    """Whether the sign-in by code holds, asked of the server itself."""
    if shutil.which(service.server.command) is None:
        return False
    try:
        done = subprocess.run(
            [service.server.command, *service.server.args, "--verify-login"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and "not" not in done.stdout.lower()[:200]


def sign_in(service: Service, show: Callable[[str, str], None], timeout: float = 300.0) -> bool:
    """Signs into a service by code, telling the person where to go and what to type.

    The server prints an address and a code; `show` gets both the moment
    they appear, the person signs in from her browser, and the server
    ends when she has. True once it did.
    """
    if shutil.which(service.server.command) is None:
        return False
    try:
        process = subprocess.Popen(
            [service.server.command, *service.server.args, "--login"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError:
        return False
    shown = False
    try:
        for line in process.stdout or ():
            found = DEVICE_CODE.search(line) if not shown else None
            if found:
                shown = True
                show(found.group(1), found.group(2))
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return False
    return process.returncode == 0

