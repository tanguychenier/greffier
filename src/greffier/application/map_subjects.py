"""Tirer d'une réunion les points qui nourrissent la carte d'un sujet.

Ce que le rédacteur sait faire — distinguer un problème d'une piste, une
décision d'une intention — est exactement ce qu'il faut ici, et c'est hors de
portée d'une règle. Il rend donc une liste structurée, et ce module la traduit
en apports.

Deux exigences qui gouvernent tout :

- **Le format doit être relisible par une machine.** Une carte construite à
  partir de prose libre serait fausse une fois sur trois. On demande du JSON, on
  refuse ce qui ne s'analyse pas, et on ne devine rien.
- **Rien n'est acté par défaut.** La carte s'écrit pendant la réunion : tout ce
  qui vient du fil du direct est « en discussion » tant qu'une décision
  explicite n'est pas relevée. Présenter une idée lancée à l'oral comme une
  décision de l'équipe est le défaut le plus grave possible ici.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from greffier.domain.board import Apport, Genre, RecorderState
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

_KINDS = {str(kind): kind for kind in Genre}
_ETATS = {str(state): state for state in RecorderState}

_BLOC = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

def extract(
    writer: outbound.Writer,
    subject: str,
    material: str,
    maximum: int = 12,
    deja: Sequence[str] = (),
) -> list[Apport]:
    """Les apports que cette réunion fournit sur ce sujet.

    `deja` porte les libellés qui sont **déjà** sur la carte. Les donner est ce
    qui permet de compléter au lieu de dupliquer : sans eux, le rédacteur
    reformule d'une extraction à l'autre — « Pré-production du client en retard
    de deux versions » puis « Pré-prod cliente en retard de deux versions » —
    et chaque reformulation ouvre une branche de plus. Mesuré : treize points
    devenus vingt-six à la seconde publication.
    """
    if not material.strip():
        return []
    invite = [f"Sujet à cartographier : {subject}"]
    if deja:
        invite.append(
            "\nDéjà sur la carte, à reprendre mot pour mot s'il s'agit du même point :\n"
            + "\n".join(f"- {label_text}" for label_text in deja)
        )
    invite.append(f"\nCe qui a été dit :\n{material}")
    return analyser(writer.write_up("\n".join(invite)), maximum=maximum)

class RenduIllisible(ValueError):
    """La réponse ne contenait pas de tableau. Distinct de « rien trouvé ».

    Confondre les deux est ce qui a fait passer un échec pour un résultat : la
    commande annonçait « rien à ajouter » alors que le modèle avait répondu en
    prose sans jamais produire de JSON.
    """

def analyser(rendered: str, maximum: int = 12) -> list[Apport]:
    """Traduit la réponse du rédacteur en apports. Ignore ce qui ne va pas.

    Chaque élément est validé séparément : un objet mal formé au milieu de la
    liste ne doit pas faire perdre les onze autres. En revanche, une réponse
    **sans aucun tableau** lève : c'est une panne, pas un résultat vide.
    """
    trouve = _BLOC.search(rendered)
    brut = trouve.group(1) if trouve else rendered
    start, end = brut.find("["), brut.rfind("]")
    if start == -1 or end <= start:
        raise RenduIllisible(
            "la réponse ne contient aucun tableau JSON : "
            + " ".join(rendered.split())[:160]
        )
    try:
        items = json.loads(brut[start:end + 1])
    except json.JSONDecodeError as trouble:
        raise RenduIllisible(f"tableau JSON invalide : {trouble}") from trouble
    if not isinstance(items, list):
        raise RenduIllisible("la réponse n'est pas un tableau")

    apports: list[Apport] = []
    for item in items[:maximum]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("texte", "")).strip()
        if not text:
            continue
        apports.append(Apport(
            text=text,
            kind=_KINDS.get(str(item.get("genre", "")).strip(), Genre.CONSTAT),
            state=_ETATS.get(str(item.get("etat", "")).strip(), RecorderState.EN_DISCUSSION)
            if str(item.get("etat", "")).strip() != str(RecorderState.DEPASSE)
            else RecorderState.EN_DISCUSSION,
            sous=str(item.get("sous", "")).strip(),
        ))
    return apports
