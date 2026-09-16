"""Rebuilding a meeting from the live thread alone.

The last resort when the audio is gone: the thread holds what was said and who
said it, which is enough for minutes.
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

def from_the_thread(
    identifier: str,
    lines: list[dict[str, Any]],
    audio: Path | None = None,
) -> StoredMeeting:
    """The meeting this thread makes it possible to reconstitute."""
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
            source=Source.UNKNOWN,
            confidence=turn.confidence,
        ))
        turns.append(SpeakerTurn(turn.span, turn.voice, Source.UNKNOWN))

    names = {
        voice: known_one.name
        for voice, known_one in thread.voice.items()
        if known_one.name and known_one.certainty.name != "INCONNUE"
    }
    duration = turns[-1].span.end if turns else 0.0
    when = held_on(identifier)
    begun = None
    if when is not None:
        year, month, day, the_hour, minute = when
        begun = datetime(year, month, day, the_hour, minute).astimezone()

    return StoredMeeting(
        identifier=identifier,
        audio=audio if audio is not None else Path(""),
        processed_at=datetime.now(UTC),
        duration=duration,
        utterances=utterances,
        turns=turns,
        names=names,
        propositions={},
        warnings=[WARNING],
        started_at=begun,
        ended_at=(
            begun + timedelta(seconds=duration) if begun and duration else None
        ),
    )

def join_spans(turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
    """Stitches together consecutive turns of one voice."""
    if not turns:
        return []
    stitched = [SpeakerTurn(turns[0].span, turns[0].voice, turns[0].source)]
    for turn in turns[1:]:
        last = stitched[-1]
        if turn.voice == last.voice and turn.span.start <= last.span.end:
            stitched[-1] = SpeakerTurn(
                Span(last.span.start,
                           max(last.span.end, turn.span.end)),
                last.voice, last.source,
            )
            continue
        stitched.append(SpeakerTurn(turn.span, turn.voice, turn.source))
    return stitched
