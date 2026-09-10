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

from greffier.domaine.carte import Apport, Etat, Genre
from greffier.ports import sortants

CONSIGNES = """Tu extrais d'une réunion les points qui construisent la carte d'un
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

_GENRES = {str(genre): genre for genre in Genre}
_ETATS = {str(etat): etat for etat in Etat}

_BLOC = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

def extraire(
    redacteur: sortants.Redacteur,
    sujet: str,
    matiere: str,
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
    if not matiere.strip():
        return []
    # Le sujet et la matière seulement : les consignes sont portées par le
    # rédacteur (`composition.cartographe`). Les répéter ici les faisait arriver
    # après celles du compte rendu, et le modèle suivait les premières.
    invite = [f"Sujet à cartographier : {sujet}"]
    if deja:
        invite.append(
            "\nDéjà sur la carte, à reprendre mot pour mot s'il s'agit du même point :\n"
            + "\n".join(f"- {libelle}" for libelle in deja)
        )
    invite.append(f"\nCe qui a été dit :\n{matiere}")
    return analyser(redacteur.rediger("\n".join(invite)), maximum=maximum)

class RenduIllisible(ValueError):
    """La réponse ne contenait pas de tableau. Distinct de « rien trouvé ».

    Confondre les deux est ce qui a fait passer un échec pour un résultat : la
    commande annonçait « rien à ajouter » alors que le modèle avait répondu en
    prose sans jamais produire de JSON.
    """

def analyser(rendu: str, maximum: int = 12) -> list[Apport]:
    """Traduit la réponse du rédacteur en apports. Ignore ce qui ne va pas.

    Chaque élément est validé séparément : un objet mal formé au milieu de la
    liste ne doit pas faire perdre les onze autres. En revanche, une réponse
    **sans aucun tableau** lève : c'est une panne, pas un résultat vide.
    """
    trouve = _BLOC.search(rendu)
    brut = trouve.group(1) if trouve else rendu
    debut, fin = brut.find("["), brut.rfind("]")
    if debut == -1 or fin <= debut:
        raise RenduIllisible(
            "la réponse ne contient aucun tableau JSON : "
            + " ".join(rendu.split())[:160]
        )
    try:
        elements = json.loads(brut[debut:fin + 1])
    except json.JSONDecodeError as souci:
        raise RenduIllisible(f"tableau JSON invalide : {souci}") from souci
    if not isinstance(elements, list):
        raise RenduIllisible("la réponse n'est pas un tableau")

    apports: list[Apport] = []
    for element in elements[:maximum]:
        if not isinstance(element, dict):
            continue
        texte = str(element.get("texte", "")).strip()
        if not texte:
            continue
        apports.append(Apport(
            texte=texte,
            genre=_GENRES.get(str(element.get("genre", "")).strip(), Genre.CONSTAT),
            # Le défaut est « en discussion », et un état non reconnu y retombe :
            # se tromper vers la prudence ne coûte qu'une couleur, se tromper
            # vers « acté » fait dire à la carte une chose fausse.
            etat=_ETATS.get(str(element.get("etat", "")).strip(), Etat.EN_DISCUSSION)
            if str(element.get("etat", "")).strip() != str(Etat.DEPASSE)
            else Etat.EN_DISCUSSION,
            sous=str(element.get("sous", "")).strip(),
        ))
    return apports
