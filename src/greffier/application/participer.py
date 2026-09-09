"""Faire de l'assistant un participant, et non un micro posé sur la table.

Ce module assemble trois choses que le reste du projet fournit déjà : ce qui se
dit (le fil du direct), une règle qui décide s'il vaut la peine de parler
(`domaine.participation`), et de quoi formuler puis prononcer. Il n'en connaît
aucune : tout arrive par des ports, ce qui permet d'éprouver le comportement
sans lancer de réunion, sans modèle et sans son.

Le tour de force n'est pas de parler, c'est de se taire. Un assistant vocal
ordinaire répond dès qu'on lui laisse un blanc ; en réunion, cela revient à
couper la parole toutes les dix secondes. La règle de `Politique` fait le tri,
et ce module ne fait qu'appliquer sa décision.

Un cycle complet, celui qui vaut d'exister :

    l'assistant   « Je n'arrive plus à distinguer deux voix. Qui vient de parler ? »
    quelqu'un     « c'est Marcel »
    l'assistant   « Merci, c'est noté : je mets Marcel sur cette voix. »

La réponse ne se perd pas dans le fil : elle **nomme la voix**, donc elle sert
au compte rendu et à la banque, ce qui est tout l'intérêt d'avoir demandé.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from greffier.domaine.modeles import Replique
from greffier.domaine.participation import (
    Occasion,
    Politique,
    Raison,
    appelee,
    densite_de_parole,
    question_posee,
)

#: Comment l'assistant s'exprime quand il parle dans la pièce. Court, oral, sans
#: plan : ce qui suit est prononcé, pas lu. Le contraire d'un compte rendu.
CONSIGNES_ORALES = """Tu t'appelles {nom} et tu participes à une réunion de
travail. On t'entend par un haut-parleur : ce que tu écris sera prononcé tel
quel, à voix haute, devant les participants.

Réponds en **une à deux phrases**. Jamais de liste, de titre, de tableau, de
Markdown, d'URL ni de parenthèse : rien de tout cela ne s'entend. Pas de
préambule, pas de « bien sûr », pas de formule d'attente.

Tu parles à des gens qui sont en train de travailler. Si tu n'as pas la réponse
dans ce qui a été dit, dis-le en une phrase plutôt que de meubler. Si on ne te
posait pas vraiment de question, dis-le brièvement et rends la parole.

N'emploie ni tiret cadratin ni demi-cadratin.
"""

#: Ce qu'on lui remet du fil avant sa réponse. Assez pour comprendre de quoi on
#: parle, pas au point de faire un appel long au milieu d'une réunion.
CONTEXTE_MAXIMAL = 6000


class Parleur(Protocol):
    """Ce qui prononce. `VoixKokoro` et `VoixSysteme` s'y conforment."""

    def dire(self, texte: str) -> bool:
        ...

    def se_taire(self) -> None:
        ...

    def parle(self) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class Intervention:
    """Ce que l'assistant a dit, et pourquoi."""

    propos: str
    raison: Raison
    a: float
    prononce: bool = False


@dataclass
class Participant:
    """Écoute la réunion, et y prend la parole quand cela vaut la peine."""

    nom: str = "Greffier"
    politique: Politique = field(default_factory=Politique)
    #: Prononce. Absent, l'assistant participe **par écrit** dans le fil : c'est
    #: le mode par défaut, et il reste utile — tout le monde ne veut pas d'une
    #: voix dans la pièce.
    voix: Parleur | None = None
    #: Formule le propos. Absent, l'assistant ne dit que ce qu'il sait dire
    #: sans réfléchir : demander qui parle, par exemple, ce qui est déjà
    #: l'essentiel de ce qu'il a à demander.
    cerveau: Any | None = None
    #: Ce qui a été dit jusque-là, pour que la réponse tienne compte du sujet.
    contexte: Callable[[], str] | None = None
    #: Écrit dans la conversation de la fenêtre, pour qu'il reste une trace de
    #: ce qui a été dit à voix haute.
    tracer: Callable[[str, str], None] | None = None
    #: Ce que l'assistant attend : la question qu'il vient de poser. La phrase
    #: suivante lui répond, et il en accuse réception.
    attente: Occasion | None = None
    #: Appelé quand la réponse à « qui parle ? » donne un prénom. C'est ce qui
    #: transforme une question polie en un nom porté au compte rendu.
    nommer: Callable[[str, str], bool] | None = None
    #: Les instants où l'assistant a parlé, pour ne pas se transcrire lui-même.
    #: Sa voix sort par le haut-parleur et rentre par le micro : sans cela, il
    #: deviendrait un participant de plus, avec une empreinte vocale à la clé.
    ses_prises: list[tuple[float, float]] = field(default_factory=list)
    _travail: threading.Thread | None = None

    # --------------------------------------------------------------- écoute

    def tour(
        self,
        repliques: list[Replique],
        maintenant: float,
        tours: list[tuple[float, float]] | None = None,
        occasions: list[Occasion] | None = None,
    ) -> Occasion | None:
        """Ce que l'assistant retient de cette tranche, ou rien.

        Rien est le cas courant et c'est voulu : sur une réunion d'une heure,
        cette fonction rendra `None` la quasi-totalité du temps.
        """
        proposees = list(occasions or [])
        for replique in repliques:
            texte = replique.texte.strip()
            if not texte or self._est_de_lui(replique):
                continue
            if self.attente is not None:
                accuse = self._accuser_reception(texte, replique.intervalle.fin)
                if accuse is not None:
                    return accuse
            if appelee(texte, self.nom):
                proposees.append(Occasion(
                    raison=Raison.APPELE,
                    propos=question_posee(texte, self.nom) or texte,
                    ne_le=replique.intervalle.fin,
                ))
        creux = self._creux(repliques, maintenant)
        densite = densite_de_parole(tours or [], maintenant) if tours else 0.0
        return self.politique.choisir(proposees, maintenant, creux, densite)

    def _est_de_lui(self, replique: Replique) -> bool:
        """La réplique tombe-t-elle sur un moment où l'assistant parlait ?

        Il s'entend par le micro de la salle comme tout le monde. Se relire
        soi-même, c'est se répondre, et c'est aussi se donner une voix dans le
        compte rendu.
        """
        debut, fin = replique.intervalle.debut, replique.intervalle.fin
        return any(
            min(fin, sa_fin) - max(debut, son_debut) > 0.5 * (fin - debut)
            for son_debut, sa_fin in self.ses_prises
        )

    def _creux(self, repliques: list[Replique], maintenant: float) -> float:
        """Depuis combien de temps plus personne ne parle."""
        if not repliques:
            return maintenant
        return max(0.0, maintenant - max(r.intervalle.fin for r in repliques))

    def _accuser_reception(self, texte: str, a: float) -> Occasion | None:
        """Traite la phrase qui répond à la question posée.

        Une question posée et jamais reprise vaut moins que pas de question :
        elle a coûté une interruption pour rien.
        """
        attendue, self.attente = self.attente, None
        if attendue is None or attendue.raison is not Raison.VOIX_INDISTINCTE:
            return None
        prenom = _prenom_dans(texte)
        voix = attendue.sujet.removeprefix("voix:")
        if prenom and self.nommer is not None and self.nommer(voix, prenom):
            return Occasion(
                raison=Raison.APPELE,
                propos=f"Merci, c'est noté : je mets {prenom} sur cette voix.",
                ne_le=a,
                sujet=f"merci:{voix}",
            )
        return None

    # ---------------------------------------------------------------- parole

    def repondre(self, occasion: Occasion, maintenant: float) -> Intervention:
        """Formule puis prononce. Bloquant : voir `repondre_a_part`."""
        propos = self._formuler(occasion)
        if not propos:
            return Intervention(propos="", raison=occasion.raison, a=maintenant)
        prononce = bool(self.voix and self.voix.dire(propos))
        if prononce:
            # Une seconde par quinze caractères : le débit de la synthèse, à la
            # louche. Ce qui compte est de couvrir le temps où il s'entend, pas
            # de le mesurer au millième.
            self.ses_prises.append((maintenant, maintenant + 1.0 + len(propos) / 15.0))
        self.politique.a_parle(occasion, maintenant)
        if self.tracer is not None:
            with contextlib.suppress(OSError):
                self.tracer(self.nom.lower(), propos)
        return Intervention(propos=propos, raison=occasion.raison, a=maintenant,
                            prononce=prononce)

    def repondre_a_part(self, occasion: Occasion, maintenant: float) -> None:
        """Répond dans un fil séparé, pour ne pas retarder la transcription.

        Formuler demande un appel au modèle, donc plusieurs secondes. Les passer
        à attendre, c'est autant d'audio non transcrit, et le direct ne rattrape
        jamais son retard.
        """
        if self._travail is not None and self._travail.is_alive():
            return
        self._travail = threading.Thread(
            target=self.repondre, args=(occasion, maintenant), daemon=True)
        self._travail.start()

    def _formuler(self, occasion: Occasion) -> str:
        """Le propos exact à prononcer.

        Ce que l'assistant sait dire seul, il le dit seul : demander qui parle
        n'a pas besoin d'un modèle, et faire dépendre cette question d'un appel
        distant la rendrait lente et faillible là où elle doit être immédiate.
        """
        if occasion.raison is not Raison.APPELE or self.cerveau is None:
            return occasion.propos
        matiere = ""
        if self.contexte is not None:
            with contextlib.suppress(OSError):
                matiere = self.contexte()[-CONTEXTE_MAXIMAL:]
        demande = (
            f"Voici ce qui s'est dit jusqu'ici dans la réunion :\n\n{matiere}\n\n"
            f"On vient de te dire : « {occasion.propos} »\n\nRéponds."
        )
        try:
            return self.cerveau.rediger(demande).strip()
        except (RuntimeError, OSError):
            return ""

    def demander_qui_parle(self, voix: str, maintenant: float) -> Occasion:
        """La question qui règle le problème le plus coûteux de l'outil.

        Une voix non identifiée devient « Personne 12 » dans le compte rendu, et
        personne ne la reconnaîtra après coup. La demander sur le moment coûte
        une phrase et vaut un nom.
        """
        return Occasion(
            raison=Raison.VOIX_INDISTINCTE,
            propos="Excusez-moi, je n'arrive pas à situer la voix qui vient de "
                   "parler. Est-ce que cette personne peut dire son prénom ?",
            ne_le=maintenant,
            sujet=f"voix:{voix}",
        )

    def consignes(self) -> str:
        return CONSIGNES_ORALES.format(nom=self.nom)


def _prenom_dans(texte: str) -> str:
    """Le prénom d'une réponse du genre « c'est Marcel » ou « Marcel ».

    Volontairement simple : la réponse à « qui vient de parler » est courte, et
    tout mot qui n'est pas un mot-outil y est un prénom. Une réponse alambiquée
    ne donnera rien, ce qui vaut mieux que de nommer une voix « Alors ».
    """
    import re

    outils = {
        "c", "ce", "cette", "est", "c'est", "moi", "c'était", "etait", "était",
        "la", "le", "les", "de", "du", "des", "je", "suis", "s", "il", "elle",
        "on", "a", "ah", "eh", "ben", "bah", "oui", "non", "et", "que", "qui",
        "voix", "personne", "sais", "pas", "alors", "donc", "là", "ici", "là-bas",
    }
    mots = [m for m in re.findall(r"[\w'-]+", texte, flags=re.UNICODE) if m]
    candidats = [m for m in mots if m.lower().strip("'") not in outils and len(m) > 2]
    if len(candidats) != 1:
        return ""
    return candidats[0].strip("'").capitalize()
