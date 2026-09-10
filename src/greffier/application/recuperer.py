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

from greffier.domaine.direct import Fil
from greffier.domaine.modeles import Intervalle, Replique, Source, TourDeParole
from greffier.domaine.reunion import ReunionEnregistree, tenue_le

AVERTISSEMENT = (
    "Réunion reconstruite depuis le fil du direct, faute de traitement complet. "
    "La transcription vient du modèle rapide, les voix n'ont pas été recollées "
    "par empreinte et l'attribution des phrases est approximative. Retraiter "
    "l'enregistrement, s'il existe encore, donnera un bien meilleur résultat."
)

def depuis_le_fil(
    identifiant: str,
    lignes: list[dict[str, Any]],
    audio: Path | None = None,
) -> ReunionEnregistree:
    """La réunion que ce fil permet de reconstituer.

    Les corrections humaines du fil sont rejouées : c'est justement ce que le
    direct apporte de mieux qu'une transcription brute — quelqu'un a nommé des
    voix pendant la réunion, et ce travail ne doit pas se perdre.
    """
    fil = Fil()
    from greffier.application.suivre import rejouer

    rejouer(lignes, fil)

    repliques: list[Replique] = []
    tours: list[TourDeParole] = []
    for tour in fil.tours:
        if not tour.texte.strip():
            continue
        repliques.append(Replique(
            intervalle=tour.intervalle,
            texte=tour.texte.strip(),
            voix=tour.voix,
            source=Source.INCONNUE,
        ))
        tours.append(TourDeParole(tour.intervalle, tour.voix, Source.INCONNUE))

    noms = {
        voix: connue.nom
        for voix, connue in fil.voix.items()
        if connue.nom and connue.certitude.name != "INCONNUE"
    }
    duree = tours[-1].intervalle.fin if tours else 0.0
    quand = tenue_le(identifiant)
    commencee = None
    if quand is not None:
        annee, mois, jour, heure, minute = quand
        commencee = datetime(annee, mois, jour, heure, minute).astimezone()

    return ReunionEnregistree(
        identifiant=identifiant,
        audio=audio if audio is not None else Path(""),
        traitee_le=datetime.now(UTC),
        duree=duree,
        repliques=repliques,
        tours=tours,
        noms=noms,
        propositions={},
        avertissements=[AVERTISSEMENT],
        commencee_le=commencee,
        # La fin déduite du dernier tour, faute de mieux : l'état
        # d'enregistrement, seul à connaître l'heure d'arrêt, n'a pas été écrit
        # puisque la réunion n'a jamais été finalisée.
        terminee_le=(
            commencee + timedelta(seconds=duree) if commencee and duree else None
        ),
    )

def fusionner_intervalles(tours: list[TourDeParole]) -> list[TourDeParole]:
    """Recolle les tours consécutifs d'une même voix.

    Le direct découpe par tranche de dix secondes, donc une personne qui parle
    une minute produit six tours. Les garder tels quels ferait compter six
    prises de parole là où il y en a une, ce qui faussé le temps de parole et
    le nombre de participants.
    """
    if not tours:
        return []
    recolles = [TourDeParole(tours[0].intervalle, tours[0].voix, tours[0].source)]
    for tour in tours[1:]:
        dernier = recolles[-1]
        if tour.voix == dernier.voix and tour.intervalle.debut <= dernier.intervalle.fin:
            recolles[-1] = TourDeParole(
                Intervalle(dernier.intervalle.debut,
                           max(dernier.intervalle.fin, tour.intervalle.fin)),
                dernier.voix, dernier.source,
            )
            continue
        recolles.append(TourDeParole(tour.intervalle, tour.voix, tour.source))
    return recolles
