"""Exécuter ce qu'un dépôt de fichiers a fait valider.

Deux gestes, et rien d'autre : extraire la piste sonore d'une vidéo pour en
faire une réunion, et tirer d'un document les sigles et les noms qui manquent au
contexte. Le reste — transcrire, rédiger — est le travail de la chaîne, qui
existe déjà et qu'on ne duplique pas.

Le document n'est **pas** ajouté tel quel au contexte. Un compte rendu de dix
pages versé dans l'amorce du transcripteur la ferait tronquer sans prévenir : ce
qu'on en veut, ce sont les mots qu'un modèle ne peut pas devenir — sigles,
produits, noms propres. Le rédacteur sait les repérer, c'est donc lui qui lit le
document, et il rend une liste que la même confirmation qu'ailleurs valide.
"""

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
    """Ce qu'un dépôt a produit."""

    proposition: Suggestion
    produit: Path | None = None
    appris: tuple[tuple[str, str, str], ...] = ()
    trouble: str = ""

def tools_present() -> frozenset[str]:
    """Les commandes d'extraction réellement disponibles sur ce poste."""
    trouvees = {name for name in ("ffmpeg", "pdftotext") if shutil.which(name)}
    if platform.system() == "Darwin" and shutil.which("textutil"):
        trouvees.add("textutil")
    return frozenset(trouvees)

def extract_sound(video: Path, destination: Path) -> Path:
    """Sort la piste sonore d'une vidéo, au format que la chaîne attend.

    16 kHz mono : c'est ce que les modèles de transcription et d'empreintes
    consomment, et convertir une fois ici évite que chaque étape le refasse.
    L'image est jetée — elle ne sert à rien pour transcrire, et garder un
    fichier de 800 Mo à côté d'un WAV de 30 Mo n'apporte que de la place perdue.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fait = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(destination)],
        capture_output=True, text=True, check=False,
    )
    if fait.returncode != 0 or not destination.exists():
        details = (fait.stderr or "").strip().splitlines()
        raise RuntimeError(
            "extraction du son impossible"
            + (f" : {details[-1][:160]}" if details else "")
        )
    return destination

def lire_le_texte(document: Path) -> str:
    """Le texte d'un document, quel que soit son format. Vide si illisible.

    Les outils du système plutôt qu'une bibliothèque de plus : `pdftotext` et
    `textutil` sont déjà là ou s'installent en une ligne, et une dépendance
    Python de plus se paie à chaque installation de l'outil, sur les trois
    systèmes.
    """
    from greffier.domain.store import TEXTES_OUTILLES, TEXTS

    suffixe = document.suffix.casefold()
    if suffixe in TEXTS:
        try:
            return document.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    if suffixe not in TEXTES_OUTILLES:
        return ""
    command = (
        ["pdftotext", "-q", str(document), "-"] if suffixe == ".pdf"
        else ["textutil", "-stdout", "-convert", "txt", str(document)]
    )
    if shutil.which(command[0]) is None:
        return ""
    fait = subprocess.run(command, capture_output=True, text=True, check=False)
    return fait.stdout if fait.returncode == 0 else ""

def learn_from_document(
    document: Path, writer: object, maximum: int = 20
) -> tuple[tuple[str, str, str], ...]:
    """Les entrées de contexte que ce document suggère. Vide s'il n'apprend rien.

    Rend des triplets (écriture, sens, genre) plutôt que d'écrire : la
    confirmation est la même que pour une phrase tapée dans la conversation, et
    c'est un humain qui décide ce qui entre dans le contexte.
    """
    return learn_from_text(lire_le_texte(document), writer, maximum)

def learn_from_text(
    text: str, writer: object, maximum: int = 20
) -> tuple[tuple[str, str, str], ...]:
    """Les entrées de contexte que ce texte suggère.

    Séparée de la lecture du fichier : un document fourni pendant la réunion
    est lu une fois, son texte servant à la fois à répondre aux questions et à
    proposer du vocabulaire. Le relire ferait tourner `pdftotext` deux fois.
    """
    import json
    import re

    if not text.strip():
        return ()
    rendered = writer.write_up(  # type: ignore[attr-defined]
        CONSIGNES_DOCUMENT + text[:LU_AU_PLUS]
    )
    bloc = re.search(r"```(?:json)?\s*(.*?)```", rendered, re.DOTALL)
    brut = bloc.group(1) if bloc else rendered
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
    """Fait ce que la proposition annonce. Ne lève pas : rapporte.

    Un fichier qui échoue ne doit pas interrompre le dépôt des autres — on
    dépose souvent un lot, et perdre neuf traitements pour un fichier abîmé
    serait absurde.
    """
    if not proposition.feasible:
        return Done(proposition, trouble=proposition.bloque_par or "rien à en faire")

    if proposition.destin is Destination.VIDEO:
        target = recordings / f"{proposition.file.stem}.wav"
        try:
            return Done(proposition, produit=extract_sound(proposition.file, target))
        except (RuntimeError, OSError) as trouble:
            return Done(proposition, trouble=str(trouble))

    if proposition.destin is Destination.MEETING:
        target = recordings / proposition.file.name
        try:
            if target.resolve() != proposition.file.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(proposition.file, target)
            return Done(proposition, produit=target)
        except OSError as trouble:
            return Done(proposition, trouble=str(trouble))

    if proposition.destin is Destination.CONTEXT:
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
