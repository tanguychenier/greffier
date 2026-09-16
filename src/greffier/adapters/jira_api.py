"""Reading and writing on a Jira registered in the source registry."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from greffier.domain.sources import Source

TIMEOUT = 15.0
AT_MOST = 20

class JiraRefused(RuntimeError):
    """The call did not happen, and for a reason worth showing."""

@dataclass(frozen=True, slots=True)
class Request:
    """A Jira issue, reduced to what it takes to talk about it."""

    key: str
    title: str
    state: str
    address: str
    assignee: str = ""

    def say(self) -> str:
        who = f", {self.assignee}" if self.assignee else ""
        return f"{self.key} {self.title}{who} ({self.state})"

def _identifiers(token: str) -> tuple[str, str]:
    """The email and token pair, from the single secret."""
    if ":" not in token:
        raise JiraRefused(
            "le secret Jira doit valoir « adresse@exemple.fr:jeton » : "
            "l'authentification Basic demande les deux"
        )
    address, _, brut = token.partition(":")
    return (address.strip(), brut.strip())

def _call(
    source: Source, token: str, path: str, http_method: str = "GET",
    corps: dict[str, Any] | None = None,
) -> object:
    address, secret = _identifiers(token)
    authorisation = base64.b64encode(f"{address}:{secret}".encode()).decode()
    the_request = urllib.request.Request(
        f"{source.address}/rest/api/3{path}",
        method=http_method,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": f"Basic {authorisation}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(the_request, timeout=TIMEOUT) as response:
            brut = response.read().decode("utf-8")
            return json.loads(brut) if brut.strip() else {}
    except urllib.error.HTTPError as trouble:
        detail = trouble.read().decode("utf-8", "replace")[:200]
        if trouble.code in (401, 403):
            raise JiraRefused(
                f"identifiants refusés sur « {source.name} » ({trouble.code}). "
                "Vérifie l'adresse du compte et le jeton."
            ) from trouble
        raise JiraRefused(f"Jira a répondu {trouble.code} : {detail}") from trouble
    except (urllib.error.URLError, TimeoutError) as trouble:
        raise JiraRefused(f"{source.address} est injoignable : {trouble}") from trouble
    except (ValueError, OSError) as trouble:
        raise JiraRefused(str(trouble)) from trouble

def _as_request(source: Source, brut: dict[str, Any]) -> Request:
    champs = brut.get("fields") or {}
    assignee = (champs.get("assignee") or {}).get("displayName", "") or ""
    state = ((champs.get("status") or {}).get("name", "")) or ""
    key = str(brut.get("key", ""))
    return Request(
        key=key,
        title=str(champs.get("summary", "")).strip(),
        state=state,
        address=f"{source.address}/browse/{key}",
        assignee=assignee,
    )

def requests(source: Source, token: str, open_ones: bool = True) -> list[Request]:
    """The registered project's issues. Read only."""
    jql = f'project = "{source.project}"'
    if open_ones:
        jql += " AND statusCategory != Done"
    jql += " ORDER BY updated DESC"
    parameters = urllib.parse.urlencode({
        "jql": jql, "maxResults": str(AT_MOST),
        "fields": "summary,status,assignee",
    })
    rendered = _call(source, token, f"/search/jql?{parameters}")
    if not isinstance(rendered, dict):
        raise JiraRefused("réponse inattendue de Jira")
    found = rendered.get("issues", [])
    return [
        _as_request(source, brut) for brut in found if isinstance(brut, dict)
    ]

def create_a_request(
    source: Source, token: str, title: str, description: str = "",
    kind: str = "Task",
) -> Request:
    """Creates an issue. **The caller must have confirmed.**"""
    if not source.can_write:
        raise JiraRefused(
            f"« {source.name} » est en lecture seule : rien n'a été créé"
        )
    if not title.strip():
        raise JiraRefused("une demande sans titre ne sert à personne")
    corps = {
        "fields": {
            "project": {"key": source.project},
            "summary": title.strip(),
            "issuetype": {"name": kind},
        }
    }
    if description.strip():
        corps["fields"]["description"] = {
            "type": "doc", "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": description}],
            }],
        }
    rendered = _call(source, token, "/issue", "POST", corps)
    if not isinstance(rendered, dict) or not rendered.get("key"):
        raise JiraRefused("Jira n'a pas rendu la demande créée")
    key = str(rendered["key"])
    return Request(key, title.strip(), "créée", f"{source.address}/browse/{key}")
