"""Faire parler l'assistant, avec la voix du système et rien d'autre.

Aucun service distant n'est appelé : ce que l'assistant dit dans la réunion ne
sort pas du poste, ce qui est la moindre des choses pour un outil qui écoute
une salle. Anthropic n'expose d'ailleurs aucune API vocale — l'API Messages
accepte du texte, des images et des documents, pas du son — donc le mode vocal
de l'application web n'est pas réutilisable, et il ne le sera pas en le
souhaitant très fort.

Les trois systèmes savent parler sans qu'on installe rien :

- macOS : `say`, qui rend les mêmes voix qu'`AVSpeechSynthesizer` ;
- Linux : `spd-say` (speech-dispatcher) ou `espeak-ng` ;
- Windows : `System.Speech` par PowerShell, présent depuis toujours.

La qualité tient à la voix choisie, pas au programme qui la joue. macOS livre
des voix « compactes » qui sonnent robotiques et propose au téléchargement des
voix améliorées, autrement meilleures ; `meilleure_voix()` prend la meilleure
installée et `voix_amelioree_disponible()` dit s'il faut aller la chercher.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import threading

SYSTEM = platform.system()

QUALITES = ("Premium", "Enhanced")

COMPACTES_ACCEPTABLES = ("Thomas", "Amélie", "Audrey", "Aurelie")

DEBIT = 165

def _say_voice() -> list[tuple[str, str]]:
    """Les voix françaises que `say` connaît, avec leur nom exact."""
    if SYSTEM != "Darwin" or shutil.which("say") is None:
        return []
    try:
        output = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    voice = []
    for line in output.splitlines():
        # « Thomas (Premium)      fr_FR    # Bonjour… » : le nom peut contenir
        # des espaces et des parenthèses, la langue jamais.
        trouve = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if trouve and trouve.group(2).startswith("fr"):
            voice.append((trouve.group(1).strip(), trouve.group(2)))
    return voice

def best_voice() -> str | None:
    """Le nom de la meilleure voix française installée, ou rien.

    Rien n'est un résultat normal : sur un système sans voix française, mieux
    vaut laisser la synthèse choisir sa voix par défaut que d'en imposer une
    qui lirait le français avec un accent anglais.
    """
    voice = _say_voice()
    if not voice:
        return None
    for qualite in QUALITES:
        # fr_FR avant fr_CA : la réunion se tient en France, et l'accent
        # québécois, si agréable soit-il, distrait l'auditoire.
        for language in ("fr_FR", "fr_CA"):
            for name, cette_langue in voice:
                if f"({qualite})" in name and cette_langue == language:
                    return name
    for prefere in COMPACTES_ACCEPTABLES:
        for name, _ in voice:
            if name.split(" (")[0] == prefere:
                return name
    return voice[0][0]

def better_voice_available() -> bool:
    """Une voix neuronale est-elle installée ?

    Sert au diagnostic : sans elle, l'assistant parle, mais il s'entend. Le
    téléchargement se fait dans Réglages Système ▸ Accessibilité ▸ Contenu
    énoncé ▸ Voix système ▸ Gérer les voix, et prend une minute.
    """
    return any(
        f"({qualite})" in name for name, _ in _say_voice() for qualite in QUALITES
    )

class SystemVoice:
    """Prononce un texte par le synthétiseur du système, sans jamais bloquer.

    Sans jamais bloquer, parce que l'appelant est la boucle qui suit la réunion :
    la faire attendre la fin d'une phrase, ce sont dix secondes d'audio non
    transcrit à chaque intervention.
    """

    def __init__(self, voice: str | None = None, debit: int = DEBIT) -> None:
        self.voice = voice if voice is not None else best_voice()
        self.debit = debit
        self._in_progress: subprocess.Popen[bytes] | None = None
        self._verrou = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self._command("essai"))

    def _command(self, text: str) -> list[str]:
        if SYSTEM == "Darwin" and shutil.which("say"):
            arguments = ["say", "-r", str(self.debit)]
            if self.voice:
                arguments += ["-v", self.voice]
            return [*arguments, text]
        if SYSTEM == "Linux":
            if shutil.which("spd-say"):
                return ["spd-say", "-l", "fr", "-w", text]
            if shutil.which("espeak-ng"):
                return ["espeak-ng", "-v", "fr", "-s", str(self.debit), text]
            return []
        if SYSTEM == "Windows" and shutil.which("powershell"):
            # Le texte passe par un littéral PowerShell : seuls les guillemets
            # simples ont besoin d'être doublés, et ils ne peuvent rien fermer
            # d'autre. Aucune interpolation n'a lieu dans ce type de chaîne.
            echappe = text.replace("'", "''")
            return [
                "powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Speech; "
                "$v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$v.Rate = {max(-10, min(10, (self.debit - 175) // 15))}; "
                f"$v.Speak('{echappe}')",
            ]
        return []

    def say(self, text: str) -> bool:
        """Lance la phrase et rend la main. Faux si le système ne parle pas.

        Une intervention en cours est interrompue : ce qu'on avait à dire il y a
        dix secondes ne vaut plus rien, et deux voix superposées ne valent rien
        du tout.
        """
        remark = text.strip()
        if not remark:
            return False
        command = self._command(remark)
        if not command:
            return False
        self.go_quiet()
        with self._verrou:
            try:
                self._in_progress = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError:
                return False
        return True

    def is_speaking(self) -> bool:
        with self._verrou:
            return self._in_progress is not None and self._in_progress.poll() is None

    def go_quiet(self) -> None:
        """Coupe la phrase en cours. Sans effet s'il n'y en a pas."""
        with self._verrou:
            in_progress, self._in_progress = self._in_progress, None
        if in_progress is not None and in_progress.poll() is None:
            in_progress.terminate()
            try:
                in_progress.wait(timeout=2)
            except subprocess.TimeoutExpired:
                in_progress.kill()

    def attendre(self, timeout: float = 30.0) -> None:
        """Attend la fin de la phrase. Pour la ligne de commande et les essais."""
        with self._verrou:
            in_progress = self._in_progress
        if in_progress is not None:
            try:
                in_progress.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.go_quiet()
