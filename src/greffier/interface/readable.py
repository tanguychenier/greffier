"""What the window computes before showing, testable without a screen."""

from __future__ import annotations

import contextlib
from pathlib import Path


def clock(seconds: float) -> str:
    """The meeting's stopwatch."""
    entier = max(0, int(seconds))
    heures, remaining = divmod(entier, 3600)
    minutes, restantes = divmod(remaining, 60)
    if heures:
        return f"{heures}:{minutes:02d}:{restantes:02d}"
    return f"{minutes}:{restantes:02d}"

def readable_subject(identifier: str, minutes: Path, subject: str = "") -> str:
    """The meeting's subject: the chosen one, else what was written."""
    if subject.strip():
        return subject.strip()
    if minutes.exists():
        with contextlib.suppress(OSError):
            from greffier.domain.minutes import title as extraire_titre

            title = extraire_titre(minutes.read_text(encoding="utf-8"), "")
            if title:
                without_prefix = title.split(":", 1)[-1].strip() if ":" in title else title
                return without_prefix or title
    return identifier

ETIREMENT_MAXIMUM = 1.25

def button_grid(
    largeurs: list[int], offerte: int, gap: int = 9
) -> tuple[int, int]:
    """La grille d'une barre d'actions : (boutons par rang, largeur de colonne).

    Ici et non dans le composant dessiné : ce qui touche à Tk n'est pas éprouvé
    par les tests, faute de serveur d'affichage en intégration continue, et
    c'est ce calcul qui portait le défaut — le septième bouton de l'onglet
    Réunions sortait de la fenêtre, invisible et inatteignable.

    Trois règles, et elles vont ensemble :

    **Des colonnes de largeur égale.** Des boutons de largeurs différentes ne
    tombent pas ensemble d'un rang à l'autre, et une barre dont les bords ne
    s'alignent pas se lit comme bâclée. La largeur de colonne est donc unique,
    et c'est le plus large qui la fixe au minimum.

    **Les rangs sont équilibrés.** On cherche le nombre minimal de rangs, puis
    on répartit à égalité — sept boutons sur deux rangs donnent 4 et 3, jamais
    5 et 2. Un premier rang plein contre un second presque vide est le défaut
    le plus visible d'une barre qui passe à la ligne.

    **L'étirement est plafonné.** Les colonnes prennent l'espace disponible,
    mais pas plus d'un quart au-delà de ce que le libellé demande : à 1 280 px
    de fenêtre, remplir sans limite donnait des boutons de 290 px pour un
    « Ouvrir » de 96, étirés sur du vide. Un bouton disproportionné est aussi
    mal réparti qu'un bouton qui déborde.
    """
    total = len(largeurs)
    if not total:
        return (1, 0)
    demandee = max(largeurs)
    plafond = int(demandee * ETIREMENT_MAXIMUM)
    for rangs in range(1, total + 1):
        by_rank = -(-total // rangs)  # division entière par excès
        if by_rank * demandee + (by_rank - 1) * gap <= offerte:
            break
    else:
        by_rank = 1
    available = (offerte - (by_rank - 1) * gap) // by_rank
    colonne = max(demandee, min(plafond, available))
    return (by_rank, colonne)

def dot_marker(count: int) -> str:
    """Ce qu'une pastille d'onglet affiche pour ce compte. Vide pour rien.

    Ici plutôt que dans le segment dessiné : ce qui touche à Tk n'est pas
    éprouvé par les tests, faute de serveur d'affichage en intégration
    continue, et c'est le nombre qui porte la règle.

    Au-delà de neuf, le nombre exact n'aide plus : ce qui compte est qu'il y en
    a beaucoup, et deux chiffres déborderaient du disque.
    """
    if count <= 0:
        return ""
    return str(count) if count < 10 else "9+"

def live_state_line(in_a_meeting: bool, annonce: str, sentences: int) -> str:
    """La ligne qui dit ce que le fil est en train de faire, ou pourquoi rien.

    Un onglet vide se lit « personne ne parle » alors qu'il veut souvent dire
    « rien n'écoute » : modèle absent, processus non lancé, réunion terminée. La
    différence est celle entre attendre et perdre sa réunion.
    """
    if not in_a_meeting:
        return (
            "Aucune réunion en cours. Pendant une réunion, ce qui se dit "
            "s'affiche ici et le locuteur se corrige d'un clic sur son nom."
        )
    if sentences == 0:
        awaiting = annonce or "En attente de la première tranche…"
        return f"{awaiting} Clique sur un nom pour corriger qui parle."
    aide = (
        "Clique sur un nom pour corriger qui parle : « ? » signale un nom deviné "
        "par la voix, pas encore confirmé."
    )
    return f"{sentences} phrase(s) transcrite(s). {aide}"
