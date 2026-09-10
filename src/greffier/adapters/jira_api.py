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
AU_PLUS = 20

class JiraRefused(RuntimeError):
    """The call did not happen, and for a reason worth showing."""

@dataclass(frozen=True, slots=True)
class Request:
    """A Jira issue, reduced to what it takes to talk about it."""

    key: str
    title: str
    state: str
    adresse: str
    assigne: str = ""

    def say(self) -> str:
        qui = f" — {self.assigne}" if self.assigne else ""
        return f"{self.key} {self.title}{qui} ({self.state})"

def _identifiers(token: str) -> tuple[str, str]:
    """The email and token pair, from the single secret."""
    if ":" not in token:
        raise JiraRefused(
            "le secret Jira doit valoir « adresse@exemple.fr:jeton » : "
            "l'authentification Basic demande les deux"
        )
    adresse, _, brut = token.partition(":")
    return (adresse.strip(), brut.strip())

def _appeler(
    source: Source, token: str, path: str, methode: str = "GET",
    corps: dict[str, Any] | None = None,
) -> object:
    adresse, secret = _identifiers(token)
    autorisation = base64.b64encode(f"{adresse}:{secret}".encode()).decode()
    requete = urllib.request.Request(
        f"{source.adresse}/rest/api/3{path}",
        method=methode,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": f"Basic {autorisation}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=TIMEOUT) as response:
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
        raise JiraRefused(f"{source.adresse} est injoignable : {trouble}") from trouble
    except (ValueError, OSError) as trouble:
        raise JiraRefused(str(trouble)) from trouble

def _as_request(source: Source, brut: dict[str, Any]) -> Request:
    champs = brut.get("fields") or {}
    assigne = (champs.get("assignee") or {}).get("displayName", "") or ""
    state = ((champs.get("status") or {}).get("name", "")) or ""
    key = str(brut.get("key", ""))
    return Request(
        key=key,
        title=str(champs.get("summary", "")).strip(),
        state=state,
        adresse=f"{source.adresse}/browse/{key}",
        assigne=assigne,
    )

def requests(source: Source, token: str, ouvertes: bool = True) -> list[Request]:
    """The registered project's issues. Read only."""
    jql = f'project = "{source.projet}"'
    if ouvertes:
        jql += " AND statusCategory != Done"
    jql += " ORDER BY updated DESC"
    parametres = urllib.parse.urlencode({
        "jql": jql, "maxResults": str(AU_PLUS),
        "fields": "summary,status,assignee",
    })
    rendered = _appeler(source, token, f"/search/jql?{parametres}")
    if not isinstance(rendered, dict):
        raise JiraRefused("réponse inattendue de Jira")
    trouvees = rendered.get("issues", [])
    return [
        _as_request(source, brut) for brut in trouvees if isinstance(brut, dict)
    ]

def creer_une_demande(
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
            "project": {"key": source.projet},
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
    rendered = _appeler(source, token, "/issue", "POST", corps)
    if not isinstance(rendered, dict) or not rendered.get("key"):
        raise JiraRefused("Jira n'a pas rendu la demande créée")
    key = str(rendered["key"])
    return Request(key, title.strip(), "créée", f"{source.adresse}/browse/{key}")
