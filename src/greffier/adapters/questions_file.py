"""The question queue, append-only, one file per meeting."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path

from greffier.domain.questions import Question, Reason

GENRE_QUESTION = "question"
GENRE_REPONSE = "reponse"

@dataclass(frozen=True, slots=True)
class Pending:
    """A question asked that nobody has answered yet."""

    question: Question

    @property
    def number(self) -> int:
        return self.question.number

def questions_file(folder: Path, identifier: str) -> Path:
    return folder / f"{identifier}.jsonl"

def publish(file: Path, question: Question) -> None:
    """Appends a question to the queue. Never overwrites."""
    file.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "genre": GENRE_QUESTION,
        "numero": question.number,
        "texte": question.text,
        "motif": str(question.motif),
        "entendu": question.entendu,
        "attendu": question.attendu,
    }
    with file.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(line, ensure_ascii=False) + "\n")

def answer(file: Path, number: int, response: str) -> None:
    """Publishes an answer. The question stays, with its answer."""
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(
            {"genre": GENRE_REPONSE, "numero": number, "reponse": response},
            ensure_ascii=False,
        ) + "\n")

def read(file: Path) -> tuple[list[Pending], dict[int, str]]:
    """The unanswered questions, and the answers given."""
    if not file.exists():
        return ([], {})
    questions: dict[int, Question] = {}
    answers: dict[int, str] = {}
    with contextlib.suppress(OSError):
        for brute in file.read_text(encoding="utf-8").splitlines():
            if not brute.strip():
                continue
            try:
                line = json.loads(brute)
            except json.JSONDecodeError:
                continue
            if not isinstance(line, dict):
                continue
            if line.get("genre") == GENRE_QUESTION:
                with contextlib.suppress(ValueError, KeyError):
                    questions[int(line["numero"])] = Question(
                        number=int(line["numero"]),
                        text=str(line.get("texte", "")),
                        motif=Reason(line.get("motif", Reason.NEAR_TERM)),
                        entendu=str(line.get("entendu", "")),
                        attendu=str(line.get("attendu", "")),
                    )
            elif line.get("genre") == GENRE_REPONSE:
                with contextlib.suppress(ValueError, KeyError):
                    answers[int(line["numero"])] = str(line.get("reponse", ""))
    awaiting = [
        Pending(question)
        for number, question in sorted(questions.items())
        if number not in answers
    ]
    return (awaiting, answers)

def keys_already_placed(file: Path) -> set[str]:
    """What it takes not to ask a question again after a restart."""
    awaiting, _ = read(file)
    posees = {en_attente.question.key for en_attente in awaiting}
    if not file.exists():
        return posees
    with contextlib.suppress(OSError):
        for brute in file.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError, ValueError, KeyError):
                line = json.loads(brute)
                if isinstance(line, dict) and line.get("genre") == GENRE_QUESTION:
                    posees.add(Question(
                        number=int(line["numero"]),
                        text=str(line.get("texte", "")),
                        motif=Reason(line.get("motif", Reason.NEAR_TERM)),
                        entendu=str(line.get("entendu", "")),
                        attendu=str(line.get("attendu", "")),
                    ).key)
    return posees
