"""Reading and writing on a GitLab registered in the source registry.

What is not registered does not exist, and writing always needs the caller to
have confirmed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from greffier.domain.sources import Source

TIMEOUT = 15.0

AT_MOST = 20

class GitLabRefused(RuntimeError):
    """The call did not happen, and for a reason worth showing."""

@dataclass(frozen=True, slots=True)
class Ticket:
    """A ticket, reduced to what it takes to talk about it."""

    number: int
    title: str
    state: str
    adresse: str
    assigne: str = ""
    etiquettes: tuple[str, ...] = ()

    def say(self) -> str:
        who = f", {self.assigne}" if self.assigne else ""
        marques = f" [{', '.join(self.etiquettes)}]" if self.etiquettes else ""
        return f"#{self.number} {self.title}{who}{marques} ({self.state})"

def _appeler(
    source: Source, token: str, path: str, methode: str = "GET",
    corps: dict[str, Any] | None = None,
) -> object:
    project = urllib.parse.quote(source.project, safe="")
    requete = urllib.request.Request(
        f"{source.adresse}/api/v4/projects/{project}{path}",
        method=methode,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "PRIVATE-TOKEN": token,
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
            raise GitLabRefused(
                f"jeton refusé sur « {source.name} » ({trouble.code}). Vérifie sa "
                "portée : lire les tickets demande « read_api », en créer "
                "demande « api »."
            ) from trouble
        if trouble.code == 404:
            raise GitLabRefused(
                f"projet « {source.project} » introuvable sur {source.adresse}. "
                "Un projet privé invisible du jeton rend aussi 404."
            ) from trouble
        raise GitLabRefused(f"GitLab a répondu {trouble.code} : {detail}") from trouble
    except (urllib.error.URLError, TimeoutError) as trouble:
        raise GitLabRefused(f"{source.adresse} est injoignable : {trouble}") from trouble
    except (ValueError, OSError) as trouble:
        raise GitLabRefused(str(trouble)) from trouble

def _as_ticket(brut: dict[str, Any]) -> Ticket:
    assigne = (brut.get("assignee") or {}).get("name", "") or ""
    return Ticket(
        number=int(brut.get("iid", 0)),
        title=str(brut.get("title", "")).strip(),
        state=str(brut.get("state", "")),
        adresse=str(brut.get("web_url", "")),
        assigne=assigne,
        etiquettes=tuple(str(x) for x in brut.get("labels", [])),
    )

def tickets(
    source: Source, token: str, ouverts: bool = True, cherche: str = ""
) -> list[Ticket]:
    """The registered project's tickets. Read only."""
    parametres = {"per_page": str(AT_MOST), "order_by": "updated_at"}
    if ouverts:
        parametres["state"] = "opened"
    if cherche.strip():
        parametres["search"] = cherche.strip()
    rendered = _appeler(source, token, f"/issues?{urllib.parse.urlencode(parametres)}")
    if not isinstance(rendered, list):
        raise GitLabRefused("réponse inattendue de GitLab")
    return [_as_ticket(brut) for brut in rendered if isinstance(brut, dict)]

def join_requests(source: Source, token: str, ouvertes: bool = True) -> list[Ticket]:
    """The merge requests, presented as tickets."""
    parametres = {"per_page": str(AT_MOST), "order_by": "updated_at"}
    if ouvertes:
        parametres["state"] = "opened"
    rendered = _appeler(
        source, token, f"/merge_requests?{urllib.parse.urlencode(parametres)}"
    )
    if not isinstance(rendered, list):
        raise GitLabRefused("réponse inattendue de GitLab")
    return [_as_ticket(brut) for brut in rendered if isinstance(brut, dict)]

def create_a_ticket(
    source: Source, token: str, title: str, description: str = ""
) -> Ticket:
    """Creates a ticket. **The caller must have confirmed.**"""
    if not source.can_write:
        raise GitLabRefused(
            f"« {source.name} » est en lecture seule : aucun ticket n'a été créé"
        )
    if not title.strip():
        raise GitLabRefused("un ticket sans titre ne sert à personne")
    rendered = _appeler(
        source, token, "/issues", "POST",
        {"title": title.strip(), "description": description},
    )
    if not isinstance(rendered, dict) or not rendered.get("iid"):
        raise GitLabRefused("GitLab n'a pas rendu le ticket créé")
    return _as_ticket(rendered)

def comment(source: Source, token: str, number: int, text: str) -> str:
    """Adds a comment to a ticket. Returns its address."""
    if not source.can_write:
        raise GitLabRefused(f"« {source.name} » est en lecture seule")
    if not text.strip():
        raise GitLabRefused("un commentaire vide n'apporte rien")
    rendered = _appeler(
        source, token, f"/issues/{number}/notes", "POST", {"body": text}
    )
    if not isinstance(rendered, dict):
        raise GitLabRefused("réponse inattendue de GitLab")
    return f"{source.adresse}/{source.project}/-/issues/{number}"
