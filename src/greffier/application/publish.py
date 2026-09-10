"""Doing what a file drop had validated."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from greffier.domain.store import Destination, Suggestion

CONSIGNES_DOCUMENT = """Tu lis un document de travail pour en extraire le
vocabulaire qu'une transcription automatique ne pourrait pas deviner.

Rends **uniquement** un tableau JSON, sans texte avant ni après :

[{"ecriture": "...", "sens": "...", "genre": "terme|personne"}]

Règles :

- Ne retiens que ce qu'un modèle de transcription écrirait mal : sigles, noms
  de produits, de projets, d'applications, noms propres de personnes. Pas les
  mots courants, pas le jargon répandu (« sprint », « backlog » le sont).
- « ecriture » est l'orthographe exacte, telle qu'elle doit apparaître.
- « sens » développe un sigle ou dit ce qu'est le produit, en huit mots au plus.
  Vide si le document ne le dit pas — n'invente pas.
- « genre » vaut « personne » pour un nom de personne, « terme » sinon.
- Vingt entrées au maximum, les plus utiles. Une amorce trop longue est
  tronquée en silence par le transcripteur.
- Si le document ne contient rien de tel, rends [].

Document :
"""

LU_AU_PLUS = 40_000

@dataclass(frozen=True, slots=True)
class Done:
    """What a drop produced."""

    proposition: Suggestion
    produit: Path | None = None
    appris: tuple[tuple[str, str, str], ...] = ()
    trouble: str = ""

def tools_present() -> frozenset[str]:
    """The extraction commands actually available on this machine."""
    found = {name for name in ("ffmpeg", "pdftotext") if shutil.which(name)}
    if platform.system() == "Darwin" and shutil.which("textutil"):
        found.add("textutil")
    return frozenset(found)

def extract_sound(video: Path, destination: Path) -> Path:
    """Pulls the sound track out of a video, in the format transcription wants."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(destination)],
        capture_output=True, text=True, check=False,
    )
    if done.returncode != 0 or not destination.exists():
        details = (done.stderr or "").strip().splitlines()
        raise RuntimeError(
            "extraction du son impossible"
            + (f" : {details[-1][:160]}" if details else "")
        )
    return destination

def lire_le_texte(document: Path) -> str:
    """The text of a document, whatever its format. Empty when unreadable."""
    from greffier.domain.store import TEXTS, TOOLED_TEXTS

    suffixe = document.suffix.casefold()
    if suffixe in TEXTS:
        try:
            return document.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    if suffixe not in TOOLED_TEXTS:
        return ""
    command = (
        ["pdftotext", "-q", str(document), "-"] if suffixe == ".pdf"
        else ["textutil", "-stdout", "-convert", "txt", str(document)]
    )
    if shutil.which(command[0]) is None:
        return ""
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else ""

def learn_from_document(
    document: Path, writer: object, maximum: int = 20
) -> tuple[tuple[str, str, str], ...]:
    """The context entries this document suggests."""
    return learn_from_text(lire_le_texte(document), writer, maximum)

def learn_from_text(
    text: str, writer: object, maximum: int = 20
) -> tuple[tuple[str, str, str], ...]:
    """The context entries this text suggests."""
    import json
    import re

    if not text.strip():
        return ()
    rendered = writer.write_up(  # type: ignore[attr-defined]
        CONSIGNES_DOCUMENT + text[:LU_AU_PLUS]
    )
    block = re.search(r"```(?:json)?\s*(.*?)```", rendered, re.DOTALL)
    brut = block.group(1) if block else rendered
    start, end = brut.find("["), brut.rfind("]")
    if start == -1 or end <= start:
        return ()
    try:
        items = json.loads(brut[start:end + 1])
    except json.JSONDecodeError:
        return ()
    if not isinstance(items, list):
        return ()

    retenus: list[tuple[str, str, str]] = []
    for item in items[:maximum]:
        if not isinstance(item, dict):
            continue
        ecriture = str(item.get("ecriture", "")).strip()
        if not ecriture:
            continue
        kind = "personne" if str(item.get("genre", "")).strip() == "personne" else "terme"
        retenus.append((ecriture, str(item.get("sens", "")).strip(), kind))
    return tuple(retenus)

def run_chain(
    proposition: Suggestion,
    recordings: Path,
    writer: object | None = None,
) -> Done:
    """Does what the suggestion announced. Never raises."""
    if not proposition.feasible:
        return Done(proposition, trouble=proposition.blocked_by or "rien à en faire")

    if proposition.destination is Destination.VIDEO:
        target = recordings / f"{proposition.file.stem}.wav"
        try:
            return Done(proposition, produit=extract_sound(proposition.file, target))
        except (RuntimeError, OSError) as trouble:
            return Done(proposition, trouble=str(trouble))

    if proposition.destination is Destination.MEETING:
        target = recordings / proposition.file.name
        try:
            if target.resolve() != proposition.file.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(proposition.file, target)
            return Done(proposition, produit=target)
        except OSError as trouble:
            return Done(proposition, trouble=str(trouble))

    if proposition.destination is Destination.CONTEXT:
        if writer is None:
            return Done(proposition, trouble="aucun rédacteur pour lire le document")
        try:
            return Done(
                proposition,
                appris=learn_from_document(proposition.file, writer),
            )
        except (RuntimeError, OSError) as trouble:
            return Done(proposition, trouble=str(trouble))

    return Done(proposition, trouble="rien à en faire")
