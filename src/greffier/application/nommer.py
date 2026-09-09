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
from dataclasses import dataclass, replace
from pathlib import Path

from greffier.domaine import empreintes as empreintes_domaine
from greffier.domaine import prenoms
from greffier.domaine.empreintes import agreger
from greffier.domaine.modeles import Intervalle
from greffier.domaine.reunion import ReunionEnregistree
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

    depot: sortants.DepotReunions
    banque: sortants.BanqueDeVoix
    extracteur: sortants.ExtracteurEmpreintes
    #: Ce que le dernier nommage a de suspect, en clair. Vide quand tout va
    #: bien. L'appelant l'affiche : c'est le seul moment où l'utilisateur peut
    #: encore se raviser sans effort.
    doute: str = ""

    def nommer(self, identifiant: str, voix: str, nom: str) -> ReunionEnregistree:
        """Pose un nom sur une voix, et réunit celles qui portent déjà ce nom.

        Réunir, parce que c'est le geste qu'on fait sans le savoir : nommer
        « Michel » une deuxième voix, c'est dire qu'elle est de Michel, donc de
        la même personne. Sans cela, chaque voix gardait son identifiant et le
        compte rendu annonçait deux Michel — sur une réunion réelle, trente-six
        voix ont été nommées à la main pour trois personnes présentes.
        """
        refuse = prenoms.refus(nom)
        if refuse:
            raise ValueError(refuse)
        nom = prenoms.normaliser(nom)
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
        # Avant de verser : cette voix ressemble-t-elle à quelqu'un d'autre ?
        # On ne refuse pas — deux collègues peuvent avoir des voix proches, et
        # l'utilisateur a le droit d'avoir raison contre la machine — mais on
        # ne laisse plus une entrée fausse entrer en silence.
        # L'origine voyage avec l'empreinte : c'est ce qui permettra de
        # défaire d'un geste ce qu'une réunion mal attribuée a versé.
        agregat = replace(agreger(empreintes), origine=identifiant)
        self.doute = empreintes_domaine.entree_douteuse(
            agregat, nom, self.banque.personnes())
        self.banque.enregistrer(nom, agregat)

        reunion.noms[voix] = nom
        reunion.propositions.pop(voix, None)
        # Les voix qui portaient déjà ce nom rejoignent celle-ci. La plus
        # fournie garde son identifiant : c'est celle dont l'extrait est le plus
        # représentatif si quelqu'un veut réécouter.
        temps = reunion.temps_de_parole()
        homonymes = [v for v in reunion.voix_portant(nom) if v != voix]
        for autre in homonymes:
            gardee, absorbee = (
                (voix, autre) if temps.get(voix, 0.0) >= temps.get(autre, 0.0)
                else (autre, voix)
            )
            reunion.reunir(absorbee, gardee)
            reunion.noms[gardee] = nom
            voix = gardee
        self.depot.enregistrer(reunion)
        return reunion

    def oublier(self, identifiant: str, voix: str) -> ReunionEnregistree:
        """Retire le nom d'une voix, dans la réunion.

        Une erreur de nommage est le geste le plus coûteux de l'outil, et il
        n'était pas défaisable : on ne pouvait que renommer par-dessus, ce qui
        ajoutait une empreinte fausse à la banque au lieu d'en retirer une.
        Ici, la réunion oublie ; la banque se corrige avec `greffier connus`,
        qui montre déjà les entrées douteuses.
        """
        reunion = self.depot.lire(identifiant)
        if voix not in reunion.noms and voix not in reunion.propositions:
            raise KeyError(f"La voix « {voix} » ne porte aucun nom.")
        reunion.noms.pop(voix, None)
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
