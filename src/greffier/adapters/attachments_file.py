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

HEADER = "# "

@dataclass(frozen=True, slots=True)
class Attachment:
    """Un document fourni, réduit à son texte."""

    name: str
    file: Path
    caracteres: int

    def say(self) -> str:
        return f"{self.name} ({self.caracteres // 1000 or 1} k caractères)"

def attachments_folder(base: Path, identifier: str) -> Path:
    return base / identifier

def _aplatir(name: str) -> str:
    """Un nom de fichier sûr, sans accent ni espace, jamais vide."""
    without_accents = "".join(
        lettre for lettre in unicodedata.normalize("NFD", name)
        if unicodedata.category(lettre) != "Mn"
    )
    nu = re.sub(r"[^A-Za-z0-9]+", "-", without_accents).strip("-").casefold()
    return nu[:60] or "document"

def write(base: Path, identifier: str, name: str, text: str) -> Attachment | None:
    """Garde le texte de ce document sous la réunion. None s'il n'y a rien à garder.

    Écrase une pièce du même nom : redéposer un document est ce qu'on fait
    quand il a changé, et garder les deux versions ferait répondre l'outil sur
    l'ancienne.
    """
    utile = text.strip()
    if not utile or not identifier.strip():
        return None
    folder = attachments_folder(base, identifier)
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / f"{_aplatir(name)}.txt"
    file.write_text(f"{HEADER}{name}\n{utile}", encoding="utf-8")
    return Attachment(name=name, file=file, caracteres=len(utile))

def lister(base: Path, identifier: str) -> list[Attachment]:
    """Les documents fournis pour cette réunion, du plus ancien au plus récent."""
    folder = attachments_folder(base, identifier)
    if not identifier.strip() or not folder.is_dir():
        return []
    trouvees: list[Attachment] = []
    for file in sorted(folder.glob("*.txt"), key=lambda f: f.stat().st_mtime):
        try:
            content = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        header, _, corps = content.partition("\n")
        name = header[len(HEADER):].strip() if header.startswith(HEADER) else file.stem
        trouvees.append(Attachment(name=name, file=file, caracteres=len(corps)))
    return trouvees

def material(base: Path, identifier: str, au_plus: int = AU_PLUS) -> str:
    """Le texte des documents, prêt à être donné à l'assistant. Vide s'il n'y en a pas.

    Chaque document est annoncé par son nom : sans lui, l'assistant répond « le
    document dit » sans pouvoir dire lequel, et deux documents contradictoires
    deviennent une seule voix.
    """
    chunks: list[str] = []
    reste = au_plus
    for piece in lister(base, identifier):
        if reste <= 0:
            break
        try:
            content = piece.file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _, _, corps = content.partition("\n")
        garde = min(PAR_PIECE, reste)
        coupe = corps[:garde].strip()
        if not coupe:
            continue
        suite = "\n[…] document tronqué" if len(corps) > garde else ""
        chunks.append(f"Document « {piece.name} » :\n{coupe}{suite}")
        reste -= len(coupe)
    return "\n\n".join(chunks)
