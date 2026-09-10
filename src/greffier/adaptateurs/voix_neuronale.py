"""Donner à l'assistant une voix qu'on écoute sans grincer des dents.

Les voix livrées d'office par les systèmes sont des synthétiseurs par
concaténation : elles disent les mots, mais l'oreille entend la machine à chaque
syllabe. Pour un outil qui prend la parole dans une réunion, c'est éliminatoire.

La synthèse est tenue par `sherpa-onnx` — **le moteur déjà présent** pour la
segmentation et les empreintes vocales. Aucune dépendance nouvelle, aucun appel
réseau, et un modèle que l'installeur télécharge comme il télécharge déjà ceux
de whisper.

Le modèle retenu est un VITS français, choisi **à l'écoute** contre trois
autres. Il gagne aussi sur les chiffres : quarante-huit fois le temps réel,
quatre secondes de parole calculées en huit centièmes, quatre-vingts
mégaoctets. Le multilingue Kokoro, qui servait d'abord, tenait cinq fois le
temps réel pour trois cent vingt-cinq mégaoctets — et s'entendait davantage.

Les deux familles restent acceptées, et se distinguent par un fichier : Kokoro
porte une table de voix, un VITS n'en a pas. Détecter plutôt que configurer,
parce que changer de modèle est une décision de qualité sonore et non de
programmation.

Deux détails décident du résultat :

- **la langue de phonémisation** doit être dite à Kokoro (`lang="fr"`, jamais
  `"fr-fr"`, qui échoue en silence). Sans elle, un texte français est découpé en
  phonèmes anglais et la voix prend un accent à couper au couteau. Un VITS
  français, lui, porte sa langue dans ses poids ;
- **on parle par phrases**. Générer tout le propos avant d'ouvrir la bouche
  fait attendre le temps de calcul du tout ; générer la première phrase pendant
  qu'on prononce, c'est la latence de la première phrase seule.
"""

from __future__ import annotations

import contextlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SYSTEME = platform.system()

#: La voix retenue dans le modèle, quand il en porte plusieurs.
#:
#: Pour Kokoro multilingue, c'est **30** : la seule française, les autres étant
#: anglaises, chinoises, japonaises, espagnoles, hindi, italiennes ou
#: portugaises, et leur donner du français produit un charabia phonétique. Pour
#: un VITS français mono-locuteur, c'est 0.
#:
#: Le défaut suit le modèle qu'installe l'installeur, et se règle dans
#: `assistant.locuteur` pour qui en change.
VOIX_FRANCAISE = 0

#: Le code espeak-ng du français est « fr », et non « fr-fr » : ce dernier fait
#: échouer la phonémisation en silence, et rien n'est prononcé du tout.
LANGUE_ESPEAK = {"fr": "fr", "en": "en-us", "es": "es", "it": "it", "pt": "pt"}

#: Un débit un peu sous la normale : on parle à des gens qui écoutent d'une
#: oreille, au milieu d'autre chose.
VITESSE = 0.95

#: Fins de phrase. On coupe là pour parler tôt, sans hacher le propos au milieu
#: d'une proposition — un point d'interrogation qui tombe dans le silence n'a
#: pas la même valeur qu'un souffle coupé.
FINS_DE_PHRASE = re.compile(r"(?<=[.!?…])\s+")

#: Les tirets n'ont pas de phonème : le modèle les signale un par un et les
#: ignore. On les remplace par une virgule, qui porte la même pause.
TIRETS = re.compile(r"\s*[—–-]\s*")


def nettoyer(texte: str) -> str:
    """Ce qui se prononce, débarrassé de ce qui ne se prononce pas."""
    sans_tirets = TIRETS.sub(", ", texte)
    return re.sub(r"\s+", " ", sans_tirets).strip()


def phrases(texte: str, maximum: int = 240) -> list[str]:
    """Découpe en morceaux prononçables, du plus tôt au plus tard.

    Une phrase trop longue est recoupée sur ses virgules : le but est de parler
    vite, et une période de quarante mots coûterait plusieurs secondes avant le
    premier son.
    """
    morceaux: list[str] = []
    for phrase in FINS_DE_PHRASE.split(nettoyer(texte)):
        phrase = phrase.strip()
        if not phrase:
            continue
        if len(phrase) <= maximum:
            morceaux.append(phrase)
            continue
        courant = ""
        for bout in phrase.split(", "):
            if courant and len(courant) + len(bout) + 2 > maximum:
                morceaux.append(courant)
                courant = bout
            else:
                courant = f"{courant}, {bout}" if courant else bout
        if courant:
            morceaux.append(courant)
    return morceaux


def _lecteur() -> list[str] | None:
    """La commande qui joue un fichier wav, selon le système."""
    if SYSTEME == "Darwin" and shutil.which("afplay"):
        return ["afplay"]
    for nom in ("paplay", "aplay", "ffplay"):
        chemin = shutil.which(nom)
        if chemin:
            return [chemin, "-nodisp", "-autoexit", "-loglevel", "error"] \
                if nom == "ffplay" else [chemin]
    if SYSTEME == "Windows" and shutil.which("powershell"):
        return ["powershell", "-NoProfile", "-Command"]
    return None


@contextlib.contextmanager
def _sans_bavardage() -> Iterator[None]:
    """Étouffe ce que la bibliothèque native écrit sur la sortie d'erreur.

    sherpa-onnx signale chaque caractère qu'il ne sait pas prononcer — un tiret,
    une apostrophe typographique — par une ligne en anglais mentionnant un point
    de code Unicode. Sept lignes pour une phrase, sans conséquence sur le son.
    C'est du C++ : `warnings` et `logging` n'y peuvent rien, seul le descripteur
    de fichier compte.
    """
    try:
        copie = os.dup(2)
    except OSError:
        yield
        return
    try:
        with open(os.devnull, "w") as puits:
            os.dup2(puits.fileno(), 2)
        yield
    finally:
        os.dup2(copie, 2)
        os.close(copie)


class VoixNeuronale:
    """Prononce un texte avec une voix neuronale, en local.

    Le modèle se charge à la première phrase et non à la construction : ouvrir
    la fenêtre ne doit pas coûter quatre-vingts mégaoctets à quelqu'un qui ne
    fera jamais parler l'assistant.
    """

    def __init__(self, dossier: Path, langue: str = "fr", voix: int = VOIX_FRANCAISE,
                 vitesse: float = VITESSE, fils: int = 4,
                 baillon: Path | None = None) -> None:
        #: Où déposer le numéro du processus qui joue le son.
        #:
        #: La fenêtre et la veille sont deux processus, et le bouton « couper »
        #: est dans la fenêtre : elle écrit un réglage que la veille ne relit
        #: qu'à la tranche suivante, soit jusqu'à quinze secondes plus tard.
        #: Mesuré en réunion — on appuie, elle continue de parler, et le bouton
        #: paraît cassé. Il l'était, du point de vue de qui appuie.
        #:
        #: Avec ce fichier, la fenêtre coupe le son elle-même, tout de suite, et
        #: le réglage suit à son rythme pour la suite.
        self.baillon = Path(baillon) if baillon else None
        self.dossier = Path(dossier)
        self.langue = langue
        self.voix = voix
        self.vitesse = vitesse
        self.fils = fils
        self._moteur = None
        self._verrou = threading.Lock()
        self._lecture: subprocess.Popen[bytes] | None = None
        self._interrompu = threading.Event()

    @property
    def installee(self) -> bool:
        """Un réseau et son vocabulaire suffisent, quelle que soit la famille."""
        return self._reseau.exists() and (self.dossier / "tokens.txt").exists()

    @property
    def disponible(self) -> bool:
        return self.installee and _lecteur() is not None

    def _charger(self) -> Any:
        """Monte le modèle présent, quelle que soit sa famille.

        Deux familles se posent au même endroit et se distinguent par un
        fichier : Kokoro porte une table de voix (`voices.bin`), un VITS n'en a
        pas. Détecter plutôt que configurer, parce que changer de modèle est une
        décision de qualité sonore, pas de programmation — et qu'un réglage de
        plus à tenir à jour serait un réglage de plus à se tromper.
        """
        if self._moteur is not None:
            return self._moteur
        import sherpa_onnx

        commun = {
            "tokens": str(self.dossier / "tokens.txt"),
            "data_dir": str(self.dossier / "espeak-ng-data"),
        }
        if self._table_des_voix.exists():
            modele = sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(self._reseau), voices=str(self._table_des_voix),
                    lang=LANGUE_ESPEAK.get(self.langue, self.langue), **commun,
                ),
                num_threads=self.fils,
            )
        else:
            # Un VITS porte sa langue dans ses poids : rien à lui dire.
            modele = sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(self._reseau), **commun),
                num_threads=self.fils,
            )
        configuration = sherpa_onnx.OfflineTtsConfig(model=modele)
        if not configuration.validate():
            raise RuntimeError("configuration de synthèse vocale invalide")
        self._moteur = sherpa_onnx.OfflineTts(configuration)
        return self._moteur

    @property
    def _table_des_voix(self) -> Path:
        return self.dossier / "voices.bin"

    @property
    def _reseau(self) -> Path:
        """Le fichier de poids. Nommé `model.onnx` chez Kokoro, autrement chez
        Piper — d'où la recherche plutôt qu'un nom en dur."""
        attendu = self.dossier / "model.onnx"
        if attendu.exists():
            return attendu
        return next(iter(sorted(self.dossier.glob("*.onnx"))), attendu)

    def fabriquer(self, texte: str, destination: Path) -> Path | None:
        """Écrit le texte parlé dans un fichier, sans le jouer.

        Sert aussi bien à `greffier lire` qu'aux essais : ce qui s'entend doit
        pouvoir s'écouter deux fois.
        """
        import soundfile

        propos = nettoyer(texte)
        if not propos:
            return None
        with _sans_bavardage():
            rendu = self._charger().generate(propos, sid=self.voix, speed=self.vitesse)
        if len(rendu.samples) == 0:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(destination), rendu.samples, rendu.sample_rate)
        return destination

    def dire(self, texte: str) -> bool:
        """Prononce le texte, phrase après phrase, en rendant la main aussitôt.

        La boucle qui suit la réunion appelle cette méthode : la faire attendre
        la fin du propos, ce sont dix secondes d'audio non transcrit.
        """
        morceaux = phrases(texte)
        if not morceaux or not self.disponible:
            return False
        self.se_taire()
        self._interrompu.clear()
        threading.Thread(target=self._prononcer, args=(morceaux,), daemon=True).start()
        return True

    def _prononcer(self, morceaux: list[str]) -> None:
        import soundfile

        with tempfile.TemporaryDirectory() as dossier:
            for rang, morceau in enumerate(morceaux):
                if self._interrompu.is_set():
                    return
                try:
                    with _sans_bavardage():
                        rendu = self._charger().generate(
                            morceau, sid=self.voix, speed=self.vitesse)
                except (RuntimeError, OSError):
                    return
                if len(rendu.samples) == 0:
                    continue
                fichier = Path(dossier) / f"{rang}.wav"
                soundfile.write(str(fichier), rendu.samples, rendu.sample_rate)
                if not self._jouer(fichier):
                    return

    def _jouer(self, fichier: Path) -> bool:
        """Joue un fichier et attend sa fin. Faux si on a été interrompu."""
        lecteur = _lecteur()
        if lecteur is None:
            return False
        commande = (
            [*lecteur, f"(New-Object Media.SoundPlayer '{fichier}').PlaySync()"]
            if lecteur[0] == "powershell" else [*lecteur, str(fichier)]
        )
        try:
            with self._verrou:
                if self._interrompu.is_set():
                    return False
                self._lecture = subprocess.Popen(
                    commande, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._publier_le_baillon(self._lecture.pid)
            code = self._lecture.wait()
        except OSError:
            return False
        finally:
            self._publier_le_baillon(None)
        if code is not None and code < 0:
            # Tué par un signal, donc coupé de l'extérieur : c'est le bouton de
            # la fenêtre, et il ne demande pas de sauter une phrase, il demande
            # le silence. Sans ce contrôle, la phrase en cours s'arrêtait et la
            # suivante repartait aussitôt — « elle s'arrête puis elle reprend »,
            # ce qui est pire que de ne pas s'arrêter.
            self._interrompu.set()
            return False
        return not self._interrompu.is_set()

    def _publier_le_baillon(self, pid: int | None) -> None:
        """Dit à qui veut couper quel processus joue le son.

        Écrit et effacé : un numéro qui traîne ferait tuer un processus qui
        n'est plus le nôtre, et sur un système qui recycle les numéros ce
        serait n'importe lequel.
        """
        if self.baillon is None:
            return
        with contextlib.suppress(OSError):
            if pid is None:
                self.baillon.unlink(missing_ok=True)
            else:
                self.baillon.parent.mkdir(parents=True, exist_ok=True)
                self.baillon.write_text(str(pid), encoding="utf-8")

    def parle(self) -> bool:
        with self._verrou:
            return self._lecture is not None and self._lecture.poll() is None

    def se_taire(self) -> None:
        """Coupe le propos en cours, phrases à venir comprises."""
        self._interrompu.set()
        with self._verrou:
            lecture, self._lecture = self._lecture, None
        if lecture is not None and lecture.poll() is None:
            lecture.terminate()
            try:
                lecture.wait(timeout=2)
            except subprocess.TimeoutExpired:
                lecture.kill()


def faire_taire(baillon: Path) -> bool:
    """Coupe le son en cours, depuis n'importe quel processus.

    Sert au bouton de la fenêtre, qui ne peut pas attendre que la veille relise
    son réglage. Rend faux quand il n'y avait rien à couper, ce qui est le cas
    courant.
    """
    import signal

    try:
        pid = int(baillon.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return False
    with contextlib.suppress(OSError):
        baillon.unlink(missing_ok=True)
    return True
