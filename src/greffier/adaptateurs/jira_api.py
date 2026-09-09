"""Lire et écrire sur un Jira inscrit au registre des sources.

Même principe que pour GitLab : c'est Greffier qui appelle, sur intention
reconnue et après confirmation, jamais l'assistant avec un jeton en main.

Jira s'authentifie par courriel et jeton, en Basic : le jeton seul ne suffit
pas. Le courriel est celui du compte, et il est pris dans la même entrée que le
jeton, séparé par un « : » — de sorte qu'un seul secret est à déposer et que
l'adresse ne traîne pas dans un fichier de configuration.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from greffier.domaine.sources import Source

DELAI = 15.0
AU_PLUS = 20


class JiraRefuse(RuntimeError):
    """L'appel n'a pas eu lieu, et pour une raison présentable."""


@dataclass(frozen=True, slots=True)
class Demande:
    """Un ticket Jira, réduit à ce qui sert à en parler."""

    clef: str
    titre: str
    etat: str
    adresse: str
    assigne: str = ""

    def dire(self) -> str:
        qui = f" — {self.assigne}" if self.assigne else ""
        return f"{self.clef} {self.titre}{qui} ({self.etat})"


def _identifiants(jeton: str) -> tuple[str, str]:
    """Le couple courriel/jeton, depuis le secret unique déposé.

    Un seul secret à déposer plutôt que deux, et l'adresse du compte hors du
    fichier de configuration : elle identifie une personne.
    """
    if ":" not in jeton:
        raise JiraRefuse(
            "le secret Jira doit valoir « adresse@exemple.fr:jeton » : "
            "l'authentification Basic demande les deux"
        )
    adresse, _, brut = jeton.partition(":")
    return (adresse.strip(), brut.strip())


def _appeler(
    source: Source, jeton: str, chemin: str, methode: str = "GET",
    corps: dict[str, Any] | None = None,
) -> object:
    adresse, secret = _identifiants(jeton)
    autorisation = base64.b64encode(f"{adresse}:{secret}".encode()).decode()
    requete = urllib.request.Request(
        f"{source.adresse}/rest/api/3{chemin}",
        method=methode,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": f"Basic {autorisation}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=DELAI) as reponse:
            brut = reponse.read().decode("utf-8")
            return json.loads(brut) if brut.strip() else {}
    except urllib.error.HTTPError as souci:
        detail = souci.read().decode("utf-8", "replace")[:200]
        if souci.code in (401, 403):
            raise JiraRefuse(
                f"identifiants refusés sur « {source.nom} » ({souci.code}). "
                "Vérifie l'adresse du compte et le jeton."
            ) from souci
        raise JiraRefuse(f"Jira a répondu {souci.code} : {detail}") from souci
    except (urllib.error.URLError, TimeoutError) as souci:
        raise JiraRefuse(f"{source.adresse} est injoignable : {souci}") from souci
    except (ValueError, OSError) as souci:
        raise JiraRefuse(str(souci)) from souci


def _en_demande(source: Source, brut: dict[str, Any]) -> Demande:
    champs = brut.get("fields") or {}
    assigne = (champs.get("assignee") or {}).get("displayName", "") or ""
    etat = ((champs.get("status") or {}).get("name", "")) or ""
    clef = str(brut.get("key", ""))
    return Demande(
        clef=clef,
        titre=str(champs.get("summary", "")).strip(),
        etat=etat,
        adresse=f"{source.adresse}/browse/{clef}",
        assigne=assigne,
    )


def demandes(source: Source, jeton: str, ouvertes: bool = True) -> list[Demande]:
    """Les demandes du projet inscrit. Lecture seule, toujours permise."""
    jql = f'project = "{source.projet}"'
    if ouvertes:
        jql += " AND statusCategory != Done"
    jql += " ORDER BY updated DESC"
    parametres = urllib.parse.urlencode({
        "jql": jql, "maxResults": str(AU_PLUS),
        "fields": "summary,status,assignee",
    })
    rendu = _appeler(source, jeton, f"/search/jql?{parametres}")
    if not isinstance(rendu, dict):
        raise JiraRefuse("réponse inattendue de Jira")
    trouvees = rendu.get("issues", [])
    return [
        _en_demande(source, brut) for brut in trouvees if isinstance(brut, dict)
    ]


def creer_une_demande(
    source: Source, jeton: str, titre: str, description: str = "",
    genre: str = "Task",
) -> Demande:
    """Crée une demande. **L'appelant doit avoir confirmé.**"""
    if not source.peut_ecrire:
        raise JiraRefuse(
            f"« {source.nom} » est en lecture seule : rien n'a été créé"
        )
    if not titre.strip():
        raise JiraRefuse("une demande sans titre ne sert à personne")
    corps = {
        "fields": {
            "project": {"key": source.projet},
            "summary": titre.strip(),
            "issuetype": {"name": genre},
        }
    }
    if description.strip():
        # Jira attend le format « document » depuis l'API 3 : du texte brut y
        # est refusé, et l'erreur ne le dit pas clairement.
        corps["fields"]["description"] = {
            "type": "doc", "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": description}],
            }],
        }
    rendu = _appeler(source, jeton, "/issue", "POST", corps)
    if not isinstance(rendu, dict) or not rendu.get("key"):
        raise JiraRefuse("Jira n'a pas rendu la demande créée")
    clef = str(rendu["key"])
    return Demande(clef, titre.strip(), "créée", f"{source.adresse}/browse/{clef}")
