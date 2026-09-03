"""À qui donner une phrase transcrite, quand les deux découpes ne coïncident pas.

La transcription coupe à la phrase, la segmentation au changement de locuteur :
les deux ne tombent jamais aux mêmes instants. Le plus souvent une phrase tient
dans un seul tour de parole et l'attribution est évidente. Mais une phrase peut
**enjamber** un changement de locuteur — whisper étire alors ses horodatages sur
les deux tours — et la donner entière au plus bavard attribue à quelqu'un des
mots qu'il n'a pas dits.

En visio, le canal rattrapait ce cas : la provenance ne se trompe jamais, et
`canaux.soustraire` s'en servait déjà pour ne pas mélanger deux voix dans une
empreinte. Autour d'une table, il n'y a plus de canal, et rien ne protège.
Mesuré sur une réunion de table synthétisée : « Merci Pierre. On garde donc
jeudi… », dit par Jacques, attribué à Pierre parce que la phrase couvrait 61 %
du tour de Pierre.

Ce module ne connaît que des intervalles : ni modèle, ni fichier.
"""

from __future__ import annotations

from greffier.domaine.modeles import Intervalle, TourDeParole

#: Part du temps couvert que le tour meneur doit tenir pour qu'on lui donne la
#: phrase. Mesuré sur 29 répliques de cinq réunions synthétisées : 26 tiennent
#: 0,98 ou plus (24 à 1,00 exactement), et les 3 qui enjambent un changement de
#: locuteur tiennent 0,50, 0,52 et 0,61. Rien entre 0,62 et 0,97 : le seuil est
#: posé au milieu de cette bande vide, pas choisi au doigt mouillé.
PART_MINIMALE = 0.80


def temps_par_voix(intervalle: Intervalle, tours: list[TourDeParole]) -> dict[str, float]:
    """Combien de secondes chaque voix tient pendant cet intervalle."""
    cumuls: dict[str, float] = {}
    for tour in tours:
        commun = intervalle.recouvrement(tour.intervalle)
        if commun > 0:
            cumuls[tour.voix] = cumuls.get(tour.voix, 0.0) + commun
    return cumuls


def voix_de(
    intervalle: Intervalle,
    tours: list[TourDeParole],
    part_minimale: float = PART_MINIMALE,
) -> str | None:
    """La voix à qui donner cette phrase, ou `None` si elle est à cheval.

    Rendre `None` n'est pas un échec : la phrase garde son texte et son
    horodatage dans le compte rendu, elle ne désigne simplement personne. Se
    taire vaut mieux qu'attribuer à tort — c'est déjà la règle retenue pour une
    banque de voix qui se contredit.
    """
    cumuls = temps_par_voix(intervalle, tours)
    if not cumuls:
        return None
    total = sum(cumuls.values())
    meneur = max(cumuls, key=lambda voix: cumuls[voix])
    if total <= 0 or cumuls[meneur] / total < part_minimale:
        return None
    return meneur
