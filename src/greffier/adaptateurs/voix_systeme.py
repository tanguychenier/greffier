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

SYSTEME = platform.system()

QUALITES = ("Premium", "Enhanced")

COMPACTES_ACCEPTABLES = ("Thomas", "Amélie", "Audrey", "Aurelie")

DEBIT = 165

def _voix_de_say() -> list[tuple[str, str]]:
    """Les voix françaises que `say` connaît, avec leur nom exact."""
    if SYSTEME != "Darwin" or shutil.which("say") is None:
        return []
    try:
        sortie = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    voix = []
    for ligne in sortie.splitlines():
        # « Thomas (Premium)      fr_FR    # Bonjour… » : le nom peut contenir
        # des espaces et des parenthèses, la langue jamais.
        trouve = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", ligne)
        if trouve and trouve.group(2).startswith("fr"):
            voix.append((trouve.group(1).strip(), trouve.group(2)))
    return voix

def meilleure_voix() -> str | None:
    """Le nom de la meilleure voix française installée, ou rien.

    Rien n'est un résultat normal : sur un système sans voix française, mieux
    vaut laisser la synthèse choisir sa voix par défaut que d'en imposer une
    qui lirait le français avec un accent anglais.
    """
    voix = _voix_de_say()
    if not voix:
        return None
    for qualite in QUALITES:
        # fr_FR avant fr_CA : la réunion se tient en France, et l'accent
        # québécois, si agréable soit-il, distrait l'auditoire.
        for langue in ("fr_FR", "fr_CA"):
            for nom, cette_langue in voix:
                if f"({qualite})" in nom and cette_langue == langue:
                    return nom
    for prefere in COMPACTES_ACCEPTABLES:
        for nom, _ in voix:
            if nom.split(" (")[0] == prefere:
                return nom
    return voix[0][0]

def voix_amelioree_disponible() -> bool:
    """Une voix neuronale est-elle installée ?

    Sert au diagnostic : sans elle, l'assistant parle, mais il s'entend. Le
    téléchargement se fait dans Réglages Système ▸ Accessibilité ▸ Contenu
    énoncé ▸ Voix système ▸ Gérer les voix, et prend une minute.
    """
    return any(
        f"({qualite})" in nom for nom, _ in _voix_de_say() for qualite in QUALITES
    )

class VoixSysteme:
    """Prononce un texte par le synthétiseur du système, sans jamais bloquer.

    Sans jamais bloquer, parce que l'appelant est la boucle qui suit la réunion :
    la faire attendre la fin d'une phrase, ce sont dix secondes d'audio non
    transcrit à chaque intervention.
    """

    def __init__(self, voix: str | None = None, debit: int = DEBIT) -> None:
        self.voix = voix if voix is not None else meilleure_voix()
        self.debit = debit
        self._en_cours: subprocess.Popen[bytes] | None = None
        self._verrou = threading.Lock()

    @property
    def disponible(self) -> bool:
        return bool(self._commande("essai"))

    def _commande(self, texte: str) -> list[str]:
        if SYSTEME == "Darwin" and shutil.which("say"):
            arguments = ["say", "-r", str(self.debit)]
            if self.voix:
                arguments += ["-v", self.voix]
            return [*arguments, texte]
        if SYSTEME == "Linux":
            if shutil.which("spd-say"):
                return ["spd-say", "-l", "fr", "-w", texte]
            if shutil.which("espeak-ng"):
                return ["espeak-ng", "-v", "fr", "-s", str(self.debit), texte]
            return []
        if SYSTEME == "Windows" and shutil.which("powershell"):
            # Le texte passe par un littéral PowerShell : seuls les guillemets
            # simples ont besoin d'être doublés, et ils ne peuvent rien fermer
            # d'autre. Aucune interpolation n'a lieu dans ce type de chaîne.
            echappe = texte.replace("'", "''")
            return [
                "powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Speech; "
                "$v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$v.Rate = {max(-10, min(10, (self.debit - 175) // 15))}; "
                f"$v.Speak('{echappe}')",
            ]
        return []

    def dire(self, texte: str) -> bool:
        """Lance la phrase et rend la main. Faux si le système ne parle pas.

        Une intervention en cours est interrompue : ce qu'on avait à dire il y a
        dix secondes ne vaut plus rien, et deux voix superposées ne valent rien
        du tout.
        """
        propos = texte.strip()
        if not propos:
            return False
        commande = self._commande(propos)
        if not commande:
            return False
        self.se_taire()
        with self._verrou:
            try:
                self._en_cours = subprocess.Popen(
                    commande, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError:
                return False
        return True

    def parle(self) -> bool:
        with self._verrou:
            return self._en_cours is not None and self._en_cours.poll() is None

    def se_taire(self) -> None:
        """Coupe la phrase en cours. Sans effet s'il n'y en a pas."""
        with self._verrou:
            en_cours, self._en_cours = self._en_cours, None
        if en_cours is not None and en_cours.poll() is None:
            en_cours.terminate()
            try:
                en_cours.wait(timeout=2)
            except subprocess.TimeoutExpired:
                en_cours.kill()

    def attendre(self, delai: float = 30.0) -> None:
        """Attend la fin de la phrase. Pour la ligne de commande et les essais."""
        with self._verrou:
            en_cours = self._en_cours
        if en_cours is not None:
            try:
                en_cours.wait(timeout=delai)
            except subprocess.TimeoutExpired:
                self.se_taire()
