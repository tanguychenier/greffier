"""Ce que l'outil sait du milieu où la réunion se tient.

Une transcription automatique ne perd pas les mots courants, elle perd les noms
propres et les acronymes : ils ne figurent nulle part dans ce qu'un modèle a
appris, donc il rend le mot le plus proche qu'il connaît. Mesuré sur la réunion
du 2026-09-09 : « déploiement » rendu « exploitement », « emploi du temps »
rendu « emploi fictif », « comptes rendus » rendu « prochains délits ». Aucun
réglage de modèle ne corrige ça — ces mots doivent lui être dits.

Le contexte sert **trois** étages, et c'est la raison d'être de ce module : la
transcription en direct, la transcription définitive et la rédaction. Les tenir
en un seul endroit évite de renseigner trois fois la même chose et de les
laisser diverger — le vocabulaire ne servait auparavant que la transcription
définitive, si bien que le direct devinait des termes que l'outil connaissait.

Ce module ne lit aucun fichier et ne connaît ni whisper ni le rédacteur : il
compose des textes. C'est ce qui permet de vérifier les règles de troncature
sans charger un modèle.
"""

from __future__ import annotations

from dataclasses import dataclass

AMORCE_MAXIMUM = 850

_PREAMBULE = "Réunion de travail."

@dataclass(frozen=True, slots=True)
class Terme:
    """Un mot que le modèle ne peut pas deviner : sigle, produit, nom propre.

    `sens` n'aide pas la transcription — le transcripteur ne raisonne pas — mais
    il évite au rédacteur de laisser un sigle nu dans un document lu par des
    absents. Les deux étages ont besoin de la même entrée pour des raisons
    différentes, ce qui est précisément pourquoi elle est unique.
    """

    ecriture: str
    sens: str = ""

    def __post_init__(self) -> None:
        if not self.ecriture.strip():
            raise ValueError("un terme sans écriture ne sert à rien")

    @property
    def gloss(self) -> str:
        """« OTP (mot de passe à usage unique) », ou « OTP » si le sens manque."""
        return f"{self.ecriture} ({self.sens})" if self.sens else self.ecriture

@dataclass(frozen=True, slots=True)
class Intervenant:
    """Quelqu'un dont le nom se prononce en réunion.

    Le rôle sert le rédacteur : « Sophie, cheffe de projet » lui permet de
    rattacher une position à une fonction sans l'inventer. Il ne sert pas la
    reconnaissance des voix, qui repose sur le timbre et non sur une liste.
    """

    name: str
    role: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("un intervenant sans nom ne sert à rien")

    @property
    def gloss(self) -> str:
        return f"{self.name} ({self.role})" if self.role else self.name

@dataclass(frozen=True, slots=True)
class Contexte:
    """Le glossaire et l'annuaire d'un milieu de travail.

    Immuable et fusionnable : le contexte du poste se complète de celui qu'on
    fournit pour une réunion précise, sans que l'un écrase l'autre.
    """

    termes: tuple[Terme, ...] = ()
    intervenants: tuple[Intervenant, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.termes and not self.intervenants

    def join(self, autre: Contexte) -> Contexte:
        """Ce contexte, complété par `autre`, qui l'emporte à égalité de nom.

        L'ordre compte : ce qui est fourni pour une réunion précise est plus
        juste que le glossaire général du poste, qui vieillit.
        """
        termes = {t.ecriture.casefold(): t for t in self.termes}
        termes.update({t.ecriture.casefold(): t for t in autre.termes})
        gens = {i.name.casefold(): i for i in self.intervenants}
        gens.update({i.name.casefold(): i for i in autre.intervenants})
        return Contexte(tuple(termes.values()), tuple(gens.values()))

    # ------------------------------------------------------ vers les étages

    def prompt_seed(self) -> str:
        """L'amorce du transcripteur : des écritures, sans leur sens.

        Les noms des intervenants y figurent au même titre que les termes : un
        prénom mal transcrit ne se rattrape pas plus tard, et c'est lui qui
        décide de l'attribution des tours de parole.

        Tronquée à `AMORCE_MAXIMUM` sur une frontière de terme, jamais au
        milieu d'un mot : une écriture coupée en deux apprend au modèle une
        orthographe fausse, ce qui est pire que de l'omettre.
        """
        words = [t.ecriture for t in self.termes] + [i.name for i in self.intervenants]
        retenus = _hold(words, AMORCE_MAXIMUM - len(_PREAMBULE) - len(" Vocabulaire : ."))
        if not retenus:
            return ""
        return f"{_PREAMBULE} Vocabulaire : " + ", ".join(retenus) + "."

    def ecartes(self) -> tuple[str, ...]:
        """Les termes que l'amorce n'a pas pu emporter, pour le dire.

        whisper tronque sans prévenir. Rendre la liste permet à l'appelant
        d'avertir au lieu de laisser un glossaire à moitié pris.
        """
        words = [t.ecriture for t in self.termes] + [i.name for i in self.intervenants]
        retenus = set(_hold(words, AMORCE_MAXIMUM - len(_PREAMBULE) - len(" Vocabulaire : .")))
        return tuple(m for m in words if m not in retenus)

    def header(self) -> str:
        """Le glossaire dicté au rédacteur, sens compris.

        Sans limite de longueur, à la différence de l'amorce : le rédacteur lit
        un contexte, il n'est pas amorcé par lui. En revanche il lui est dit de
        ne pas s'en servir comme d'un ordre du jour — un glossaire cité en
        entier dans un compte rendu le rend illisible, et laisse croire que
        chaque terme a été abordé.
        """
        if self.empty:
            return ""
        lines = ["[Contexte du milieu de travail]"]
        if self.termes:
            lines.append(
                "Termes et sigles employés dans cette organisation, avec leur sens. "
                "Emploie ces écritures, y compris là où la transcription les a "
                "manifestement déformés. N'en cite que ceux dont il est question :"
            )
            lines += [f"- {t.gloss}" for t in self.termes]
        if self.intervenants:
            lines.append(
                "Personnes de cette organisation. N'attribue une position à "
                "quelqu'un que si la transcription le montre, jamais d'après son rôle :"
            )
            lines += [f"- {i.gloss}" for i in self.intervenants]
        return "\n".join(lines) + "\n\n"

def _hold(words: list[str], place: int) -> list[str]:
    """Les premiers `mots` qui tiennent dans `place` caractères, séparateurs compris."""
    retenus: list[str] = []
    length = 0
    for mot in dict.fromkeys(m for m in words if m.strip()):
        ajout = len(mot) + (2 if retenus else 0)
        if length + ajout > place:
            continue
        retenus.append(mot)
        length += ajout
    return retenus
