"""Lire et écrire sur un GitLab inscrit au registre des sources.

Ce n'est **pas** l'assistant qui appelle l'API. Il n'a que deux outils, la
recherche et la lecture d'une page web, et cela reste vrai : lui confier un
jeton d'écriture reviendrait à ce qu'une phrase mal comprise crée un ticket.
C'est Greffier qui appelle, sur une intention reconnue, après confirmation — et
l'assistant ne voit que le résultat.

Deux conséquences que ce module tient :

- **la portée vient du registre**, pas de la phrase. Un projet qui n'y figure
  pas est inatteignable, même nommé explicitement ;
- **toute écriture rend ce qu'elle a fait**, avec l'adresse de ce qui a été
  créé. Une écriture dont on ne peut pas montrer le résultat n'est pas
  vérifiable.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from greffier.domaine.sources import Source

DELAI = 15.0

AU_PLUS = 20

class GitLabRefuse(RuntimeError):
    """L'appel n'a pas eu lieu, et pour une raison présentable."""

@dataclass(frozen=True, slots=True)
class Ticket:
    """Un ticket, réduit à ce qui sert à en parler."""

    numero: int
    titre: str
    etat: str
    adresse: str
    assigne: str = ""
    etiquettes: tuple[str, ...] = ()

    def dire(self) -> str:
        qui = f" — {self.assigne}" if self.assigne else ""
        marques = f" [{', '.join(self.etiquettes)}]" if self.etiquettes else ""
        return f"#{self.numero} {self.titre}{qui}{marques} ({self.etat})"

def _appeler(
    source: Source, jeton: str, chemin: str, methode: str = "GET",
    corps: dict[str, Any] | None = None,
) -> object:
    projet = urllib.parse.quote(source.projet, safe="")
    requete = urllib.request.Request(
        f"{source.adresse}/api/v4/projects/{projet}{chemin}",
        method=methode,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "PRIVATE-TOKEN": jeton,
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
            raise GitLabRefuse(
                f"jeton refusé sur « {source.nom} » ({souci.code}). Vérifie sa "
                "portée : lire les tickets demande « read_api », en créer "
                "demande « api »."
            ) from souci
        if souci.code == 404:
            raise GitLabRefuse(
                f"projet « {source.projet} » introuvable sur {source.adresse}. "
                "Un projet privé invisible du jeton rend aussi 404."
            ) from souci
        raise GitLabRefuse(f"GitLab a répondu {souci.code} : {detail}") from souci
    except (urllib.error.URLError, TimeoutError) as souci:
        raise GitLabRefuse(f"{source.adresse} est injoignable : {souci}") from souci
    except (ValueError, OSError) as souci:
        raise GitLabRefuse(str(souci)) from souci

def _en_ticket(brut: dict[str, Any]) -> Ticket:
    assigne = (brut.get("assignee") or {}).get("name", "") or ""
    return Ticket(
        numero=int(brut.get("iid", 0)),
        titre=str(brut.get("title", "")).strip(),
        etat=str(brut.get("state", "")),
        adresse=str(brut.get("web_url", "")),
        assigne=assigne,
        etiquettes=tuple(str(x) for x in brut.get("labels", [])),
    )

def tickets(
    source: Source, jeton: str, ouverts: bool = True, cherche: str = ""
) -> list[Ticket]:
    """Les tickets du projet inscrit. Lecture seule, toujours permise."""
    parametres = {"per_page": str(AU_PLUS), "order_by": "updated_at"}
    if ouverts:
        parametres["state"] = "opened"
    if cherche.strip():
        parametres["search"] = cherche.strip()
    rendu = _appeler(source, jeton, f"/issues?{urllib.parse.urlencode(parametres)}")
    if not isinstance(rendu, list):
        raise GitLabRefuse("réponse inattendue de GitLab")
    return [_en_ticket(brut) for brut in rendu if isinstance(brut, dict)]

def demandes_de_fusion(source: Source, jeton: str, ouvertes: bool = True) -> list[Ticket]:
    """Les demandes de fusion, présentées comme des tickets — même besoin."""
    parametres = {"per_page": str(AU_PLUS), "order_by": "updated_at"}
    if ouvertes:
        parametres["state"] = "opened"
    rendu = _appeler(
        source, jeton, f"/merge_requests?{urllib.parse.urlencode(parametres)}"
    )
    if not isinstance(rendu, list):
        raise GitLabRefuse("réponse inattendue de GitLab")
    return [_en_ticket(brut) for brut in rendu if isinstance(brut, dict)]

def creer_un_ticket(
    source: Source, jeton: str, titre: str, description: str = ""
) -> Ticket:
    """Crée un ticket. **L'appelant doit avoir confirmé.**

    Ce module ne demande rien : il ne sait pas s'il tourne dans une fenêtre, un
    terminal ou un fil de fond. La confirmation appartient à qui parle à
    l'humain, et le droit d'écriture au registre — les deux sont exigés, et ni
    l'un ni l'autre ne suffit.
    """
    if not source.peut_ecrire:
        raise GitLabRefuse(
            f"« {source.nom} » est en lecture seule : aucun ticket n'a été créé"
        )
    if not titre.strip():
        raise GitLabRefuse("un ticket sans titre ne sert à personne")
    rendu = _appeler(
        source, jeton, "/issues", "POST",
        {"title": titre.strip(), "description": description},
    )
    if not isinstance(rendu, dict) or not rendu.get("iid"):
        raise GitLabRefuse("GitLab n'a pas rendu le ticket créé")
    return _en_ticket(rendu)

def commenter(source: Source, jeton: str, numero: int, texte: str) -> str:
    """Ajoute un commentaire à un ticket. Rend son adresse.

    Commenter est une écriture, au même titre que créer : un commentaire
    notifie des gens et reste attaché à leur travail.
    """
    if not source.peut_ecrire:
        raise GitLabRefuse(f"« {source.nom} » est en lecture seule")
    if not texte.strip():
        raise GitLabRefuse("un commentaire vide n'apporte rien")
    rendu = _appeler(
        source, jeton, f"/issues/{numero}/notes", "POST", {"body": texte}
    )
    if not isinstance(rendu, dict):
        raise GitLabRefuse("réponse inattendue de GitLab")
    return f"{source.adresse}/{source.projet}/-/issues/{numero}"
