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

import json
import platform
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from greffier.application.suivre import TRANCHE_MINIMALE_S, Position, Suivi
from greffier.domaine.instructions import Proposition, Veille
from greffier.domaine.modeles import Intervalle, Replique
from greffier.ports import sortants

SYSTEME = platform.system()

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
    periode_tranche: float = PERIODE_TRANCHE
    #: Jusqu'où la transcription au fil de l'eau est allée, en secondes de
    #: réunion. Ce qui précède a déjà été lu — et affiché.
    traite: float = 0.0
    #: Dernière taille d'audio observée, pour savoir si la capture avance.
    vu: float | None = None

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
        # Deux versions de la même tranche, et c'est nécessaire : la
        # transcription veut un mélange équilibré, l'attribution veut les
        # niveaux **relatifs** intacts, puisque c'est l'écart entre le micro et
        # la boucle qui dit qui parle. Normaliser avant d'attribuer ferait
        # passer tout le monde pour la personne qui enregistre.
        a_transcrire = tranche
        if self.preparateur is not None:
            a_transcrire = self.preparateur.preparer_transcription(
                tranche, travail / "tranche-niveau.wav"
            )
        try:
            repliques = self.transcripteur.transcrire(a_transcrire, self.langue, "")
        except (RuntimeError, OSError):
            # Une tranche ratée ne doit pas interrompre la veille : la réunion
            # continue, et la transcription définitive se fera à la fin.
            return []
        self.traite = ou.decalage + ou.ecrit
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
        return nouvelles

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
