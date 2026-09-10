"""Proposer les tickets à créer à partir d'un compte rendu.

Le compte rendu contient déjà une section « Décisions et suites » : quoi, qui,
quand. Il ne reste qu'à la transformer en tickets — et à s'arrêter là.

**Rien n'est créé.** Les tickets sont proposés dans un fichier, à relire et à
ouvrir soi-même. Créer automatiquement des tickets depuis une transcription
reviendrait à polluer un outil partagé sur la foi d'un texte produit par un
modèle : la relecture humaine est le garde-fou, pas une formalité.
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
    assigne: str = ""
    echeance: str = ""
    extrait: str = ""

    def as_markdown(self) -> str:
        lines = [f"### {self.title}", ""]
        if self.description:
            lines += [self.description, ""]
        details = []
        if self.assigne:
            details.append(f"**Pour** {self.assigne}")
        if self.echeance:
            details.append(f"**Échéance** {self.echeance}")
        if details:
            lines += [" · ".join(details), ""]
        if self.extrait:
            lines += [f"> {self.extrait}", ""]
        return "\n".join(lines)


@dataclass
class Suggestion:
    tickets: list[Ticket] = field(default_factory=list)
    brut: str = ""

    def as_markdown(self, meeting: str) -> str:
        header = [
            f"# Tickets proposés — {meeting}",
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
    """Récupère le tableau JSON, même enrobé de texte ou de balises.

    Un modèle qui répond « Voici les tickets : ```json … ``` » reste utilisable :
    exiger une réponse parfaitement nue rendrait la fonction fragile pour rien.
    """
    nettoye = re.sub(r"^```(?:json)?|```$", "", response.strip(), flags=re.MULTILINE).strip()
    try:
        charge = json.loads(nettoye)
    except json.JSONDecodeError:
        trouve = re.search(r"\[.*\]", nettoye, re.DOTALL)
        if not trouve:
            return []
        try:
            charge = json.loads(trouve.group(0))
        except json.JSONDecodeError:
            return []
    return charge if isinstance(charge, list) else []


def depuis_reponse(response: str) -> Suggestion:
    """Construit les tickets à partir de ce que le rédacteur a rendu."""
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
            assigne=str(item.get("assigne", "")).strip(),
            echeance=str(item.get("echeance", "")).strip(),
            extrait=str(item.get("extrait", "")).strip(),
        ))
    return Suggestion(tickets=tickets, brut=response)


def offer(minutes: str, writer: Writer) -> Suggestion:
    """Demande les tickets au même rédacteur que le compte rendu."""
    return depuis_reponse(writer.write_up(GUIDANCE + minutes))
