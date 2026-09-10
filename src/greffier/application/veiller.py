"""Veiller pendant la réunion, sans jamais agir seul.

Deux boucles de rythmes différents, parce que les deux sources n'ont pas le même
coût : le presse-papier se relit en quelques millisecondes, la transcription
d'une tranche demande plusieurs secondes de calcul.

Rien n'est exécuté. Les propositions s'accumulent dans un fichier que
l'interface lit et présente ; c'est un humain qui déclenche. Une action lancée
seule sur une phrase mal transcrite, au milieu d'une réunion confidentielle, se
retourne vite contre son auteur.
"""

from __future__ import annotations

import contextlib
import json
import platform
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from greffier.application.participer import Participant
from greffier.application.suivre import TRANCHE_MINIMALE_S, Position, Suivi
from greffier.domaine.instructions import Proposition, Veille
from greffier.domaine.modeles import Intervalle, Replique
from greffier.domaine.participation import Occasion, Raison
from greffier.ports import sortants

SYSTEME = platform.system()

#: Les raisons de parler qui appellent une réponse. Répondre à quelqu'un
#: n'attend rien en retour, et un remerciement clôt l'échange ; poser une
#: question de soi-même laisse une phrase en suspens, et rester muet quand on y
#: répond fait passer pour distrait.
ATTENDENT_UNE_REPONSE = frozenset({
    Raison.VOIX_INDISTINCTE,
    Raison.DECISION_SANS_SUITE,
    Raison.QUESTION_SANS_REPONSE,
    Raison.ECART_AVEC_UN_DOCUMENT,
    Raison.APPORT,
})

# Le presse-papier est gratuit à relire : on le fait souvent, pour que le lien
# collé apparaisse pendant qu'on en parle encore.
PERIODE_PRESSE_PAPIER = 2.0
# Une tranche de transcription coûte plusieurs secondes de calcul. Trop souvent,
# on prend du temps machine à la réunion elle-même.
PERIODE_TRANCHE = 30.0
# Recouvrement entre deux tranches : une phrase à cheval doit rester entière
# dans au moins l'une des deux.
RECOUVREMENT = 5.0
# Une tranche ratée est reprise à la suivante, avec un peu plus de matière. Sans
# borne, un échec durable — modèle absent, fichier illisible — la ferait grandir
# jusqu'à demander plusieurs minutes de calcul à chaque tour.
TRANCHE_MAXIMALE = 90.0
# Secondes d'audio **déjà transcrit** données en plus au modèle, avant la
# tranche. Rien n'en est réaffiché : c'est du contexte, et il change tout.
#
# Mesuré le 2026-09-09 sur une réunion en présentiel, même passage, même modèle,
# seule la longueur de la fenêtre changeant : à 15 s « sur la ZIS », à 30 s
# « sur Asis », à 60 s « sur Oasis » — le mot juste, et la phrase entière avec.
# Whisper décode par fenêtres de 30 s en reportant le texte de la précédente en
# contexte : ne lui donner que la tranche, c'est le priver de ce sur quoi il
# s'appuie, et il comble avec ce qui ressemble.
#
# Le coût tient dans le budget : 0,9 s pour 15 s d'audio, 1,4 s pour 60 s avec
# huit fils, pour une tranche qui en dure dix.
CONTEXTE_S = 50.0


def _dans_la_tranche(repliques: list[Replique], frontiere: float) -> list[Replique]:
    """Ne garde que ce qui déborde dans la tranche, remis à l'heure de celle-ci.

    Une réplique entièrement dans le contexte a déjà été affichée : la
    réafficher doublerait chaque phrase. Une réplique à cheval est gardée
    entière — le texte déjà montré en sera retiré à l'affichage, ce qui vaut
    mieux que de couper une phrase au milieu.
    """
    if frontiere <= 0:
        return repliques
    gardees = []
    for replique in repliques:
        if replique.intervalle.fin <= frontiere:
            continue
        gardees.append(Replique(
            intervalle=Intervalle(
                max(0.0, replique.intervalle.debut - frontiere),
                replique.intervalle.fin - frontiere,
            ),
            texte=replique.texte, voix=replique.voix, source=replique.source,
        ))
    return gardees


def lire_presse_papier() -> str:
    """Contenu du presse-papier, ou vide si le système ne le donne pas."""
    commandes = {
        "Darwin": ["pbpaste"],
        "Linux": (["wl-paste"] if _existe("wl-paste")
                  else ["xclip", "-o", "-selection", "clipboard"]),
        "Windows": ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
    }
    commande = commandes.get(SYSTEME)
    if not commande:
        return ""
    try:
        return subprocess.run(
            commande, capture_output=True, text=True, check=False, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _existe(programme: str) -> bool:
    import shutil

    return shutil.which(programme) is not None


def extraire_tranche(audio: Path, debut: float, fin: float, destination: Path) -> Path | None:
    """Découpe un morceau d'un enregistrement **en cours d'écriture**.

    ffmpeg lit sans gêner l'écriture : c'est ce qui permet de transcrire une
    réunion pendant qu'elle a lieu, sans toucher au fichier qui s'écrit.
    """
    if not audio.exists() or audio.stat().st_size < 1024:
        return None
    resultat = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{debut:.2f}", "-t", f"{fin - debut:.2f}",
         "-i", str(audio), "-c:a", "pcm_s16le", str(destination)],
        capture_output=True, check=False,
    )
    if resultat.returncode != 0 or not destination.exists():
        return None
    return destination if destination.stat().st_size > 1024 else None


@dataclass
class Veilleur:
    """Fait tourner la veille tant que la réunion est enregistrée."""

    veille: Veille
    journal: Path
    transcripteur: sortants.Transcripteur | None = None
    #: Où en est l'enregistrement, d'après les octets réellement écrits. Une
    #: fonction et non un chemin : l'enregistrement change de morceau dès qu'on
    #: met en pause ou qu'on branche un casque.
    situer: Callable[[], Position | None] | None = None
    #: Le fil affiché pendant la réunion. Absent, la veille se contente de
    #: relever les propositions, comme avant.
    suivi: Suivi | None = None
    #: Met les canaux de la tranche à niveau avant de la transcrire. Sans lui, la
    #: voix la plus faible du mélange est **omise ou inventée** — le défaut qui
    #: avait coûté treize minutes de parole au premier compte rendu réel, et qui
    #: se reproduisait ici : à l'essai, une question sur six n'était pas
    #: transcrite du tout, celle de la personne au micro.
    preparateur: sortants.Enregistreur | None = None
    langue: str = "fr"
    #: Repère les termes que la transcription a probablement déformés et dépose
    #: la question. Facultatif : sans lui, le direct fonctionne comme avant.
    interroger: Callable[[str], None] | None = None
    #: Le vocabulaire donné au modèle du direct. Vide, il devinait les sigles et
    #: les prénoms que l'outil connaissait pourtant : l'amorce n'était câblée
    #: que sur la transcription définitive, si bien que le fil affichait
    #: « l'exploitement » là où le compte rendu, lui, écrivait « déploiement ».
    #: Or c'est le direct qu'on lit pendant la réunion, et c'est là qu'on
    #: corrige.
    amorce: str = ""
    #: Relit le contexte, pour que l'amorce suive **pendant** la réunion.
    #: Sans cela, un terme appris en cours de route ne servait qu'à la réunion
    #: suivante : le processus du direct avait figé son amorce au démarrage, et
    #: c'est justement en réunion qu'on découvre les mots qui manquent.
    relire_l_amorce: Callable[[], str] | None = None
    #: L'assistant, quand il participe à la réunion. Absent, la veille est ce
    #: qu'elle a toujours été : elle écoute et n'ouvre pas la bouche.
    participant: Participant | None = None
    #: Relit si l'assistant participe toujours, et s'il a la parole. La fenêtre
    #: et la veille sont deux processus : les boutons écrivent dans la
    #: configuration, et c'est ici qu'on s'en aperçoit. Même mécanisme que pour
    #: l'amorce, et pour la même raison — on doit pouvoir le faire taire en
    #: pleine réunion, pas à la suivante.
    #:
    #: Rend le couple (participe, parle à voix haute). Les deux se règlent
    #: séparément : sans la voix, l'assistant pose toujours ses questions, mais
    #: dans la conversation.
    relire_la_participation: Callable[[], tuple[bool, bool]] | None = None
    #: De quoi rendre la parole à l'assistant quand on la lui redonne en cours
    #: de réunion. Construire une voix charge un modèle : on ne le fait qu'une
    #: fois, à la première demande.
    rendre_la_voix: Callable[[], Any] | None = None
    #: Matière au-delà de laquelle une voix sans nom mérite qu'on demande à qui
    #: elle est. Trente secondes : en deçà, c'est un « oui, d'accord » dont le
    #: compte rendu se passera, et interrompre pour cela serait ridicule.
    matiere_pour_demander: float = 30.0
    periode_tranche: float = PERIODE_TRANCHE
    #: Jusqu'où la transcription au fil de l'eau est allée, en secondes de
    #: réunion. Ce qui précède a déjà été lu — et affiché.
    traite: float = 0.0
    #: Dernière taille d'audio observée, pour savoir si la capture avance.
    vu: float | None = None

    def _amorce_courante(self) -> str:
        """L'amorce à donner à cette tranche, contexte relu s'il a changé.

        Relire un fichier toutes les dix secondes ne coûte rien mesurable, et
        c'est le prix pour qu'« ajoute OTP au contexte » serve à la phrase
        suivante et non à la réunion d'après. C'est en réunion qu'on découvre
        les mots qui manquent, donc c'est là que l'apprentissage doit porter.
        """
        if self.relire_l_amorce is None:
            return self.amorce
        try:
            fraiche = self.relire_l_amorce()
        except OSError:
            return self.amorce
        if fraiche and fraiche != self.amorce:
            self.amorce = fraiche
        return self.amorce

    def publier(self, nouvelles: list[Proposition]) -> None:
        """Ajoute au journal, une proposition par ligne.

        Un fichier en ajout plutôt qu'un fichier réécrit : l'interface peut le
        suivre au fil de l'eau, et une interruption ne perd rien de ce qui
        précède.
        """
        if not nouvelles:
            return
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8") as flux:
            for proposition in nouvelles:
                flux.write(json.dumps({
                    "genre": proposition.genre.value,
                    "texte": proposition.texte,
                    "instant": round(proposition.instant, 1),
                    "origine": proposition.origine.value,
                    "contexte": proposition.contexte,
                }, ensure_ascii=False) + "\n")

    def tour_presse_papier(self, instant: float) -> list[Proposition]:
        contenu = lire_presse_papier()
        nouvelles = self.veille.coller(contenu, instant) if contenu else []
        self.publier(nouvelles)
        return nouvelles

    def tour_transcription(self, ou: Position, travail: Path) -> list[Proposition]:
        """Transcrit ce qui a été enregistré depuis la dernière tranche.

        Le découpage se fait sur ce que le fichier **porte réellement**, jamais
        sur l'horloge : après une pause, les deux ont divergé de tout le temps
        d'arrêt, et lire à la position de l'horloge demandait à ffmpeg un passage
        au-delà de la fin du fichier — donc rien.
        """
        if self.transcripteur is None:
            return []
        debut = max(0.0, self.traite - ou.decalage - RECOUVREMENT, ou.ecrit - TRANCHE_MAXIMALE)
        if ou.ecrit - debut < TRANCHE_MINIMALE_S:
            return []
        tranche = extraire_tranche(ou.morceau, debut, ou.ecrit, travail / "tranche.wav")
        if tranche is None:
            return []
        # Le modèle reçoit la tranche **précédée** de ce qui a déjà été
        # transcrit ; seules les répliques qui débordent dans la tranche sont
        # gardées. Le reste n'est là que pour qu'il sache de quoi on parle.
        depart = max(0.0, debut - CONTEXTE_S)
        avec_contexte = tranche if depart >= debut else (
            extraire_tranche(ou.morceau, depart, ou.ecrit, travail / "fenetre.wav")
            or tranche
        )
        # Deux versions de la même tranche, et c'est nécessaire : la
        # transcription veut un mélange équilibré, l'attribution veut les
        # niveaux **relatifs** intacts, puisque c'est l'écart entre le micro et
        # la boucle qui dit qui parle. Normaliser avant d'attribuer ferait
        # passer tout le monde pour la personne qui enregistre.
        a_transcrire = avec_contexte
        if self.preparateur is not None:
            a_transcrire = self.preparateur.preparer_transcription(
                avec_contexte, travail / "tranche-niveau.wav"
            )
        try:
            repliques = self.transcripteur.transcrire(
                a_transcrire, self.langue, self._amorce_courante()
            )
        except (RuntimeError, OSError):
            # Une tranche ratée ne doit pas interrompre la veille : la réunion
            # continue, et la transcription définitive se fera à la fin.
            return []
        repliques = _dans_la_tranche(repliques, debut - depart)
        self.traite = ou.decalage + ou.ecrit
        # Pendant la réunion, sur ce qui vient d'être dit : après coup, une
        # question sur un terme mal entendu arrive trop tard pour que le compte
        # rendu en profite.
        if self.interroger is not None:
            for replique in repliques:
                with contextlib.suppress(OSError):
                    self.interroger(replique.texte)
        decalage = ou.decalage + debut
        # Les répliques sont datées dans la tranche : on les remet à l'heure de
        # la réunion, sinon les propositions renverraient au mauvais moment.
        recalees = [
            Replique(
                intervalle=Intervalle(
                    r.intervalle.debut + decalage, r.intervalle.fin + decalage
                ),
                texte=r.texte, voix=r.voix, source=r.source,
            )
            for r in repliques
        ]
        nouvelles = self.veille.ecouter(recalees)
        self.publier(nouvelles)
        if self.suivi is not None:
            # Le fil affiché reçoit la tranche elle-même : l'empreinte vocale se
            # prélève dedans, aux temps de la tranche.
            self.suivi.accueillir(tranche, repliques, decalage)
        self.tour_assistant(recalees, self.traite)
        return nouvelles

    def tour_assistant(self, repliques: list[Replique], maintenant: float) -> None:
        """Laisse l'assistant décider s'il a quelque chose à dire, et le dire.

        Après l'affichage, jamais avant : ce qui se dit doit être visible même
        quand l'assistant se tait, ce qui est le cas la plupart du temps.
        """
        if self.participant is None:
            return
        if self.relire_la_participation is not None:
            with contextlib.suppress(OSError):
                self._appliquer_les_boutons(*self.relire_la_participation())
        retenue = self.participant.tour(
            repliques, maintenant,
            tours=self._bornes_des_tours(),
            occasions=self._voix_a_demander(maintenant),
        )
        if retenue is None:
            # Rien à dire maintenant : on en profite pour chercher s'il y aura
            # quelque chose à dire tout à l'heure. La recherche coûte un appel
            # au modèle, donc elle se fait à côté et son résultat sert à la
            # tranche suivante.
            self.participant.chercher_un_apport_a_part(maintenant)
            return
        if retenue.raison in ATTENDENT_UNE_REPONSE:
            # On retient la question posée : c'est ce qui permet à la réponse
            # d'être comprise comme une réponse, et pas comme une phrase de plus.
            # Répondre à quelqu'un n'attend rien en retour ; poser une question
            # de soi-même, si.
            self.participant.attente = retenue
        self.participant.repondre_a_part(retenue, maintenant)

    def _appliquer_les_boutons(self, participe: bool, a_voix_haute: bool) -> None:
        """Suit les deux boutons de la fenêtre, sans redémarrer quoi que ce soit.

        Se taire est immédiat, phrase en cours comprise : appuyer sur le bouton
        pendant qu'il parle doit l'interrompre, pas attendre la fin de sa
        tirade. Reprendre la parole ne coûte le chargement du modèle qu'une
        fois, et seulement si on la lui redonne.
        """
        if self.participant is None:
            return
        lui = self.participant
        if participe != lui.politique.actif:
            lui.politique.actif = participe
            if not participe and lui.voix is not None:
                lui.voix.se_taire()
        if not a_voix_haute and lui.voix is not None:
            lui.voix.se_taire()
            lui.voix = None
        elif a_voix_haute and lui.voix is None and self.rendre_la_voix is not None:
            lui.voix = self.rendre_la_voix()

    def _bornes_des_tours(self) -> list[tuple[float, float]]:
        """Les tours de parole affichés, pour mesurer la densité de la discussion."""
        if self.suivi is None:
            return []
        return [(t.intervalle.debut, t.intervalle.fin) for t in self.suivi.fil.tours]

    def _voix_a_demander(self, maintenant: float) -> list[Occasion]:
        """Une voix qui a parlé longtemps sans qu'on sache de qui elle est.

        C'est le défaut le plus coûteux de l'outil : elle deviendra
        « Personne 12 » dans le compte rendu, et plus personne ne saura la
        reconnaître. La demander sur le moment coûte une phrase et vaut un nom.
        """
        if self.suivi is None or self.participant is None:
            return []
        for voix in self.suivi.fil.voix.values():
            if (voix.nom is None and voix.nommable
                    and voix.secondes >= self.matiere_pour_demander):
                return [self.participant.demander_qui_parle(voix.identifiant, maintenant)]
        return []

    def boucler(
        self,
        encore: Callable[[], bool],
        depuis: Callable[[], float],
        travail: Path,
        pause: Callable[[float], None] = time.sleep,
    ) -> list[Proposition]:
        """Tourne jusqu'à la fin de l'enregistrement.

        Les deux rythmes sont gérés dans une seule boucle : deux fils
        d'exécution pour ça compliqueraient l'arrêt sans rien apporter.

        `depuis` donne l'heure de la réunion, pour horodater les liens collés.
        Le rythme des tranches, lui, suit l'audio écrit : en pause, rien ne
        s'ajoute au fichier, donc rien n'est transcrit — et la reprise repart où
        la capture s'était arrêtée.
        """
        while encore():
            self.tour_presse_papier(depuis())
            ou = self.situer() if self.situer is not None else None
            if ou is not None and self._est_temps(ou):
                self.tour_transcription(ou, travail)
            pause(PERIODE_PRESSE_PAPIER)
        self.derniere_passe(travail)
        return self.veille.propositions

    def derniere_passe(self, travail: Path) -> list[Proposition]:
        """Transcrit ce qui restait quand la réunion s'est arrêtée.

        Il reste toujours jusqu'à une période d'audio non lue : sans cette
        passe, on finit sa phrase devant un fil qui s'arrête avant elle. Le
        fichier visé est alors celui que l'arrêt vient de recoller, où les temps
        sont déjà ceux de la réunion.
        """
        ou = self.situer() if self.situer is not None else None
        if ou is None or ou.globale - self.traite < TRANCHE_MINIMALE_S:
            return []
        return self.tour_transcription(ou, travail)

    def _est_temps(self, ou: Position) -> bool:
        """Faut-il transcrire maintenant ?

        Deux cas. Le rythme ordinaire : assez d'audio s'est ajouté. Et le
        rattrapage, quand le fichier **ne grandit plus** — mise en pause, ou fin
        de la réunion : sans lui, les dernières secondes de chaque prise de
        parole ne s'affichaient jamais, et l'on finissait sa phrase devant un fil
        qui s'arrêtait avant elle.
        """
        avance = ou.globale - self.traite
        stagne = self.vu is not None and abs(ou.ecrit - self.vu) < 0.05
        self.vu = ou.ecrit
        if avance >= self.periode_tranche:
            return True
        return stagne and avance >= TRANCHE_MINIMALE_S
