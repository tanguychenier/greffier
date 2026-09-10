"""Drawing from a meeting the points that feed a subject's board."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from greffier.domain.board import Contribution, Kind, Standing
from greffier.ports import outbound

GUIDANCE = """Tu extrais d'une réunion les points qui construisent la carte d'un
sujet. Tu ne rédiges pas, tu extrais.

Rends **uniquement** un tableau JSON, sans texte avant ni après, sans bloc de
code. Chaque élément :

{{"texte": "...", "genre": "problème|piste|action|constat",
  "etat": "acté|en discussion", "sous": "..."}}

Règles :

- « texte » : le point, en cinq à douze mots. Pas une phrase de compte rendu,
  un intitulé de branche. Pas de ponctuation finale.
- « genre » : « problème » pour une difficulté constatée, « piste » pour une
  solution envisagée, « action » pour ce que quelqu'un doit faire, « constat »
  pour le reste.
- « etat » : « acté » **uniquement** si le groupe a explicitement tranché, et
  seulement pour une « piste » ou une « action ». Un « problème » et un
  « constat » ne s'actent pas : ils sont constatés, et « acté » se lirait
  « le groupe a décidé ce problème », ce qui n'a pas de sens. Une idée évoquée,
  une proposition, une intention : « en discussion ». En cas de doute,
  « en discussion ».
- « sous » : le « texte » exact d'un autre élément de ta liste, celui auquel
  celui-ci se rattache. Vide pour un point de premier niveau. Une piste se
  rattache au problème qu'elle résout ; une action à ce qu'elle sert.
- N'invente rien. Si la réunion ne dit rien du sujet demandé, rends [].
- Ne mets ni nom de personne ni citation dans « texte » : une carte se partage
  largement, et un intitulé de branche n'a pas à désigner quelqu'un.
- Douze éléments au maximum, les plus structurants. Une carte illisible ne
  sert à rien.
- **Si un point figure déjà dans « Déjà sur la carte », reprends son libellé
  mot pour mot.** Une reformulation crée une branche de plus au lieu de
  compléter celle qui existe, et la carte se remplit de doublons — c'est
  arrivé, treize points sont devenus vingt-six. Ne le reprends que s'il s'agit
  vraiment du même point ; sinon, formule le tien.
"""

_KINDS = {str(kind): kind for kind in Kind}
_STANDINGS = {str(state): state for state in Standing}

_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

def extract(
    writer: outbound.Writer,
    subject: str,
    material: str,
    maximum: int = 12,
    already: Sequence[str] = (),
) -> list[Contribution]:
    """The contributions this meeting brings on this subject."""
    if not material.strip():
        return []
    invite = [f"Sujet à cartographier : {subject}"]
    if already:
        invite.append(
            "\nDéjà sur la carte, à reprendre mot pour mot s'il s'agit du même point :\n"
            + "\n".join(f"- {label_text}" for label_text in already)
        )
    invite.append(f"\nCe qui a été dit :\n{material}")
    return analyser(writer.write_up("\n".join(invite)), maximum=maximum)

class UnreadableOutput(ValueError):
    """The answer held no table. Distinct from an empty answer."""

def analyser(rendered: str, maximum: int = 12) -> list[Contribution]:
    """Turns the writer's answer into contributions."""
    found = _BLOCK.search(rendered)
    brut = found.group(1) if found else rendered
    start, end = brut.find("["), brut.rfind("]")
    if start == -1 or end <= start:
        raise UnreadableOutput(
            "la réponse ne contient aucun tableau JSON : "
            + " ".join(rendered.split())[:160]
        )
    try:
        items = json.loads(brut[start:end + 1])
    except json.JSONDecodeError as trouble:
        raise UnreadableOutput(f"tableau JSON invalide : {trouble}") from trouble
    if not isinstance(items, list):
        raise UnreadableOutput("la réponse n'est pas un tableau")

    apports: list[Contribution] = []
    for item in items[:maximum]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("texte", "")).strip()
        if not text:
            continue
        apports.append(Contribution(
            text=text,
            kind=_KINDS.get(str(item.get("genre", "")).strip(), Kind.OBSERVATION),
            state=_STANDINGS.get(str(item.get("etat", "")).strip(), Standing.UNDER_DISCUSSION)
            if str(item.get("etat", "")).strip() != str(Standing.OVERTAKEN)
            else Standing.UNDER_DISCUSSION,
            under=str(item.get("sous", "")).strip(),
        ))
    return apports
