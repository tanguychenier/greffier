"""The documents supplied for a meeting, kept as text."""

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
    """A supplied document, reduced to its text."""

    name: str
    file: Path
    caracteres: int

    def say(self) -> str:
        return f"{self.name} ({self.caracteres // 1000 or 1} k caractères)"

def attachments_folder(base: Path, identifier: str) -> Path:
    return base / identifier

def _aplatir(name: str) -> str:
    """A safe file name, without accents or spaces."""
    without_accents = "".join(
        lettre for lettre in unicodedata.normalize("NFD", name)
        if unicodedata.category(lettre) != "Mn"
    )
    nu = re.sub(r"[^A-Za-z0-9]+", "-", without_accents).strip("-").casefold()
    return nu[:60] or "document"

def write(base: Path, identifier: str, name: str, text: str) -> Attachment | None:
    """Keeps this document's text under the meeting."""
    utile = text.strip()
    if not utile or not identifier.strip():
        return None
    folder = attachments_folder(base, identifier)
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / f"{_aplatir(name)}.txt"
    file.write_text(f"{HEADER}{name}\n{utile}", encoding="utf-8")
    return Attachment(name=name, file=file, caracteres=len(utile))

def lister(base: Path, identifier: str) -> list[Attachment]:
    """The documents supplied for this meeting, newest first."""
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
    """The text of the documents, ready to hand to the assistant."""
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
