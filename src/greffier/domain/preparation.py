"""A meeting prepared before it is held.

The conversation already answered outside a meeting, and led nowhere: it spoke
of a meeting that already existed, never of the one about to be held. Someone
preparing theirs -- « rappelle-moi la dernière, va voir dans le dépôt, cherche
ce texte » -- gathered material that stayed in a corner while the meeting
started from nothing.

A preparation is that conversation with somewhere to go: a subject, what was
asked and answered, the documents gathered, the points to raise. Starting a
meeting **consumes** it, which is the whole point -- material that does not
reach the meeting was worth nothing.

Pure: what a preparation holds, what it hands over, and what it costs in room.
Where it is kept, and who fills it, are somebody else's business.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: Room given to a preparation in the header of the meeting it opens. Larger
#: than the recalled meetings (2 000): this material was gathered on purpose,
#: for this meeting, by somebody who will be in the room.
PREPARATION_MAXIMUM = 6_000


@dataclass(frozen=True, slots=True)
class Exchange:
    """One question and its answer, as they were said."""

    asked: str
    answered: str = ""

    @property
    def empty(self) -> bool:
        return not self.asked.strip()


@dataclass(frozen=True, slots=True)
class Preparation:
    """What was gathered before a meeting, waiting for it to start."""

    identifier: str
    subject: str = ""
    opened_on: str = ""
    exchanges: tuple[Exchange, ...] = field(default=())
    documents: tuple[str, ...] = field(default=())
    to_raise: tuple[str, ...] = field(default=())
    #: Who is expected in the room. Reported in use: « Sophie était en réunion
    #: alors que non, elle était sur une autre réunion », and the minutes carried
    #: her name. A voice bank grows across meetings and proposes anybody it has
    #: ever heard; said in advance, who is expected turns a resemblance to
    #: somebody absent into what it is -- a resemblance.
    expected: tuple[str, ...] = field(default=())
    #: Set when a meeting has taken it in. A preparation is consumed once: two
    #: meetings opening on the same material would each believe it was theirs.
    taken_by: str = ""

    @property
    def empty(self) -> bool:
        return not (self.exchanges or self.documents or self.to_raise or self.expected)

    @property
    def available(self) -> bool:
        """Whether a meeting starting now would open on it."""
        return not self.taken_by and not self.empty

    def asked(self, question: str, answer: str = "") -> Preparation:
        """The same preparation, one exchange further."""
        exchange = Exchange(asked=question.strip(), answered=answer.strip())
        if exchange.empty:
            return self
        return replace(self, exchanges=(*self.exchanges, exchange))

    def expecting(self, name: str) -> Preparation:
        """Somebody expected in the room, kept once however often they are named."""
        clean = " ".join(name.split())
        if not clean or clean in self.expected:
            return self
        return replace(self, expected=(*self.expected, clean))

    def raising(self, point: str) -> Preparation:
        """A point to put to the room, kept once however often it is said."""
        clean = " ".join(point.split())
        if not clean or clean in self.to_raise:
            return self
        return replace(self, to_raise=(*self.to_raise, clean))

    def with_document(self, name: str) -> Preparation:
        clean = name.strip()
        if not clean or clean in self.documents:
            return self
        return replace(self, documents=(*self.documents, clean))

    def taken(self, identifier: str) -> Preparation:
        """Consumed by a meeting, and no longer offered to the next one."""
        return replace(self, taken_by=identifier)

    def header(self, place: int = PREPARATION_MAXIMUM) -> str:
        """What the meeting opens on, in the words of the preparation.

        The questions first: what somebody thought to ask before the meeting is
        what they mean to get out of it. The answers follow, cut at an exchange
        and never inside one -- half an answer read as a whole one is worse than
        no answer, since nothing says it was cut.
        """
        if self.empty:
            return ""
        lines = ["[Préparation de cette réunion]"]
        if self.subject:
            lines.append(f"Sujet annoncé : {self.subject}")
        if self.to_raise:
            lines.append("Points à soulever, dans l'ordre où ils ont été notés :")
            lines += [f"- {point}" for point in self.to_raise]
        if self.expected:
            lines.append(
                "Personnes attendues : " + ", ".join(self.expected)
                + ". N'attribue un propos qu'à quelqu'un dont la transcription "
                "montre la présence."
            )
        if self.documents:
            lines.append("Documents rassemblés avant la séance : "
                          + ", ".join(self.documents))
        header = "\n".join(lines)
        the_exchanges = _that_fit(self.exchanges, place - len(header))
        if the_exchanges:
            header += (
                "\n\nCe qui a été demandé avant la réunion, et ce qui a été "
                "répondu. N'y reviens que si la séance y touche :\n" + the_exchanges
            )
        return header + "\n\n"


def _that_fit(exchanges: tuple[Exchange, ...], place: int) -> str:
    """The most recent exchanges that fit, in the order they happened."""
    retained_ones: list[str] = []
    length = 0
    for exchange in reversed(exchanges):
        rendered = f"- demandé : {exchange.asked}"
        if exchange.answered:
            rendered += f"\n  répondu : {exchange.answered}"
        if length + len(rendered) + 1 > place:
            break
        retained_ones.append(rendered)
        length += len(rendered) + 1
    return "\n".join(reversed(retained_ones))


def question_prompt(preparation: Preparation, setting: str, question: str) -> str:
    """What is handed to the model when somebody prepares a meeting out loud.

    The question first and the material after, in that order: what is asked is
    what must be answered, and a model given four thousand characters before the
    question answers the material instead.

    Said plainly, because the difference matters here: this meeting has not been
    held. Handed the same material as a meeting that has, the model summarises
    minutes that do not exist -- and somebody preparing a meeting would be told
    what was decided in it.
    """
    material = preparation.header()
    return (
        f"Question : {question.strip()}\n\n"
        "Cette réunion n'a pas encore eu lieu : on la prépare. Réponds à la "
        "question, brièvement, pour quelqu'un qui parle et qui écoutera la "
        "réponse à voix haute. N'invente aucun propos tenu en séance, et dis "
        "quand tu ne sais pas.\n\n"
        + (setting or "")
        + (f"\n{material}" if material else "")
    )
