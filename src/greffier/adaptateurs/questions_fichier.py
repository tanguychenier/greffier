"""La file des questions, en ajout seul, un fichier par réunion.

Même choix que le fil du direct, pour les mêmes raisons : deux processus se
partagent la file — celui qui écoute la dépose, la fenêtre la lit et y répond —
et un fichier en ajout seul survit à tout, se relit après un plantage et ne
demande ni démon ni port réseau.

Une réponse ne réécrit pas la question : elle publie une ligne qui dit ce
qu'elle répond. On garde ainsi la trace de ce qui a été demandé et de ce qui a
été décidé, ce qui est exactement ce dont le contexte a besoin pour apprendre.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path

from greffier.domaine.questions import Motif, Question

GENRE_QUESTION = "question"
GENRE_REPONSE = "reponse"


@dataclass(frozen=True, slots=True)
class EnAttente:
    """Une question posée à laquelle personne n'a encore répondu."""

    question: Question

    @property
    def numero(self) -> int:
        return self.question.numero


def fichier_des_questions(dossier: Path, identifiant: str) -> Path:
    return dossier / f"{identifiant}.jsonl"


def deposer(fichier: Path, question: Question) -> None:
    """Ajoute une question à la file. N'écrase jamais rien."""
    fichier.parent.mkdir(parents=True, exist_ok=True)
    ligne = {
        "genre": GENRE_QUESTION,
        "numero": question.numero,
        "texte": question.texte,
        "motif": str(question.motif),
        "entendu": question.entendu,
        "attendu": question.attendu,
    }
    with fichier.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(ligne, ensure_ascii=False) + "\n")


def repondre(fichier: Path, numero: int, reponse: str) -> None:
    """Publie une réponse. La question reste, avec sa trace."""
    fichier.parent.mkdir(parents=True, exist_ok=True)
    with fichier.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(
            {"genre": GENRE_REPONSE, "numero": numero, "reponse": reponse},
            ensure_ascii=False,
        ) + "\n")


def lire(fichier: Path) -> tuple[list[EnAttente], dict[int, str]]:
    """Les questions sans réponse, et les réponses déjà données.

    Une ligne illisible est sautée sans faire échouer la lecture : la file est
    écrite par un autre processus, qui peut être interrompu en pleine ligne.
    """
    if not fichier.exists():
        return ([], {})
    questions: dict[int, Question] = {}
    reponses: dict[int, str] = {}
    with contextlib.suppress(OSError):
        for brute in fichier.read_text(encoding="utf-8").splitlines():
            if not brute.strip():
                continue
            try:
                ligne = json.loads(brute)
            except json.JSONDecodeError:
                continue
            if not isinstance(ligne, dict):
                continue
            if ligne.get("genre") == GENRE_QUESTION:
                with contextlib.suppress(ValueError, KeyError):
                    questions[int(ligne["numero"])] = Question(
                        numero=int(ligne["numero"]),
                        texte=str(ligne.get("texte", "")),
                        motif=Motif(ligne.get("motif", Motif.TERME_PROCHE)),
                        entendu=str(ligne.get("entendu", "")),
                        attendu=str(ligne.get("attendu", "")),
                    )
            elif ligne.get("genre") == GENRE_REPONSE:
                with contextlib.suppress(ValueError, KeyError):
                    reponses[int(ligne["numero"])] = str(ligne.get("reponse", ""))
    attente = [
        EnAttente(question)
        for numero, question in sorted(questions.items())
        if numero not in reponses
    ]
    return (attente, reponses)


def clefs_deja_posees(fichier: Path) -> set[str]:
    """De quoi ne pas reposer une question après un redémarrage du direct.

    L'interrogateur tient cette mémoire en vivant ; le processus qui écoute,
    lui, peut être relancé en cours de réunion.
    """
    attente, _ = lire(fichier)
    posees = {en_attente.question.clef for en_attente in attente}
    if not fichier.exists():
        return posees
    # Les questions déjà répondues comptent aussi : y revenir serait pire.
    with contextlib.suppress(OSError):
        for brute in fichier.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError, ValueError, KeyError):
                ligne = json.loads(brute)
                if isinstance(ligne, dict) and ligne.get("genre") == GENRE_QUESTION:
                    posees.add(Question(
                        numero=int(ligne["numero"]),
                        texte=str(ligne.get("texte", "")),
                        motif=Motif(ligne.get("motif", Motif.TERME_PROCHE)),
                        entendu=str(ligne.get("entendu", "")),
                        attendu=str(ligne.get("attendu", "")),
                    ).clef)
    return posees
