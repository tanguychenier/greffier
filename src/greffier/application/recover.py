"""Reconstruire une réunion depuis le seul fil du direct.

Le fil s'écrit tour par tour pendant la réunion, mais il ne devient une réunion
qu'au traitement final. Si celui-ci ne démarre jamais — c'est arrivé le
2026-09-09, un traitement lancé à côté ayant fait croire à la fenêtre que la
réunion était finie — il reste un fichier `.jsonl` que rien ne sait lire :
l'onglet Réunions ne montre rien, aucun compte rendu ne peut s'écrire, et
pourtant tout ce qui a été dit est là.

Ce que cette reconstruction rend est **moins bon** qu'un traitement, et il faut
le dire : la transcription vient du modèle rapide du direct, les voix ne sont
pas recollées par empreinte, et une phrase à cheval sur deux locuteurs n'a pas
été arbitrée. Mais une réunion imparfaite existe, se relit, et son compte rendu
s'écrit. C'est la différence entre approximatif et perdu.

Ce module ne lit aucun fichier : il reçoit des lignes déjà relues et rend une
réunion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from greffier.domain.live import LiveThread
from greffier.domain.meeting import StoredMeeting, held_on
from greffier.domain.models import Source, Span, SpeakerTurn, Utterance

WARNING = (
    "Réunion reconstruite depuis le fil du direct, faute de traitement complet. "
    "La transcription vient du modèle rapide, les voix n'ont pas été recollées "
    "par empreinte et l'attribution des phrases est approximative. Retraiter "
    "l'enregistrement, s'il existe encore, donnera un bien meilleur résultat."
)

def depuis_le_fil(
    identifier: str,
    lines: list[dict[str, Any]],
    audio: Path | None = None,
) -> StoredMeeting:
    """La réunion que ce fil permet de reconstituer.

    Les corrections humaines du fil sont rejouées : c'est justement ce que le
    direct apporte de mieux qu'une transcription brute — quelqu'un a nommé des
    voix pendant la réunion, et ce travail ne doit pas se perdre.
    """
    thread = LiveThread()
    from greffier.application.follow import replay

    replay(lines, thread)

    utterances: list[Utterance] = []
    turns: list[SpeakerTurn] = []
    for turn in thread.turns:
        if not turn.text.strip():
            continue
        utterances.append(Utterance(
            span=turn.span,
            text=turn.text.strip(),
            voice=turn.voice,
            source=Source.INCONNUE,
        ))
        turns.append(SpeakerTurn(turn.span, turn.voice, Source.INCONNUE))

    names = {
        voice: connue.name
        for voice, connue in thread.voice.items()
        if connue.name and connue.certitude.name != "INCONNUE"
    }
    duration = turns[-1].span.end if turns else 0.0
    quand = held_on(identifier)
    commencee = None
    if quand is not None:
        annee, mois, jour, heure, minute = quand
        commencee = datetime(annee, mois, jour, heure, minute).astimezone()

    return StoredMeeting(
        identifier=identifier,
        audio=audio if audio is not None else Path(""),
        traitee_le=datetime.now(UTC),
        duration=duration,
        utterances=utterances,
        turns=turns,
        names=names,
        propositions={},
        warnings=[WARNING],
        commencee_le=commencee,
        terminee_le=(
            commencee + timedelta(seconds=duration) if commencee and duration else None
        ),
    )

def join_spans(turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
    """Recolle les tours consécutifs d'une même voix.

    Le direct découpe par tranche de dix secondes, donc une personne qui parle
    une minute produit six tours. Les garder tels quels ferait compter six
    prises de parole là où il y en a une, ce qui faussé le temps de parole et
    le nombre de participants.
    """
    if not turns:
        return []
    recolles = [SpeakerTurn(turns[0].span, turns[0].voice, turns[0].source)]
    for turn in turns[1:]:
        dernier = recolles[-1]
        if turn.voice == dernier.voice and turn.span.start <= dernier.span.end:
            recolles[-1] = SpeakerTurn(
                Span(dernier.span.start,
                           max(dernier.span.end, turn.span.end)),
                dernier.voice, dernier.source,
            )
            continue
        recolles.append(SpeakerTurn(turn.span, turn.voice, turn.source))
    return recolles
