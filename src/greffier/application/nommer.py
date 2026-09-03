"""Donner un nom à une voix, après la réunion.

C'est le chemin principal, et il est délibéré : **personne n'est prié de se
présenter**. On laisse la réunion se dérouler, puis on écoute dix secondes et on
tape un nom. Une seule fois par personne — ensuite l'empreinte est en banque et
la reconnaissance se fait seule.

Les noms prononcés pendant la réunion viennent en renfort, jamais en
remplacement : ils proposent, l'utilisateur tranche.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from greffier.adaptateurs.depot_fichiers import DepotFichiers, ReunionEnregistree
from greffier.domaine.empreintes import agreger
from greffier.domaine.modeles import Intervalle
from greffier.ports import sortants

# Assez pour reconnaître une voix à l'oreille, assez court pour ne pas lasser
# quand il y a cinq personnes à nommer.
DUREE_EXTRAIT = 10.0
# En deçà, un passage ne porte pas assez de voix : ni pour l'oreille, ni pour
# l'empreinte.
DUREE_UTILE = 3.0


@dataclass
class VoixANommer:
    """Une voix de la réunion, telle qu'elle est présentée à l'utilisateur."""

    voix: str
    duree: float
    part: float
    nom: str | None = None          # déjà nommée
    proposition: str | None = None  # nom deviné, à confirmer
    extrait: Intervalle | None = None

    @property
    def a_nommer(self) -> bool:
        return self.nom is None


def voix_a_nommer(reunion: ReunionEnregistree, minimum: float = 10.0) -> list[VoixANommer]:
    """Les voix de la réunion, de la plus bavarde à la moins, avec un extrait.

    Les fragments d'une seconde laissés par la segmentation sont écartés : les
    proposer à nommer ferait passer une réunion de cinq personnes pour une
    assemblée de vingt. Une voix courte qui porte déjà un nom ou une
    proposition détectée dans les mentions échappe à ce filtre : c'est
    justement le prénom prononcé dans une réponse brève qui se perdait sinon,
    jeté avec le fragment qui le portait.
    """
    temps = reunion.temps_de_parole()
    total = sum(d for d in temps.values() if d >= minimum) or 1.0
    resultat = []
    for voix, duree in temps.items():
        if duree < minimum and not (reunion.noms.get(voix) or reunion.propositions.get(voix)):
            continue
        resultat.append(VoixANommer(
            voix=voix,
            duree=duree,
            part=duree / total,
            nom=reunion.noms.get(voix),
            proposition=reunion.propositions.get(voix),
            extrait=meilleur_extrait(reunion.intervalles_de(voix)),
        ))
    return resultat


def meilleur_extrait(intervalles: list[Intervalle]) -> Intervalle | None:
    """Le passage le plus représentatif à faire écouter.

    Le plus long tour de parole plutôt que le premier : un début de réunion
    commence souvent par un « oui, bonjour » qui ne dit rien du timbre.
    """
    utiles = [i for i in intervalles if i.duree >= DUREE_UTILE]
    if not utiles:
        utiles = intervalles
    if not utiles:
        return None
    plus_long = max(utiles, key=lambda i: i.duree)
    if plus_long.duree <= DUREE_EXTRAIT:
        return plus_long
    # Un peu après le début : on évite l'attaque, souvent hésitante.
    debut = plus_long.debut + min(1.0, (plus_long.duree - DUREE_EXTRAIT) / 2)
    return Intervalle(debut, debut + DUREE_EXTRAIT)


def extraire_audio(audio: Path, intervalle: Intervalle, destination: Path) -> Path:
    """Découpe un extrait, pour l'écouter."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{intervalle.debut:.3f}", "-t", f"{intervalle.duree:.3f}",
         "-i", str(audio), "-c:a", "pcm_s16le", str(destination)],
        check=True,
    )
    return destination


@dataclass
class Nommage:
    """Associe une voix à un nom, et fait entrer l'empreinte en banque."""

    depot: DepotFichiers
    banque: sortants.BanqueDeVoix
    extracteur: sortants.ExtracteurEmpreintes

    def nommer(self, identifiant: str, voix: str, nom: str) -> ReunionEnregistree:
        reunion = self.depot.lire(identifiant)
        intervalles = reunion.intervalles_de(voix)
        if not intervalles:
            raise KeyError(
                f"La voix « {voix} » n'existe pas dans cette réunion. "
                f"Voix connues : {', '.join(sorted(reunion.temps_de_parole()))}"
            )
        empreintes = self.extracteur.extraire_intervalles(reunion.audio, intervalles)
        if not empreintes:
            raise ValueError(
                f"La voix « {voix} » n'a aucun passage d'au moins {DUREE_UTILE:.0f} s : "
                "trop peu de matière pour une empreinte fiable."
            )
        # Une empreinte agrégée sur toute la réunion, et non un extrait unique :
        # elle résiste mieux aux variations de posture et de distance au micro.
        self.banque.enregistrer(nom, agreger(empreintes))

        reunion.noms[voix] = nom
        reunion.propositions.pop(voix, None)
        self.depot.enregistrer(reunion)
        return reunion

    def accepter_propositions(self, identifiant: str) -> dict[str, str]:
        """Valide d'un coup tous les noms devinés pendant la réunion.

        Pratique quand les propositions sont manifestement justes, mais c'est
        bien l'utilisateur qui décide : rien n'est validé sans ce geste.
        """
        reunion = self.depot.lire(identifiant)
        acceptes = dict(reunion.propositions)
        for voix, nom in acceptes.items():
            self.nommer(identifiant, voix, nom)
        return acceptes
