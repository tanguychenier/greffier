"""What is done with a meeting once it is transcribed."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from greffier.domain.meeting import HORODATAGE, StoredMeeting
from greffier.domain.models import Span, SpeakerTurn, Utterance
from greffier.ports import outbound


class Transcribed(Protocol):
    """What has to be known about a meeting in order to render it."""

    @property
    def coverage(self) -> float: ...

    @property
    def turns(self) -> list[SpeakerTurn]: ...

    @property
    def utterances(self) -> list[Utterance]: ...

    def gaps(self, minimum: float = ...) -> list[Span]: ...
    def speaking_time(self) -> dict[str, float]: ...
    def name_of(self, voice: str | None) -> str: ...

SYSTEM = platform.system()

TROU_SIGNIFICATIF = 8.0
COUVERTURE_SUSPECTE = 0.60

_HORODATAGE = HORODATAGE

_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre")

def context_header(
    identifier: str,
    duration: float = 0.0,
    names: Sequence[str] = (),
    voix_entendues: int = 0,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> str:
    """The meeting's context, dictated to the writer word for word."""
    trouve = _HORODATAGE.match(identifier)
    lines = ["[Contexte de la réunion]"]
    context = _context_line(trouve, duration, names, voix_entendues,
                                  started_at, ended_at)
    if not context:
        return ""
    lines.append(
        "Reproduis cette ligne telle quelle sous le titre, sans rien y ajouter "
        "ni en retirer :"
    )
    lines.append(context)
    if trouve:
        lines.append("Emploie cette date, jamais celle du jour.")
    return "\n".join(lines) + "\n\n"

def _context_line(
    trouve: re.Match[str] | None,
    duration: float,
    names: Sequence[str],
    voix_entendues: int,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> str:
    chunks: list[str] = []
    if trouve:
        annee, mois, jour, heure, minute = trouve.groups()
        chunks.append(f"{int(jour)} {_MOIS[int(mois) - 1]} {annee}")
    if started_at is not None and ended_at is not None:
        locale_debut, locale_fin = started_at.astimezone(), ended_at.astimezone()
        chunks.append(
            f"de {locale_debut.hour} h {locale_debut.minute:02d} "
            f"à {locale_fin.hour} h {locale_fin.minute:02d}"
        )
        ecoule = (ended_at - started_at).total_seconds()
        if ecoule > 0:
            chunks.append(f"durée {_readable_duration(ecoule)}")
    elif trouve and trouve.group(4):
        chunks.append(_time_range(int(trouve.group(4)), int(trouve.group(5)), duration))
        if duration > 0:
            chunks.append(f"durée {_readable_duration(duration)}")
    elif duration > 0:
        chunks.append(f"durée {_readable_duration(duration)}")
    if not chunks:
        return ""
    line = ", ".join(chunks) + "."
    present_line = _present_line(names, voix_entendues)
    return f"{line} {present_line}" if present_line else line

def _time_range(heure: int, minute: int, duration: float) -> str:
    """"from 16:46 to 17:03" — the end time follows from the duration."""
    if duration <= 0:
        return f"à {heure} h {minute:02d}"
    end = (heure * 60 + minute + int(duration // 60)) % (24 * 60)
    return f"de {heure} h {minute:02d} à {end // 60} h {end % 60:02d}"

def _present_line(names: Sequence[str], voix_entendues: int) -> str:
    known = [n for n in dict.fromkeys(names) if n]
    if known:
        reste = voix_entendues - len(known)
        listing = ", ".join(known)
        if reste > 0:
            pluriel = "s" if reste > 1 else ""
            return f"Participants : {listing}, et {reste} voix non nommée{pluriel}."
        return f"Participants : {listing}."
    if voix_entendues > 0:
        if voix_entendues == 1:
            return "Participants : 1 personne a parlé, non nommée."
        return (f"Participants : {voix_entendues} personnes ont parlé, "
                "aucune nommée.")
    return ""

def _readable_duration(seconds: float) -> str:
    heures, reste = divmod(int(seconds), 3600)
    minutes, restantes = divmod(reste, 60)
    if heures:
        return f"{heures} h {minutes:02d}"
    if minutes:
        return f"{minutes} min"
    return f"{restantes} s"

def disclosure_header(disclosure: str) -> str:
    """The recording statement, dictated to the writer word for word."""
    from greffier.domain.consent import mention, read

    return (
        "[Mention sur l'enregistrement]\n"
        "Reproduis cette phrase telle quelle en fin de document, sous un titre "
        "« ## Mention », sans rien y ajouter ni en retirer :\n"
        f"{mention(read(disclosure))}\n\n"
    )

def instructions_header(instructions: list[str]) -> str:
    """What was asked of the tool during the meeting, dictated to the writer.

    The defect this repairs, in the words that reported it: "I had said in the
    tool's chat that we had no Sophie... and in the chat I had given it
    instructions for the minutes, none of it was taken into account". The
    corrections were kept on disk and read by nobody.

    They come first among the headers and they say so: someone who watched the
    meeting happen knows things the transcript does not carry, and a correction
    that arrives after the fact is worth more than any rule.
    """
    if not instructions:
        return ""
    lines = [
        "[Consignes données pendant la réunion]",
        "Elles viennent de la personne qui a suivi la réunion en direct et "
        "elles l'emportent sur ce que la transcription laisse croire : une "
        "correction de nom, un terme à écrire autrement, une section à "
        "ajouter. Applique-les.",
    ]
    lines += [f"- {x}" for x in instructions]
    return "\n".join(lines) + "\n\n"


def hardware_header(events: list[str]) -> str:
    """What the watch observed of the hardware, told to the writer."""
    if not events:
        return ""
    lines = ["[Matériel audio pendant la réunion]"]
    lines += [f"- {x}" for x in events]
    lines.append(
        "Ces changements ont coupé la capture en plusieurs morceaux, recollés "
        "ensuite. Les passages enregistrés avant un branchement peuvent ne pas "
        "porter la voix de la personne qui enregistrait : dis-le si un échange "
        "paraît n'avoir qu'un seul côté."
    )
    return "\n".join(lines) + "\n\n"

def reliability_header(meeting: Transcribed) -> str:
    """What the transcription lost, told to the writer before it writes."""
    gaps = [t for t in meeting.gaps(TROU_SIGNIFICATIF) if t.duration >= TROU_SIGNIFICATIF]
    if not gaps and meeting.coverage >= COUVERTURE_SUSPECTE:
        return ""

    lines = ["[Fiabilité de la transcription]"]
    lines.append(
        f"Couverture : {meeting.coverage * 100:.0f} % de l'audio porte du texte."
    )
    if meeting.coverage < COUVERTURE_SUSPECTE:
        lines.append(
            "Ce taux est bas : le modèle a probablement décroché sur une partie "
            "de la réunion. Signale-le explicitement dans le compte rendu."
        )
    if gaps:
        lines.append(f"{len(gaps)} passage(s) sans aucun texte :")
        for trou in gaps[:10]:
            lines.append(
                f"  {int(trou.start) // 60:02d}:{int(trou.start) % 60:02d}"
                f" → {int(trou.end) // 60:02d}:{int(trou.end) % 60:02d}"
                f" ({trou.duration:.0f} s)"
            )
        if len(gaps) > 10:
            lines.append(f"  … et {len(gaps) - 10} autres")
        lines.append(
            "Un silence peut être un vrai silence ou du texte perdu : ne comble "
            "aucun de ces passages, contente-toi de les signaler."
        )
    return "\n".join(lines) + "\n\n"

def render_transcript(meeting: Transcribed, header: str = "") -> str:
    """Readable transcript, timestamped and attributed."""
    lines: list[str] = []
    current: str | None = None
    for utterance in meeting.utterances:
        name = meeting.name_of(utterance.voice)
        if name != current:
            lines.append(f"\n[{name}]")
            current = name
        start = int(utterance.span.start)
        lines.append(f"{start // 60:02d}:{start % 60:02d}  {utterance.text}")
    return header + "\n".join(lines).strip() + "\n"

def to_resume(store: Any, minutes_folder: Path, combien: int = 20) -> list[str]:
    """The transcribed meetings whose minutes are still missing."""
    missing = []
    for identifier in store.lister()[:combien]:
        if not re.match(r"^\d{4}-\d{2}-\d{2}_", identifier):
            continue
        if not (minutes_folder / f"{identifier}.md").exists():
            missing.append(identifier)
    return missing

def regenerate_minutes(
    meeting: StoredMeeting,
    writer: outbound.Writer,
    disclosure: str = "rien",
) -> str:
    """Replays the writing only, from what is already kept."""
    duration = meeting.turns[-1].span.end if meeting.turns else 0.0
    entendues = meeting.attendees()
    header = (
        context_header(
            meeting.identifier, duration,
            names=[meeting.names[v] for v in entendues if v in meeting.names],
            voix_entendues=len(entendues),
            started_at=meeting.started_at,
            ended_at=meeting.ended_at,
        )
        + hardware_header(meeting.hardware_events)
        + reliability_header(meeting)
        + disclosure_header(disclosure)
    )
    return writer.write_up(render_transcript(meeting, header))

def notable_passages(
    meeting: Transcribed,
    duree_visee: float = 300.0,
    duree_minimale: float = 8.0,
) -> list[Span]:
    """The passages to splice together to hear the essentials again."""
    temps = meeting.speaking_time()
    total = sum(temps.values()) or 1.0
    retenus: list[Span] = []

    for voice, is_speaking in temps.items():
        quota = duree_visee * (is_speaking / total)
        if quota < duree_minimale:
            continue
        candidats = sorted(
            (t.span for t in meeting.turns if t.voice == voice),
            key=lambda i: -i.duration,
        )
        cumul = 0.0
        for span in candidats:
            if cumul >= quota:
                break
            if span.duration < duree_minimale:
                continue
            end = min(span.end, span.start + max(duree_minimale, quota - cumul))
            retenus.append(Span(span.start, end))
            cumul += end - span.start

    return sorted(retenus, key=lambda i: i.start)

def assemble(audio: Path, passages: list[Span], destination: Path) -> Path:
    """Cuts and stitches the passages into a single file."""
    if not passages:
        raise ValueError("aucun passage à monter")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as job:
        folder = Path(job)
        chunks = []
        for number, passage in enumerate(passages):
            morceau = folder / f"{number:03d}.wav"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", f"{passage.start:.3f}", "-t", f"{passage.duration:.3f}",
                 "-i", str(audio), "-c:a", "pcm_s16le", str(morceau)],
                check=True,
            )
            chunks.append(morceau)
        listing = folder / "liste.txt"
        listing.write_text(
            "\n".join(f"file '{m}'" for m in chunks) + "\n", encoding="utf-8"
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(listing), "-c:a", "aac", "-b:a", "96k",
             str(destination)],
            check=True,
        )
    return destination

def speak_aloud(text: str, destination: Path) -> Path:
    """Records the minutes read out by the system's synthesiser."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    propre = _sans_balisage(text)

    if SYSTEM == "Darwin":
        with tempfile.TemporaryDirectory() as job:
            brut = Path(job) / "lecture.aiff"
            subprocess.run(["say", "-v", "Thomas", "-o", str(brut), propre], check=True)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
                 "-c:a", "aac", "-b:a", "96k", str(destination)],
                check=True,
            )
        return destination
    if shutil.which("espeak-ng"):
        subprocess.run(
            ["espeak-ng", "-v", "fr", "-w", str(destination.with_suffix(".wav")), propre],
            check=True,
        )
        return destination.with_suffix(".wav")
    raise RuntimeError(
        "Aucune synthèse vocale disponible. Sur Linux : « apt install espeak-ng »."
    )

def _sans_balisage(text: str) -> str:
    """Strips the Markdown of what is not pronounced."""
    import re

    propre = re.sub(r"^\s*\|.*\|\s*$", "", text, flags=re.MULTILINE)  # tableaux
    propre = re.sub(r"[*_`#>]+", "", propre)
    propre = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", propre)           # liens
    propre = re.sub(r"\n{3,}", "\n\n", propre)
    return propre.strip()

def archiver(audio: Path, garder_original: bool = False) -> Path:
    """Compresses a processed recording."""
    if audio.suffix == ".opus":
        return audio
    destination = audio.with_suffix(".opus")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
         "-c:a", "libopus", "-b:a", "24k", "-application", "voip", str(destination)],
        check=True,
    )
    if not garder_original:
        audio.unlink()
    return destination

def voiceprints_per_voice(
    extractor: Any, audio: Path, per_voice: dict[str, list[Any]]
) -> dict[str, list[Any]]:
    """The voiceprints of each voice, reading the recording only once."""
    tous = [(voice, i) for voice, intervalles in per_voice.items() for i in intervalles]
    voiceprints = extractor.extract_spans(audio, [i for _, i in tous])
    if len(voiceprints) != len(tous):
        return {
            voice: extractor.extract_spans(audio, intervalles)
            for voice, intervalles in per_voice.items()
        }
    groupees: dict[str, list[Any]] = {voice: [] for voice in per_voice}
    for (voice, _), voiceprint in zip(tous, voiceprints, strict=True):
        groupees[voice].append(voiceprint)
    return groupees

def review_voices(
    meeting: Any,
    extractor: Any,
    bank: Any = None,
) -> tuple[int, int]:
    """Replays voice stitching on an already processed meeting."""
    from dataclasses import replace as _remplacer

    from greffier.domain import voiceprints as voix_domaine

    avant = {t.voice for t in meeting.turns if t.voice}
    per_voice: dict[str, list[Any]] = {}
    for turn in meeting.turns:
        per_voice.setdefault(turn.voice, []).append(turn.span)
    voiceprints = voiceprints_per_voice(extractor, meeting.audio, per_voice)
    membership = voix_domaine.stitch(voiceprints)

    meeting.turns = [
        _remplacer(t, voice=membership.get(t.voice, t.voice)) for t in meeting.turns
    ]
    for utterance in meeting.utterances:
        if utterance.voice is not None:
            utterance.voice = membership.get(utterance.voice, utterance.voice)
    temps = meeting.speaking_time()
    names: dict[str, str] = {}
    for voice, name in sorted(meeting.names.items(), key=lambda x: -temps.get(x[0], 0.0)):
        vers = membership.get(voice, voice)
        if vers in names and names[vers].casefold() != name.casefold():
            meeting.propositions.setdefault(vers, name)
            continue
        names[vers] = name
    meeting.names = names
    meeting.propositions = {
        membership.get(v, v): n for v, n in meeting.propositions.items()
        if membership.get(v, v) not in names
    }
    if bank is not None:
        _reconnaitre_a_nouveau(meeting, voiceprints, membership, bank)
    _join_namesakes(meeting)
    return len(avant), len({t.voice for t in meeting.turns if t.voice})

def _join_namesakes(meeting: Any) -> None:
    """Two voices carrying the same name are one person."""
    temps = meeting.speaking_time()
    for name in {n.casefold() for n in meeting.names.values()}:
        portantes = sorted(
            (v for v, porte in meeting.names.items() if porte.casefold() == name),
            key=lambda v: -temps.get(v, 0.0),
        )
        gardee = portantes[0]
        for absorbee in portantes[1:]:
            meeting.join_into(absorbee, gardee)
        if portantes[1:]:
            meeting.names[gardee] = next(
                n for n in meeting.names.values() if n.casefold() == name
            ) if gardee in meeting.names else meeting.names.get(gardee, "")

def _reconnaitre_a_nouveau(
    meeting: Any,
    voiceprints: dict[str, list[Any]],
    membership: dict[str, str],
    bank: Any,
) -> None:
    """Asks the bank again who the voices are, once stitched."""
    from greffier.domain import voiceprints as voix_domaine

    connues = bank.people()
    if not connues:
        return
    groupes: dict[str, list[Any]] = {}
    for voice, listing in voiceprints.items():
        groupes.setdefault(membership.get(voice, voice), []).extend(listing)
    for voice, listing in groupes.items():
        if voice in meeting.names or not listing:
            continue
        match = voix_domaine.recognise(voix_domaine.aggregate(listing), connues)
        if match and match.sure:
            meeting.names[voice] = match.name
            meeting.propositions.pop(voice, None)
