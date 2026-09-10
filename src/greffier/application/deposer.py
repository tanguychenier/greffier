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

from greffier.domaine.depot import Destin, Proposition

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
class Fait:
    """Ce qu'un dépôt a produit."""

    proposition: Proposition
    produit: Path | None = None
    appris: tuple[tuple[str, str, str], ...] = ()
    souci: str = ""

def outils_presents() -> frozenset[str]:
    """Les commandes d'extraction réellement disponibles sur ce poste."""
    trouvees = {nom for nom in ("ffmpeg", "pdftotext") if shutil.which(nom)}
    if platform.system() == "Darwin" and shutil.which("textutil"):
        trouvees.add("textutil")
    return frozenset(trouvees)

def extraire_le_son(video: Path, destination: Path) -> Path:
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
    from greffier.domaine.depot import TEXTES, TEXTES_OUTILLES

    suffixe = document.suffix.casefold()
    if suffixe in TEXTES:
        try:
            return document.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    # Restreint aux formats connus : tout envoyer à `textutil` lui faisait
    # avaler une archive ou une image et rendre des octets illisibles, qu'on
    # aurait ensuite donnés au rédacteur comme s'il s'agissait d'un document.
    if suffixe not in TEXTES_OUTILLES:
        return ""
    commande = (
        ["pdftotext", "-q", str(document), "-"] if suffixe == ".pdf"
        else ["textutil", "-stdout", "-convert", "txt", str(document)]
    )
    if shutil.which(commande[0]) is None:
        return ""
    fait = subprocess.run(commande, capture_output=True, text=True, check=False)
    return fait.stdout if fait.returncode == 0 else ""

def apprendre_du_document(
    document: Path, redacteur: object, maximum: int = 20
) -> tuple[tuple[str, str, str], ...]:
    """Les entrées de contexte que ce document suggère. Vide s'il n'apprend rien.

    Rend des triplets (écriture, sens, genre) plutôt que d'écrire : la
    confirmation est la même que pour une phrase tapée dans la conversation, et
    c'est un humain qui décide ce qui entre dans le contexte.
    """
    return apprendre_du_texte(lire_le_texte(document), redacteur, maximum)

def apprendre_du_texte(
    texte: str, redacteur: object, maximum: int = 20
) -> tuple[tuple[str, str, str], ...]:
    """Les entrées de contexte que ce texte suggère.

    Séparée de la lecture du fichier : un document fourni pendant la réunion
    est lu une fois, son texte servant à la fois à répondre aux questions et à
    proposer du vocabulaire. Le relire ferait tourner `pdftotext` deux fois.
    """
    import json
    import re

    if not texte.strip():
        return ()
    rendu = redacteur.rediger(  # type: ignore[attr-defined]
        CONSIGNES_DOCUMENT + texte[:LU_AU_PLUS]
    )
    bloc = re.search(r"```(?:json)?\s*(.*?)```", rendu, re.DOTALL)
    brut = bloc.group(1) if bloc else rendu
    debut, fin = brut.find("["), brut.rfind("]")
    if debut == -1 or fin <= debut:
        return ()
    try:
        elements = json.loads(brut[debut:fin + 1])
    except json.JSONDecodeError:
        return ()
    if not isinstance(elements, list):
        return ()

    retenus: list[tuple[str, str, str]] = []
    for element in elements[:maximum]:
        if not isinstance(element, dict):
            continue
        ecriture = str(element.get("ecriture", "")).strip()
        if not ecriture:
            continue
        genre = "personne" if str(element.get("genre", "")).strip() == "personne" else "terme"
        retenus.append((ecriture, str(element.get("sens", "")).strip(), genre))
    return tuple(retenus)

def executer(
    proposition: Proposition,
    enregistrements: Path,
    redacteur: object | None = None,
) -> Fait:
    """Fait ce que la proposition annonce. Ne lève pas : rapporte.

    Un fichier qui échoue ne doit pas interrompre le dépôt des autres — on
    dépose souvent un lot, et perdre neuf traitements pour un fichier abîmé
    serait absurde.
    """
    if not proposition.faisable:
        return Fait(proposition, souci=proposition.bloque_par or "rien à en faire")

    if proposition.destin is Destin.VIDEO:
        cible = enregistrements / f"{proposition.fichier.stem}.wav"
        try:
            return Fait(proposition, produit=extraire_le_son(proposition.fichier, cible))
        except (RuntimeError, OSError) as souci:
            return Fait(proposition, souci=str(souci))

    if proposition.destin is Destin.REUNION:
        # Copié dans les enregistrements : la chaîne travaille là, et un fichier
        # déposé depuis le bureau ou une clé USB ne doit pas rester la seule
        # copie de la réunion.
        cible = enregistrements / proposition.fichier.name
        try:
            if cible.resolve() != proposition.fichier.resolve():
                cible.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(proposition.fichier, cible)
            return Fait(proposition, produit=cible)
        except OSError as souci:
            return Fait(proposition, souci=str(souci))

    if proposition.destin is Destin.CONTEXTE:
        if redacteur is None:
            return Fait(proposition, souci="aucun rédacteur pour lire le document")
        try:
            return Fait(
                proposition,
                appris=apprendre_du_document(proposition.fichier, redacteur),
            )
        except (RuntimeError, OSError) as souci:
            return Fait(proposition, souci=str(souci))

    return Fait(proposition, souci="rien à en faire")
