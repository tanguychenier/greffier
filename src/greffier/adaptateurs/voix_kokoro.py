"""Donner à l'assistant une voix qu'on écoute sans grincer des dents.

Les voix livrées d'office par les systèmes sont des synthétiseurs par
concaténation : elles disent les mots, mais l'oreille entend la machine à chaque
syllabe. Pour un outil qui prend la parole dans une réunion, c'est éliminatoire.

Kokoro est un modèle de synthèse neuronale de 82 millions de paramètres, tenu
par `sherpa-onnx` — **le moteur déjà présent** pour la segmentation et les
empreintes vocales. Aucune dépendance nouvelle, aucun appel réseau, et un
modèle que l'installeur télécharge comme il télécharge déjà ceux de whisper.
Mesuré sur ce poste : **4,9 fois le temps réel**, huit secondes de parole
calculées en une seconde et demie.

Deux détails décident du résultat :

- **la langue de phonémisation** doit être dite (`lang="fr"`). Sans elle, un
  texte français est découpé en phonèmes anglais et la voix prend un accent à
  couper au couteau, ce qui s'entend immédiatement ;
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

SYSTEME = platform.system()

#: La seule voix française du modèle multilingue (identifiant 30). Les autres
#: sont anglaises, chinoises, japonaises, espagnoles, hindi, italiennes ou
#: portugaises : leur donner du français produit un charabia phonétique.
VOIX_FRANCAISE = 30

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


class VoixKokoro:
    """Prononce un texte avec une voix neuronale, en local.

    Le modèle se charge à la première phrase et non à la construction : ouvrir
    la fenêtre ne doit pas coûter trois cent vingt-cinq mégaoctets à quelqu'un
    qui ne fera jamais parler l'assistant.
    """

    def __init__(self, dossier: Path, langue: str = "fr", voix: int = VOIX_FRANCAISE,
                 vitesse: float = VITESSE, fils: int = 4) -> None:
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
        return (self.dossier / "model.onnx").exists() and (
            self.dossier / "voices.bin").exists()

    @property
    def disponible(self) -> bool:
        return self.installee and _lecteur() is not None

    def _charger(self):
        if self._moteur is not None:
            return self._moteur
        import sherpa_onnx

        configuration = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(self.dossier / "model.onnx"),
                    voices=str(self.dossier / "voices.bin"),
                    tokens=str(self.dossier / "tokens.txt"),
                    data_dir=str(self.dossier / "espeak-ng-data"),
                    lang=LANGUE_ESPEAK.get(self.langue, self.langue),
                ),
                num_threads=self.fils,
            ),
        )
        if not configuration.validate():
            raise RuntimeError("configuration de synthèse vocale invalide")
        self._moteur = sherpa_onnx.OfflineTts(configuration)
        return self._moteur

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
            self._lecture.wait()
        except OSError:
            return False
        return not self._interrompu.is_set()

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
