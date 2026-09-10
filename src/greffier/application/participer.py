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
    quelqu'un     « c'est Michel »
    l'assistant   « Merci, c'est noté : je mets Michel sur cette voix. »

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

CONTEXTE_MAXIMAL = 6000

RIEN = "RIEN"

CONSIGNES_SUITE = """Tu t'appelles {nom} et tu participes à une réunion. Tu as
posé une question, on vient de te répondre.

Si la réponse règle la question, dis-le en **une phrase courte** qui montre ce
que tu en as retenu, et rends la parole. Une phrase du genre « très bien, donc
c'est {exemple} qui s'en occupe » vaut mieux qu'un « merci » seul : elle prouve
que tu as compris, et elle laisse une trace juste dans le compte rendu.

Si la réponse ne règle rien et qu'une précision changerait le compte rendu,
demande-la, toujours en une phrase.

Sinon, réponds le mot {rien}, seul. C'est le cas si on t'a répondu à côté, si
la conversation est déjà repartie ailleurs, ou si tu n'aurais rien à ajouter
qu'une politesse : deux répliques de plus feraient de toi un participant de
trop.

Pas de liste, pas de titre, pas d'adresse web : ce sera prononcé tel quel.
N'emploie ni tiret cadratin ni demi-cadratin.

Ta question était : « {question} »
Ce qu'on vient de te répondre :
"""

CONSIGNES_APPORT = """Tu t'appelles {nom} et tu assistes à une réunion de travail
sans y avoir été invitée à parler. On te donne ce qui vient de se dire.

Ta réponse par défaut est le mot {rien}, seul, sans rien d'autre. C'est la
réponse juste dans la très grande majorité des cas : une réunion se tient très
bien sans commentaire, et une remarque de trop coûte plus cher que dix
remarques manquées.

Tu ne sors de ce silence que si l'une de ces trois choses est vraie, et
manifestement vraie :

- une décision a été prise sans que personne ne soit désigné pour la porter,
  ou sans échéance alors qu'elle en appelle une ;
- une question a été posée à la cantonade et la conversation est passée à
  autre chose sans y répondre ;
- ce qui vient d'être dit contredit un document qu'on t'a fourni, ou une
  décision prise plus tôt dans cette même réunion.

Tu ne dis rien pour : reformuler ce qui vient d'être dit, résumer, approuver,
signaler qu'un sujet est intéressant, proposer une méthode qu'on ne t'a pas
demandée, ou rappeler une bonne pratique générale.

Si tu parles, c'est **une phrase**, à l'oral, sans liste ni titre ni adresse
web : elle sera prononcée telle quelle dans la pièce. Pose la question, ne
fais pas la leçon. N'emploie ni tiret cadratin ni demi-cadratin.

Ce qui vient de se dire :
"""

class Parleur(Protocol):
    """Ce qui prononce. `VoixNeuronale` et `VoixSysteme` s'y conforment."""

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
    voix: Parleur | None = None
    cerveau: Any | None = None
    contexte: Callable[[], str] | None = None
    tracer: Callable[[str, str], None] | None = None
    attente: Occasion | None = None
    nommer: Callable[[str, str], bool] | None = None
    en_reserve: Occasion | None = None
    ses_prises: list[tuple[float, float]] = field(default_factory=list)
    _travail: threading.Thread | None = None
    _recherche: threading.Thread | None = None

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
        if self.en_reserve is not None:
            proposees.append(self.en_reserve)
        creux = self._creux(repliques, maintenant)
        densite = densite_de_parole(tours or [], maintenant) if tours else 0.0
        retenue = self.politique.choisir(proposees, maintenant, creux, densite)
        if retenue is not None and retenue is self.en_reserve:
            self.en_reserve = None
        return retenue

    def chercher_un_apport_a_part(self, maintenant: float) -> None:
        """Cherche, dans un fil séparé, s'il y a lieu de dire quelque chose.

        À côté de la boucle qui transcrit : l'appel au modèle prend plusieurs
        secondes, et les passer à attendre coûterait autant d'audio non
        transcrit. Le résultat attend en réserve et sert à la tranche suivante.
        """
        if self.en_reserve is not None or not self.politique.actif:
            return
        if self._recherche is not None and self._recherche.is_alive():
            return

        def chercher() -> None:
            self.en_reserve = self.apport(maintenant)

        self._recherche = threading.Thread(target=chercher, daemon=True)
        self._recherche.start()

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
        elle a coûté une interruption pour rien, et celui qui a répondu ne sait
        pas s'il a été entendu.
        """
        attendue, self.attente = self.attente, None
        if attendue is None:
            return None
        if attendue.raison is Raison.VOIX_INDISTINCTE:
            return self._nommer_sur_reponse(attendue, texte, a)
        return self._suivre_sa_question(attendue, texte, a)

    def _nommer_sur_reponse(
        self, attendue: Occasion, texte: str, a: float
    ) -> Occasion | None:
        """« C'est Hugo » devient un nom porté au compte rendu."""
        prenom = _prenom_dans(texte)
        voix = attendue.sujet.removeprefix("voix:")
        if prenom and self.nommer is not None and self.nommer(voix, prenom):
            return Occasion(
                raison=Raison.APPELE,
                propos=f"Merci, c'est noté : je mets {prenom} sur cette voix.",
                ne_le=a,
                sujet=f"merci:{voix}",
                tel_quel=True,
            )
        return None

    def _suivre_sa_question(
        self, attendue: Occasion, texte: str, a: float
    ) -> Occasion | None:
        """Réagit à la réponse qu'on vient de lui faire, ou se tait.

        C'est ce qui sépare un échange d'une question jetée : « très bien, donc
        c'est Hugo qui s'en occupe » prouve qu'elle a compris et laisse une
        trace juste dans le compte rendu. Le silence reste proposé par défaut :
        deux répliques de plus feraient d'elle un participant de trop.
        """
        if self.cerveau is None:
            return None
        consignes = CONSIGNES_SUITE.format(
            nom=self.nom, rien=RIEN, question=attendue.propos, exemple="Hugo")
        try:
            propos = self._interroger(consignes, texte)
        except (RuntimeError, OSError):
            return None
        if not propos or propos.strip().upper().startswith(RIEN):
            return None
        suite = Occasion(
            raison=Raison.APPELE,
            propos=propos,
            ne_le=a,
            sujet=f"suite:{attendue.sujet or _empreinte_du_propos(attendue.propos)}",
            tel_quel=True,
        )
        # Tant qu'elle pose des questions, l'échange continue : c'est un
        # dialogue, pas un aller-retour. Elle s'arrête d'elle-même dès qu'elle
        # conclut plutôt que de demander — le point d'interrogation final est le
        # signal, et il vient d'elle, non d'un compteur qui la couperait au
        # milieu d'un sujet.
        if propos.rstrip().endswith("?"):
            self.attente = suite
        return suite

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
        if occasion.tel_quel or occasion.raison is not Raison.APPELE:
            return occasion.propos
        if self.cerveau is None:
            return occasion.propos
        matiere = ""
        if self.contexte is not None:
            with contextlib.suppress(OSError):
                matiere = str(self.contexte())[-CONTEXTE_MAXIMAL:]
        demande = (
            f"Voici ce qui s'est dit jusqu'ici dans la réunion :\n\n{matiere}\n\n"
            f"On vient de te dire : « {occasion.propos} »\n\nRéponds."
        )
        try:
            return str(self.cerveau.rediger(demande)).strip()
        except (RuntimeError, OSError):
            return ""

    def apport(self, maintenant: float) -> Occasion | None:
        """Ce que l'assistant aurait à ajouter de lui-même, ou rien.

        Rien est le cas courant, et la consigne le dit crûment : un modèle à
        qui l'on demande « as-tu quelque chose à dire » trouve toujours quelque
        chose à dire, et c'est exactement le défaut qu'on cherche à éviter.
        La politique décidera ensuite si le moment s'y prête ; ici on décide
        seulement s'il y a matière.

        L'appel n'a lieu que quand le repos est écoulé : le demander à chaque
        tranche coûterait un appel toutes les dix secondes pour un silence.
        """
        if self.cerveau is None or self.contexte is None:
            return None
        if self.politique.parle_le is not None and (
                maintenant - self.politique.parle_le < self.politique.repos):
            return None
        try:
            matiere = str(self.contexte())[-CONTEXTE_MAXIMAL:]
        except OSError:
            return None
        if not matiere.strip():
            return None
        consignes = CONSIGNES_APPORT.format(nom=self.nom, rien=RIEN)
        try:
            propos = self._interroger(consignes, matiere)
        except (RuntimeError, OSError):
            return None
        if not propos or propos.strip().upper().startswith(RIEN):
            return None
        return Occasion(
            raison=Raison.APPORT,
            propos=propos,
            ne_le=maintenant,
            # Le sujet est le propos lui-même : deux remarques identiques ne se
            # disent pas deux fois, et une remarque déjà faite ne revient pas.
            sujet=f"apport:{_empreinte_du_propos(propos)}",
        )

    def _interroger(self, consignes: str, matiere: str) -> str:
        """Un appel au cerveau, avec des consignes qui ne sont pas les siennes.

        Le rédacteur porte les consignes de l'oral ; celles de l'apport sont
        différentes, et il ne faut pas que les poser laisse le rédacteur changé
        pour l'appel suivant.
        """
        cerveau = self.cerveau
        if cerveau is None:
            return ""
        avant = getattr(cerveau, "consignes_propres", None)
        try:
            if avant is not None:
                cerveau.consignes_propres = consignes
                return str(cerveau.rediger(matiere)).strip()
            return str(cerveau.rediger(consignes + matiere)).strip()
        finally:
            if avant is not None:
                cerveau.consignes_propres = avant

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
            tel_quel=True,
        )

    def consignes(self) -> str:
        return CONSIGNES_ORALES.format(nom=self.nom)

def _empreinte_du_propos(propos: str) -> str:
    """De quoi reconnaître une remarque déjà faite, aux mots près."""
    import hashlib
    import re

    mots = " ".join(sorted(set(re.findall(r"\w{4,}", propos.lower()))))
    return hashlib.sha256(mots.encode("utf-8")).hexdigest()[:12]

def _prenom_dans(texte: str) -> str:
    """Le prénom d'une réponse du genre « c'est Michel » ou « Michel ».

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
    return str(candidats[0]).strip("'").capitalize()
