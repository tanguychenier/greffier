"""Ce que la fenêtre calcule avant d'afficher, sans une ligne de Tk.

Séparé pour la même raison que `style` : ces fonctions se testent sans écran, et
l'image d'intégration continue n'embarque pas Tk.
"""

from __future__ import annotations

import contextlib
from pathlib import Path


def horloge(secondes: float) -> str:
    """Le chronomètre de la réunion.

    Jamais négatif : la durée est calculée en retirant le temps de pause, et un
    état incohérent affichait « -1:59:55 » en gros au milieu de la fenêtre.
    """
    entier = max(0, int(secondes))
    heures, reste = divmod(entier, 3600)
    minutes, restantes = divmod(reste, 60)
    if heures:
        return f"{heures}:{minutes:02d}:{restantes:02d}"
    return f"{minutes}:{restantes:02d}"


def sujet_lisible(identifiant: str, compte_rendu: Path) -> str:
    """Le sujet de la réunion, tiré de son compte rendu.

    « 2026-08-25_14h33_reunion » ne dit rien de ce qui s'est passé. Le titre du
    compte rendu, lui, a été écrit après avoir écouté : c'est lui qu'on montre,
    l'horodatage restant en réserve tant qu'aucun compte rendu n'existe.
    """
    if compte_rendu.exists():
        with contextlib.suppress(OSError):
            from greffier.adaptateurs.gabarit_courriel import sujet

            titre = sujet(compte_rendu.read_text(encoding="utf-8"), "")
            if titre:
                # Le titre commence par « Compte rendu : » : inutile de le
                # répéter sur chaque ligne d'une liste de comptes rendus.
                sans_prefixe = titre.split(":", 1)[-1].strip() if ":" in titre else titre
                return sans_prefixe or titre
    return identifiant


def etat_du_direct(en_reunion: bool, annonce: str, phrases: int) -> str:
    """La ligne qui dit ce que le fil est en train de faire, ou pourquoi rien.

    Un onglet vide se lit « personne ne parle » alors qu'il veut souvent dire
    « rien n'écoute » : modèle absent, processus non lancé, réunion terminée. La
    différence est celle entre attendre et perdre sa réunion.
    """
    if not en_reunion:
        return (
            "Aucune réunion en cours. Pendant une réunion, ce qui se dit "
            "s'affiche ici et le locuteur se corrige d'un clic sur son nom."
        )
    if phrases == 0:
        attente = annonce or "En attente de la première tranche…"
        return f"{attente} Clique sur un nom pour corriger qui parle."
    aide = (
        "Clique sur un nom pour corriger qui parle : « ? » signale un nom deviné "
        "par la voix, pas encore confirmé."
    )
    return f"{phrases} phrase(s) transcrite(s). {aide}"
