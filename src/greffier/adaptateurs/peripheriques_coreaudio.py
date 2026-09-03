"""Lit le matériel audio réel, pour que la veille ait quelque chose à comparer.

`swift creer-peripheriques.swift --list` met une seconde : recompilé à chaque
appel, il coûterait un dixième du temps machine pendant tout l'enregistrement.
On le compile donc une fois, dans le dossier de données, et on rappelle le
binaire. La recompilation n'a lieu que si la source est plus récente.

Hors macOS, il n'y a rien à surveiller : Linux et Windows exposent un moniteur
de sortie et ne construisent aucun périphérique agrégé.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path

from greffier.domaine.peripheriques import Materiel, Peripherique

SYSTEME = platform.system()

# « Jabra EVOLVE 30 II  [entrée 1ch, sortie 2ch] » puis « uid: … » à la ligne.
_LIGNE = re.compile(r"^\s{2}(\S.*?)\s+\[(.+?)\]\s*$")
_UID = re.compile(r"^\s+uid:\s*(.+?)\s*$")
_ENTREES = re.compile(r"entrée (\d+)ch")
_SORTIES = re.compile(r"sortie (\d+)ch")


class ListeurCoreAudio:
    """Donne l'état du matériel audio, à la demande."""

    def __init__(self, source: Path, cache: Path, prete: Path | None = None) -> None:
        self.source = source
        # Le binaire livré dans le paquet macOS, quand il existe. Exécuter
        # depuis le paquet signé plutôt que depuis ~/.local change tout face à
        # un garde du poste (WithSecure XFENCE) : exécuté depuis ~/.local, il
        # redéclenchait une demande d'autorisation à chaque relevé du matériel
        # — toutes les cinq secondes pendant une réunion, constaté, la règle
        # « Autoriser » réécrite en boucle sans jamais suffire.
        self.prete = prete
        self.binaire = cache / "lister-peripheriques"

    def disponible(self) -> bool:
        if SYSTEME != "Darwin":
            return False
        return self.source.exists() or (self.prete is not None and self.prete.exists())

    def _compiler(self) -> bool:
        """Compile la source si besoin. Faux si la compilation est impossible."""
        if self.binaire.exists() and self.binaire.stat().st_mtime >= self.source.stat().st_mtime:
            return True
        if not shutil.which("swiftc"):
            return False
        self.binaire.parent.mkdir(parents=True, exist_ok=True)
        fait = subprocess.run(
            ["swiftc", "-O", str(self.source), "-o", str(self.binaire)],
            capture_output=True, text=True, check=False,
        )
        return fait.returncode == 0 and self.binaire.exists()

    def _sortie_brute(self) -> str:
        if self.prete is not None and self.prete.exists():
            commande = [str(self.prete), "--list"]
        elif self._compiler():
            commande = [str(self.binaire), "--list"]
        elif shutil.which("swift"):
            # Repli : dix fois plus lent, mais mieux que ne rien surveiller.
            commande = ["swift", str(self.source), "--list"]
        else:
            return ""
        fait = subprocess.run(commande, capture_output=True, text=True, check=False, timeout=30)
        return fait.stdout

    def lire(self) -> Materiel:
        """L'état du matériel maintenant. Vide si le système ne sait pas répondre."""
        if not self.disponible():
            return Materiel()
        try:
            return analyser(self._sortie_brute())
        except (subprocess.SubprocessError, OSError):
            # Un échec de lecture ne doit jamais interrompre un enregistrement :
            # la veille se taira, la capture continue.
            return Materiel()


def analyser(sortie: str) -> Materiel:
    """Convertit la sortie du listeur en matériel comparable.

    Fonction pure, donc éprouvable sur des sorties enregistrées, y compris
    celles qu'on ne peut pas reproduire à la demande sur un poste donné.
    """
    trouves: list[Peripherique] = []
    en_cours: tuple[str, str] | None = None
    for ligne in sortie.splitlines():
        entete = _LIGNE.match(ligne)
        if entete:
            en_cours = (entete.group(1), entete.group(2))
            continue
        uid = _UID.match(ligne)
        if uid and en_cours is not None:
            nom, canaux = en_cours
            entrees = _ENTREES.search(canaux)
            sorties = _SORTIES.search(canaux)
            trouves.append(
                Peripherique(
                    nom=nom,
                    uid=uid.group(1),
                    entrees=int(entrees.group(1)) if entrees else 0,
                    sorties=int(sorties.group(1)) if sorties else 0,
                )
            )
            en_cours = None
    return Materiel(tuple(trouves))
