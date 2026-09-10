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

SYSTEM = platform.system()

VOIX_FRANCAISE = 0

LANGUE_ESPEAK = {"fr": "fr", "en": "en-us", "es": "es", "it": "it", "pt": "pt"}

RATE = 0.95

FINS_DE_PHRASE = re.compile(r"(?<=[.!?…])\s+")

TIRETS = re.compile(r"\s*[—–-]\s*")

def clean(text: str) -> str:
    """Ce qui se prononce, débarrassé de ce qui ne se prononce pas."""
    sans_tirets = TIRETS.sub(", ", text)
    return re.sub(r"\s+", " ", sans_tirets).strip()

def sentences(text: str, maximum: int = 240) -> list[str]:
    """Découpe en morceaux prononçables, du plus tôt au plus tard.

    Une phrase trop longue est recoupée sur ses virgules : le but est de parler
    vite, et une période de quarante mots coûterait plusieurs secondes avant le
    premier son.
    """
    chunks: list[str] = []
    for phrase in FINS_DE_PHRASE.split(clean(text)):
        phrase = phrase.strip()
        if not phrase:
            continue
        if len(phrase) <= maximum:
            chunks.append(phrase)
            continue
        current = ""
        for bout in phrase.split(", "):
            if current and len(current) + len(bout) + 2 > maximum:
                chunks.append(current)
                current = bout
            else:
                current = f"{current}, {bout}" if current else bout
        if current:
            chunks.append(current)
    return chunks

def _player() -> list[str] | None:
    """La commande qui joue un fichier wav, selon le système."""
    if SYSTEM == "Darwin" and shutil.which("afplay"):
        return ["afplay"]
    for name in ("paplay", "aplay", "ffplay"):
        path = shutil.which(name)
        if path:
            return [path, "-nodisp", "-autoexit", "-loglevel", "error"] \
                if name == "ffplay" else [path]
    if SYSTEM == "Windows" and shutil.which("powershell"):
        return ["powershell", "-NoProfile", "-Command"]
    return None

@contextlib.contextmanager
def _without_chatter() -> Iterator[None]:
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

class NeuralVoice:
    """Prononce un texte avec une voix neuronale, en local.

    Le modèle se charge à la première phrase et non à la construction : ouvrir
    la fenêtre ne doit pas coûter quatre-vingts mégaoctets à quelqu'un qui ne
    fera jamais parler l'assistant.
    """

    def __init__(self, folder: Path, language: str = "fr", voice: int = VOIX_FRANCAISE,
                 rate: float = RATE, fils: int = 4,
                 gag: Path | None = None) -> None:
        self.gag = Path(gag) if gag else None
        self.folder = Path(folder)
        self.language = language
        self.voice = voice
        self.rate = rate
        self.fils = fils
        self._engine = None
        self._verrou = threading.Lock()
        self._lecture: subprocess.Popen[bytes] | None = None
        self._interrompu = threading.Event()

    @property
    def installed(self) -> bool:
        """Un réseau et son vocabulaire suffisent, quelle que soit la famille."""
        return self._network.exists() and (self.folder / "tokens.txt").exists()

    @property
    def available(self) -> bool:
        return self.installed and _player() is not None

    def _load(self) -> Any:
        """Monte le modèle présent, quelle que soit sa famille.

        Deux familles se posent au même endroit et se distinguent par un
        fichier : Kokoro porte une table de voix (`voices.bin`), un VITS n'en a
        pas. Détecter plutôt que configurer, parce que changer de modèle est une
        décision de qualité sonore, pas de programmation — et qu'un réglage de
        plus à tenir à jour serait un réglage de plus à se tromper.
        """
        if self._engine is not None:
            return self._engine
        import sherpa_onnx

        commun = {
            "tokens": str(self.folder / "tokens.txt"),
            "data_dir": str(self.folder / "espeak-ng-data"),
        }
        if self._voice_table.exists():
            model = sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(self._network), voices=str(self._voice_table),
                    lang=LANGUE_ESPEAK.get(self.language, self.language), **commun,
                ),
                num_threads=self.fils,
            )
        else:
            model = sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(self._network), **commun),
                num_threads=self.fils,
            )
        configuration = sherpa_onnx.OfflineTtsConfig(model=model)
        if not configuration.validate():
            raise RuntimeError("configuration de synthèse vocale invalide")
        self._engine = sherpa_onnx.OfflineTts(configuration)
        return self._engine

    @property
    def _voice_table(self) -> Path:
        return self.folder / "voices.bin"

    @property
    def _network(self) -> Path:
        """Le fichier de poids. Nommé `model.onnx` chez Kokoro, autrement chez
        Piper — d'où la recherche plutôt qu'un nom en dur."""
        attendu = self.folder / "model.onnx"
        if attendu.exists():
            return attendu
        return next(iter(sorted(self.folder.glob("*.onnx"))), attendu)

    def fabriquer(self, text: str, destination: Path) -> Path | None:
        """Écrit le texte parlé dans un fichier, sans le jouer.

        Sert aussi bien à `greffier lire` qu'aux essais : ce qui s'entend doit
        pouvoir s'écouter deux fois.
        """
        import soundfile

        remark = clean(text)
        if not remark:
            return None
        with _without_chatter():
            rendered = self._load().generate(remark, sid=self.voice, speed=self.rate)
        if len(rendered.samples) == 0:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(destination), rendered.samples, rendered.sample_rate)
        return destination

    def say(self, text: str) -> bool:
        """Prononce le texte, phrase après phrase, en rendant la main aussitôt.

        La boucle qui suit la réunion appelle cette méthode : la faire attendre
        la fin du propos, ce sont dix secondes d'audio non transcrit.
        """
        chunks = sentences(text)
        if not chunks or not self.available:
            return False
        self.go_quiet()
        self._interrompu.clear()
        threading.Thread(target=self._pronounce, args=(chunks,), daemon=True).start()
        return True

    def _pronounce(self, chunks: list[str]) -> None:
        import soundfile

        with tempfile.TemporaryDirectory() as folder:
            for rank, morceau in enumerate(chunks):
                if self._interrompu.is_set():
                    return
                try:
                    with _without_chatter():
                        rendered = self._load().generate(
                            morceau, sid=self.voice, speed=self.rate)
                except (RuntimeError, OSError):
                    return
                if len(rendered.samples) == 0:
                    continue
                file = Path(folder) / f"{rank}.wav"
                soundfile.write(str(file), rendered.samples, rendered.sample_rate)
                if not self._play(file):
                    return

    def _play(self, file: Path) -> bool:
        """Joue un fichier et attend sa fin. Faux si on a été interrompu."""
        player = _player()
        if player is None:
            return False
        command = (
            [*player, f"(New-Object Media.SoundPlayer '{file}').PlaySync()"]
            if player[0] == "powershell" else [*player, str(file)]
        )
        try:
            with self._verrou:
                if self._interrompu.is_set():
                    return False
                self._lecture = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._publish_the_gag(self._lecture.pid)
            code = self._lecture.wait()
        except OSError:
            return False
        finally:
            self._publish_the_gag(None)
        if code is not None and code < 0:
            self._interrompu.set()
            return False
        return not self._interrompu.is_set()

    def _publish_the_gag(self, pid: int | None) -> None:
        """Dit à qui veut couper quel processus joue le son.

        Écrit et effacé : un numéro qui traîne ferait tuer un processus qui
        n'est plus le nôtre, et sur un système qui recycle les numéros ce
        serait n'importe lequel.
        """
        if self.gag is None:
            return
        with contextlib.suppress(OSError):
            if pid is None:
                self.gag.unlink(missing_ok=True)
            else:
                self.gag.parent.mkdir(parents=True, exist_ok=True)
                self.gag.write_text(str(pid), encoding="utf-8")

    def is_speaking(self) -> bool:
        with self._verrou:
            return self._lecture is not None and self._lecture.poll() is None

    def go_quiet(self) -> None:
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

def silence(gag: Path) -> bool:
    """Coupe le son en cours, depuis n'importe quel processus.

    Sert au bouton de la fenêtre, qui ne peut pas attendre que la veille relise
    son réglage. Rend faux quand il n'y avait rien à couper, ce qui est le cas
    courant.
    """
    import signal

    try:
        pid = int(gag.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return False
    with contextlib.suppress(OSError):
        gag.unlink(missing_ok=True)
    return True
