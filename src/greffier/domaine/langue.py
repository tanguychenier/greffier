"""La langue d'une réunion, et ce qu'elle change dans le domaine.

Jusqu'ici la langue n'existait qu'à un endroit — le code passé au modèle de
transcription — et le reste du domaine était français en dur : les motifs qui
reconnaissent un prénom, les mots à ne jamais prendre pour tel, les génériques
que le modèle invente sur un silence, les tournures qui annoncent une décision.

Le laisser ainsi n'était pas neutre. Les motifs français ne se taisent pas sur
une réunion anglaise, ils **fabriquent des participants** : mesuré sur les vraies
fonctions, « Budget, on the other hand, is not settled. » rend « Budget », et
« Anyway, on Monday we ship. » rend « Anyway », parce que le motif attend une
adresse en « tu », « vous » ou « on » et que « on » est aussi un mot anglais.
Pendant ce temps, « I'm Lise and I'm the project manager. » ne rend rien. Une
vraie réunion à quatre en donnait six.

Un profil rassemble donc ce qu'une langue décide, et le domaine le reçoit en
paramètre plutôt que de le supposer. Une langue sans profil éprouvé reçoit
`NEUTRE`, dont la détection est éteinte : les voix restent à nommer à la main,
ce qui vaut mieux que des noms inventés.

Rien de Greffier ici, ni ports ni adaptateurs : un profil se lit et se teste
sans audio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from greffier.domaine.modeles import TypeMention

#: Un motif de reconnaissance : ce qu'il désigne, comment il s'écrit, et s'il
#: n'est qu'une confirmation. Un motif de confirmation est trop large pour
#: établir un prénom à lui seul ; il ne compte que sur un nom déjà repéré.
Motif = tuple[TypeMention, "re.Pattern[str]", bool]


@dataclass(frozen=True, slots=True)
class Detection:
    """Comment reconnaître un prénom prononcé, dans une langue donnée.

    `active` à faux éteint la détection entièrement. Ce n'est pas un aveu de
    paresse : laisser tourner les motifs d'une autre langue ne rate pas des
    prénoms, il en invente.
    """

    active: bool
    motifs: tuple[Motif, ...] = ()
    exclus: frozenset[str] = frozenset()
    #: En deçà, un mot est trop court pour être un prénom distinctif.
    longueur_minimale: int = 3
    #: Suffixe adverbial à écarter, et longueur à partir de laquelle l'écarter.
    #: Vide : la langue n'a pas de règle de ce genre.
    suffixe_adverbial: str = ""
    longueur_du_suffixe: int = 0


@dataclass(frozen=True, slots=True)
class Decoupage:
    """Comment cette langue sépare ses mots.

    Le chinois, le japonais et le thaï n'insèrent pas d'espace entre les mots :
    compter les espaces y rend un ou deux, une transcription valable est prise
    pour vide, et la chaîne s'interrompt avant de rédiger. Les trois sont déjà
    proposés dans la liste des langues de la fenêtre.
    """

    mots_separes_par_des_espaces: bool = True

    def compter(self, texte: str) -> int:
        """Le nombre de mots, ou de caractères là où la notion n'existe pas."""
        if self.mots_separes_par_des_espaces:
            return len(texte.split())
        return len(texte.replace(" ", ""))


@dataclass(frozen=True, slots=True)
class Redaction:
    """Ce que la langue change à la lecture de ce qui a été dit.

    Les génériques sont les phrases que le modèle invente sur un signal faible
    — « Sous-titrage réalisé par… » — et qui n'ont été prononcées par personne.
    """

    generiques: frozenset[str] = frozenset()
    motifs_de_decision: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True, slots=True)
class ProfilLinguistique:
    """Tout ce qu'une langue décide, en un objet que le domaine reçoit."""

    code: str
    nom: str
    detection: Detection
    decoupage: Decoupage = field(default_factory=Decoupage)
    redaction: Redaction = field(default_factory=Redaction)

    @property
    def eprouve(self) -> bool:
        """Si ce profil a de quoi reconnaître les prénoms de sa langue.

        Ce qui distingue une langue servie d'une langue simplement acceptée, et
        ce que l'interface doit dire plutôt que de le laisser croire.
        """
        return self.detection.active
