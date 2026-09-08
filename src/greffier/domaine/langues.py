"""Les langues que Greffier accepte, et ce qu'il sait faire de chacune.

Une seule liste, parce qu'elle existait en trois exemplaires en puissance : la
fenêtre l'affiche, l'assistant la demande, l'installeur l'écrit. Trois copies
d'une même liste, c'est trois occasions qu'elles se contredisent.

Rien d'IO ici : des codes et des noms. C'est aussi ce qui permet à l'installeur
de la charger par chemin, avant que quoi que ce soit ne soit installé.

`eprouvee` distingue une langue **servie** d'une langue simplement acceptée.
Whisper en transcrit une centaine ; la reconnaissance des prénoms, elle, repose
sur des tournures relevées sur de vraies réunions, et il n'y en a que pour le
français. Le dire vaut mieux que le laisser croire : hors des langues éprouvées,
les motifs français n'échouent pas, ils inventent des participants.
"""

from __future__ import annotations

from greffier.domaine import profils

#: Code ISO, nom en français. Le vide vaut « reconnais-la toi-même », ce que
#: whisper fait très bien et qui sert aux réunions qui changent de langue.
LANGUES: tuple[tuple[str, str], ...] = (
    ("fr", "Français"), ("", "Détection automatique"), ("en", "Anglais"),
    ("es", "Espagnol"), ("de", "Allemand"), ("it", "Italien"),
    ("pt", "Portugais"), ("nl", "Néerlandais"), ("ca", "Catalan"),
    ("pl", "Polonais"), ("ro", "Roumain"), ("ru", "Russe"),
    ("tr", "Turc"), ("ar", "Arabe"), ("zh", "Chinois"), ("ja", "Japonais"),
)

_NOMS = dict(LANGUES)


def nom_de(code: str) -> str:
    """Le nom d'une langue, ou le code lui-même s'il n'est pas au catalogue."""
    return _NOMS.get(code, code)


def eprouvee(code: str) -> bool:
    """Si la reconnaissance des prénoms est réellement servie dans cette langue."""
    return profils.pour(code).eprouve


def libelle(code: str) -> str:
    """Ce qu'il faut afficher à côté d'une langue, sans euphémisme.

    Une langue non éprouvée n'est pas refusée : elle se transcrit et son compte
    rendu s'écrit. Ce qu'elle n'a pas, c'est la reconnaissance des prénoms — les
    voix restent « Personne N » et se nomment une fois dans l'onglet Voix.
    """
    nom = nom_de(code)
    if not code or eprouvee(code):
        return nom
    return f"{nom} — voix à nommer à la main"
