"""Reconnaître une voix d'une réunion à l'autre.

Le modèle acoustique rend, pour chaque extrait de parole, un vecteur de
quelques centaines de nombres. Deux extraits de la même personne donnent des
vecteurs proches ; de deux personnes différentes, des vecteurs éloignés. Tout
ce module tient dans cette phrase — et dans la prudence qu'elle impose : la
proximité n'est jamais une preuve, seulement un degré de confiance.

Volontairement sans numpy. Les vecteurs font quelques centaines de nombres et
les comparaisons se comptent en dizaines : le calcul est instantané en Python
pur, et le domaine reste testable sans rien installer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from greffier.domaine.modeles import Empreinte, Personne

# Seuils mesurés sur une réunion réelle en salle (2026-08-20, 11,8 min, ~6
# personnes, micro de portable). Sur les segments exacts de la diarisation, en
# ne gardant que les extraits d'au moins 3 s :
#
#   deux extraits d'une même voix     médiane 0,74   (0,62 à 0,79)
#   deux voix différentes             médiane 0,41   (jusqu'à 0,66)
#
# D'où 0,70 : au-dessus du pire cas de voix distinctes, au niveau du cas courant
# d'une même voix. La valeur de 0,55 initialement retenue au jugé laissait passer
# des confusions. À reprendre si le matériel ou l'acoustique changent.
SEUIL_RECONNAISSANCE = 0.70
# Un écart minimal avec le second : deux collègues aux voix proches doivent
# produire une hésitation, pas un choix arbitraire.
MARGE_MINIMALE = 0.06
# Au sein d'une même réunion, les conditions d'enregistrement sont identiques :
# on peut donc exiger davantage pour décider que deux groupes de segments sont
# la même personne. La segmentation automatique sur-découpe beaucoup — 27 voix
# relevées pour 6 participants réels — et sans ce recollage le compte rendu
# invente des participants.
SEUIL_FUSION = 0.75
# Au-delà, garder des empreintes supplémentaires n'apporte plus rien et fige la
# banque sur les premières réunions enregistrées.
EMPREINTES_PAR_PERSONNE = 8
# Un agrégat tiré de peu de matière est bruité : sur un jeu d'essai à trois
# locuteurs synthétiques, deux petits groupes récents ont franchi SEUIL_FUSION
# par accident statistique, ramenant trois voix à deux. La garde ne s'applique
# qu'au plus grand des deux groupes candidats : une voix déjà établie continue
# d'absorber des fragments minces sans contrainte nouvelle, seuls deux petits
# groupes encore fragiles ne peuvent plus se fondre entre eux sur ce hasard.
MATIERE_MINIMALE_FUSION = 6.0


def normaliser(vecteur: Sequence[float], duree_source: float = 0.0) -> Empreinte:
    """Ramène le vecteur à une longueur de 1.

    La comparaison se réduit alors à un produit scalaire, et deux extraits
    enregistrés à des volumes différents ne passent plus pour deux personnes.
    """
    norme = math.sqrt(math.fsum(x * x for x in vecteur))
    if norme == 0:
        raise ValueError("vecteur nul : extrait sans parole ?")
    return Empreinte(vecteur=tuple(x / norme for x in vecteur), duree_source=duree_source)


def similarite(a: Empreinte, b: Empreinte) -> float:
    """Cosinus entre deux empreintes normalisées, dans [-1, 1]."""
    if len(a.vecteur) != len(b.vecteur):
        raise ValueError(
            f"empreintes de tailles différentes : {len(a.vecteur)} et {len(b.vecteur)}"
        )
    return math.fsum(x * y for x, y in zip(a.vecteur, b.vecteur, strict=True))


def agreger(empreintes: Iterable[Empreinte]) -> Empreinte:
    """Empreinte moyenne d'une même voix, pondérée par la durée des extraits.

    Une voix parle par bribes tout au long de la réunion. Moyenner ces extraits
    en tenant compte de leur durée donne une signature plus stable qu'un seul
    passage — trois secondes de « oui, d'accord » ne pèsent pas autant qu'une
    minute d'explication.
    """
    liste = list(empreintes)
    if not liste:
        raise ValueError("aucune empreinte à agréger")
    taille = len(liste[0].vecteur)
    poids_total = math.fsum(max(e.duree_source, 1e-6) for e in liste)
    somme = [
        math.fsum(e.vecteur[i] * max(e.duree_source, 1e-6) for e in liste) / poids_total
        for i in range(taille)
    ]
    return normaliser(somme, duree_source=math.fsum(e.duree_source for e in liste))


@dataclass(frozen=True, slots=True)
class Correspondance:
    """Ce que la banque de voix croit reconnaître, et à quel point."""

    nom: str
    similarite: float
    marge: float          # écart avec la deuxième personne la plus proche

    @property
    def sure(self) -> bool:
        return self.similarite >= SEUIL_RECONNAISSANCE and self.marge >= MARGE_MINIMALE


def _score(empreinte: Empreinte, personne: Personne) -> float:
    """Proximité d'une empreinte avec une personne connue.

    On retient le meilleur de ses extraits, pas la moyenne : quelqu'un enregistré
    une fois au casque et une fois en salle a deux signatures assez différentes,
    et la moyenne des deux ne ressemblerait à aucune des deux.
    """
    return max((similarite(empreinte, connue) for connue in personne.empreintes), default=-1.0)


def noms_en_conflit(banque: Iterable[Personne]) -> dict[str, set[str]]:
    """Les noms de la banque qui portent la même voix, deux à deux.

    Un nommage erroné entre en banque comme un autre, et rien ne le distingue
    ensuite : la voix ainsi classée est reconnue sous ce nom à chaque réunion,
    affirmée plutôt que proposée, et l'erreur se confirme d'elle-même. Mesuré
    sur une banque réelle : deux entrées à **0,77** de ressemblance alors que
    deux personnes différentes s'y mesurent entre 0,22 et 0,53 — l'une des deux
    portait la voix de l'autre.

    Deux personnes distinctes ne peuvent pas franchir le seuil de
    reconnaissance : si elles le font, c'est qu'un nom est faux, et on ne sait
    pas lequel. Le savoir permet de se taire au lieu de choisir.
    """
    personnes = [p for p in banque if p.empreintes]
    agregats = {p.nom: agreger(p.empreintes) if len(p.empreintes) > 1 else p.empreintes[0]
                for p in personnes}
    conflits: dict[str, set[str]] = {}
    for i, un in enumerate(personnes):
        for autre in personnes[i + 1:]:
            if similarite(agregats[un.nom], agregats[autre.nom]) >= SEUIL_RECONNAISSANCE:
                conflits.setdefault(un.nom, set()).add(autre.nom)
                conflits.setdefault(autre.nom, set()).add(un.nom)
    return conflits


def reconnaitre(
    empreinte: Empreinte,
    banque: Iterable[Personne],
    seuil: float = SEUIL_RECONNAISSANCE,
    marge_minimale: float = MARGE_MINIMALE,
) -> Correspondance | None:
    """La personne de la banque qui correspond, ou rien si le doute subsiste.

    Renvoyer « rien » est un résultat normal et fréquent : une voix inconnue,
    un extrait trop court, deux voisins de timbre. L'appelant demandera alors
    à l'utilisateur, ce qui vaut mieux qu'un nom inventé dans un compte rendu.
    """
    # Matérialisée d'abord : la banque est parfois un générateur, et elle est
    # parcourue deux fois — le classement, puis le contrôle des conflits.
    connues = [p for p in banque if p.empreintes]
    classement = sorted(
        ((_score(empreinte, p), p.nom) for p in connues),
        key=lambda x: (-x[0], x[1]),
    )
    if not classement:
        return None
    meilleur, nom = classement[0]
    second = classement[1][0] if len(classement) > 1 else -1.0
    marge = meilleur - second
    if meilleur < seuil or marge < marge_minimale:
        return None
    # Un nom que la banque confond avec un autre ne vaut pas mieux qu'aucun nom.
    # La marge ne protège pas de ce cas : elle compare l'empreinte du jour aux
    # personnes connues, alors que le défaut est **entre** deux personnes
    # connues, et il rend justement la marge confortable.
    if nom in noms_en_conflit(connues):
        return None
    return Correspondance(nom=nom, similarite=meilleur, marge=marge)


def fusionner_voix(
    par_voix: dict[str, list[Empreinte]],
    seuil: float = SEUIL_FUSION,
) -> dict[str, str]:
    """Recolle les groupes de segments qui sont en réalité la même personne.

    La segmentation acoustique éclate volontiers une voix en plusieurs groupes :
    la personne change de posture, s'éloigne du micro, hausse le ton. On compare
    donc les empreintes agrégées de chaque groupe et on réunit les plus proches,
    de la paire la plus évidente à la moins évidente, en recalculant l'agrégat
    après chaque réunion — sans quoi une chaîne de rapprochements successifs
    finirait par rassembler des voix qui n'ont rien à voir.

    Renvoie la correspondance ancien groupe → groupe retenu. Les groupes non
    fusionnés s'y trouvent aussi, associés à eux-mêmes : l'appelant applique la
    correspondance sans avoir à distinguer les cas.
    """
    groupes = {voix: list(empreintes) for voix, empreintes in par_voix.items() if empreintes}
    appartenance = {voix: voix for voix in par_voix}

    while True:
        agregats = {voix: agreger(e) for voix, e in groupes.items()}
        noms = sorted(agregats)
        meilleure: tuple[float, str, str] | None = None
        for i, a in enumerate(noms):
            for b in noms[i + 1:]:
                score = similarite(agregats[a], agregats[b])
                matiere = max(
                    sum(e.duree_source for e in groupes[a]),
                    sum(e.duree_source for e in groupes[b]),
                )
                if (
                    score >= seuil
                    and matiere >= MATIERE_MINIMALE_FUSION
                    and (meilleure is None or score > meilleure[0])
                ):
                    meilleure = (score, a, b)
        if meilleure is None:
            break
        _, garde, absorbe = meilleure
        # Le groupe le plus fourni garde son nom : c'est celui que l'utilisateur
        # aura entendu le plus souvent s'il écoute un extrait.
        if sum(e.duree_source for e in groupes[absorbe]) > sum(
            e.duree_source for e in groupes[garde]
        ):
            garde, absorbe = absorbe, garde
        groupes[garde].extend(groupes.pop(absorbe))
        for voix, vers in appartenance.items():
            if vers == absorbe:
                appartenance[voix] = garde

    return appartenance


def enrichir(
    personne: Personne,
    nouvelle: Empreinte,
    maximum: int = EMPREINTES_PAR_PERSONNE,
) -> Personne:
    """Ajoute une empreinte à une personne connue, en bornant l'accumulation.

    Quand le quota est atteint, l'empreinte issue du plus court extrait cède sa
    place : ce sont les passages longs qui portent le mieux le timbre d'une voix.
    """
    personne.empreintes.append(nouvelle)
    if len(personne.empreintes) > maximum:
        personne.empreintes.sort(key=lambda e: -e.duree_source)
        del personne.empreintes[maximum:]
    personne.reunions += 1
    return personne
