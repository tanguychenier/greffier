"""Suggesting the tickets to create from a set of minutes.

Suggesting, never creating: a ticket opened without being read is a ticket
nobody closes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from greffier.ports.outbound import Writer

GUIDANCE = """À partir du compte rendu de réunion ci-dessous, propose les tickets à créer.

Rends uniquement un tableau JSON, sans texte autour, dont chaque élément a :
  "titre"       une phrase à l'impératif, moins de 80 caractères
  "description" ce qu'il faut faire et pourquoi, en deux ou trois phrases
  "assigne"     le prénom de la personne concernée, ou "" si ce n'est pas dit
  "echeance"    la date ou l'échéance mentionnée, ou "" si aucune
  "extrait"     la phrase du compte rendu qui justifie ce ticket

Règles :
- un ticket par action réellement décidée, pas par sujet abordé ;
- n'invente ni assignation, ni échéance, ni action : si ce n'est pas dit, laisse vide ;
- ce qui reste ouvert ou en discussion n'est pas un ticket ;
- si le compte rendu ne décide de rien, rends un tableau vide.

Compte rendu :
"""


@dataclass(frozen=True, slots=True)
class Ticket:
    title: str
    description: str = ""
    assignee: str = ""
    due_date: str = ""
    excerpt: str = ""

    def as_markdown(self) -> str:
        lines = [f"### {self.title}", ""]
        if self.description:
            lines += [self.description, ""]
        details = []
        if self.assignee:
            details.append(f"**Pour** {self.assignee}")
        if self.due_date:
            details.append(f"**Échéance** {self.due_date}")
        if details:
            lines += [" · ".join(details), ""]
        if self.excerpt:
            lines += [f"> {self.excerpt}", ""]
        return "\n".join(lines)


@dataclass
class Suggestion:
    tickets: list[Ticket] = field(default_factory=list)
    brut: str = ""

    def as_markdown(self, meeting: str) -> str:
        header = [
            f"# Tickets proposés : {meeting}",
            "",
            "Proposés, **pas créés** : relis-les avant de les ouvrir. Un ticket "
            "ouvert à tort dans un outil partagé coûte plus cher à retirer qu'à "
            "ne pas créer.",
            "",
        ]
        if not self.tickets:
            header.append("Aucune action décidée dans ce compte rendu.")
            return "\n".join(header) + "\n"
        return "\n".join(header) + "\n" + "\n".join(t.as_markdown() for t in self.tickets)


def extract_json(response: str) -> list[object]:
    """Recovers the JSON array, even wrapped in text."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", response.strip(), flags=re.MULTILINE).strip()
    try:
        charge = json.loads(cleaned)
    except json.JSONDecodeError:
        found = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not found:
            return []
        try:
            charge = json.loads(found.group(0))
        except json.JSONDecodeError:
            return []
    return charge if isinstance(charge, list) else []


def from_answer(response: str) -> Suggestion:
    """Builds the tickets from what the writer answered."""
    tickets = []
    for item in extract_json(response):
        if not isinstance(item, dict):
            continue
        title = str(item.get("titre", "")).strip()
        if not title:
            continue
        tickets.append(Ticket(
            title=title,
            description=str(item.get("description", "")).strip(),
            assignee=str(item.get("assigne", "")).strip(),
            due_date=str(item.get("echeance", "")).strip(),
            excerpt=str(item.get("extrait", "")).strip(),
        ))
    return Suggestion(tickets=tickets, brut=response)


def offer(minutes: str, writer: Writer) -> Suggestion:
    """Asks the same writer that wrote the minutes for the tickets."""
    return from_answer(writer.write_up(GUIDANCE + minutes))
