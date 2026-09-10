"""Les documents fournis pour une réunion, gardés sous forme de texte.

Ce qu'on tend à l'outil en pleine réunion — un ordre du jour, un cahier des
charges, un compte rendu précédent — sert deux fois : le vocabulaire du document
part dans le contexte, et le texte lui-même doit pouvoir répondre à « qu'est-ce
que le document dit de X ? » sans qu'on le rouvre.

Le texte est gardé, pas le fichier : une pièce jointe de quarante mégaoctets
recopiée dans les données de la réunion se sauvegarde, se synchronise et se
perd, alors que son texte fait quelques dizaines de kilooctets. L'original reste
là où il est, c'est à lui de vivre sa vie.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

AU_PLUS = 24_000

PAR_PIECE = 8_000

ENTETE = "# "

@dataclass(frozen=True, slots=True)
class Piece:
    """Un document fourni, réduit à son texte."""

    nom: str
    fichier: Path
    caracteres: int

    def dire(self) -> str:
        return f"{self.nom} ({self.caracteres // 1000 or 1} k caractères)"

def dossier_des_pieces(base: Path, identifiant: str) -> Path:
    return base / identifiant

def _aplatir(nom: str) -> str:
    """Un nom de fichier sûr, sans accent ni espace, jamais vide."""
    sans_accent = "".join(
        lettre for lettre in unicodedata.normalize("NFD", nom)
        if unicodedata.category(lettre) != "Mn"
    )
    nu = re.sub(r"[^A-Za-z0-9]+", "-", sans_accent).strip("-").casefold()
    return nu[:60] or "document"

def ecrire(base: Path, identifiant: str, nom: str, texte: str) -> Piece | None:
    """Garde le texte de ce document sous la réunion. None s'il n'y a rien à garder.

    Écrase une pièce du même nom : redéposer un document est ce qu'on fait
    quand il a changé, et garder les deux versions ferait répondre l'outil sur
    l'ancienne.
    """
    utile = texte.strip()
    if not utile or not identifiant.strip():
        return None
    dossier = dossier_des_pieces(base, identifiant)
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / f"{_aplatir(nom)}.txt"
    fichier.write_text(f"{ENTETE}{nom}\n{utile}", encoding="utf-8")
    return Piece(nom=nom, fichier=fichier, caracteres=len(utile))

def lister(base: Path, identifiant: str) -> list[Piece]:
    """Les documents fournis pour cette réunion, du plus ancien au plus récent."""
    dossier = dossier_des_pieces(base, identifiant)
    if not identifiant.strip() or not dossier.is_dir():
        return []
    trouvees: list[Piece] = []
    for fichier in sorted(dossier.glob("*.txt"), key=lambda f: f.stat().st_mtime):
        try:
            contenu = fichier.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        entete, _, corps = contenu.partition("\n")
        nom = entete[len(ENTETE):].strip() if entete.startswith(ENTETE) else fichier.stem
        trouvees.append(Piece(nom=nom, fichier=fichier, caracteres=len(corps)))
    return trouvees

def matiere(base: Path, identifiant: str, au_plus: int = AU_PLUS) -> str:
    """Le texte des documents, prêt à être donné à l'assistant. Vide s'il n'y en a pas.

    Chaque document est annoncé par son nom : sans lui, l'assistant répond « le
    document dit » sans pouvoir dire lequel, et deux documents contradictoires
    deviennent une seule voix.
    """
    morceaux: list[str] = []
    reste = au_plus
    for piece in lister(base, identifiant):
        if reste <= 0:
            break
        try:
            contenu = piece.fichier.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _, _, corps = contenu.partition("\n")
        garde = min(PAR_PIECE, reste)
        coupe = corps[:garde].strip()
        if not coupe:
            continue
        suite = "\n[…] document tronqué" if len(corps) > garde else ""
        morceaux.append(f"Document « {piece.nom} » :\n{coupe}{suite}")
        reste -= len(coupe)
    return "\n\n".join(morceaux)
