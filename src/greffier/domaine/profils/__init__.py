"""Le registre des profils de langue.

Une seule entrée aujourd'hui — le français — et c'est volontaire : écrire un
profil coûte une journée, l'éprouver coûte une campagne. Toute la preuve de bout
en bout de ce dépôt repose sur des dialogues français synthétisés puis rejoués ;
tant qu'un dialogue équivalent n'existe pas dans une autre langue, déclarer cette
langue servie serait une promesse sans preuve.
"""

from __future__ import annotations

from greffier.domaine.langue import ProfilLinguistique
from greffier.domaine.profils.francais import FRANCAIS
from greffier.domaine.profils.neutre import NEUTRE

REGISTRE: dict[str, ProfilLinguistique] = {FRANCAIS.code: FRANCAIS}


def pour(code: str | None) -> ProfilLinguistique:
    """Le profil d'une langue, ou le profil neutre.

    Jamais d'exception : un code inconnu, vide ou mal saisi ne doit pas
    interrompre une réunion déjà enregistrée. Il vaut mieux nommer les voix à la
    main que perdre une heure de parole.
    """
    return REGISTRE.get((code or "").strip().lower(), NEUTRE)
