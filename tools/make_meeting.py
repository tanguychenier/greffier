#!/usr/bin/env python3
"""Makes a fake two-voice meeting, for the integration tests.

Real meetings cannot serve as a test set: they hold working exchanges and
identifiable voices. A dialogue is therefore synthesised with two system
voices, which gives a real audio file, put through the same path as any
recording, carrying no personal data at all, and replayable by anybody.

    python3 tools/make_meeting.py output.wav

Two synthesis engines, depending on the machine: « say » on macOS, and
elsewhere the VITS voice the tool already installs for the assistant, driven by
the same sherpa-onnx that serves the segmentation. No new dependency, no
network call. The French network carries two timbres, which is enough for the
two-voice dialogue and not for the meeting round a table, which stays on
« say ».
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

# The dialogue is written to exercise the three ways of naming somebody, and so
# that each voice gathers enough evidence to be certain:
#   Jacques  introduces himself (3) + « Merci Jacques » (1) = 4
#   Sandy    addressed by name (2) + « Merci Sandy » (1)    = 3
# Every line runs past three seconds, below which a voiceprint does not carry
# enough voice to be worth anything.
_DIALOGUE = [
    ("A", "Bonjour à tous, moi c'est {first}, je vous propose de commencer par le "
          "point sur la recette, qui nous occupe depuis le début de la semaine."),
    ("B", "Merci {first}. De mon côté, le déploiement en préproduction est terminé "
          "depuis vendredi dernier, et tout s'est déroulé sans incident notable."),
    ("A", "{second}, tu peux nous dire où en sont les anomalies bloquantes sur le "
          "module de facturation, celles que nous avions relevées la semaine dernière ?"),
    ("B", "Il en reste exactement deux. Elles sont corrigées depuis hier soir, mais "
          "elles ne sont pas encore validées par l'équipe fonctionnelle."),
    ("A", "Merci {second}. On décale donc la recette à jeudi prochain, et nous "
          "préviendrons l'ensemble des utilisateurs concernés mercredi en fin de journée."),
]

#: The two first names, per engine -- a first name a synthesiser mangles proves
#: nothing about the chain. Measured on the two lines that carry it: the French
#: VITS says « Sandy » in a way whisper writes « Samy », then « Sani », which
#: would have the chain fail on a word nobody pronounced. « Sophie » comes back
#: intact from both, and so does « Jacques ».
FIRST_NAMES = {"say": ("Jacques", "Sandy"), "vits": ("Jacques", "Sophie")}


def first_names() -> tuple[str, str]:
    """The two first names this machine's synthesiser can be trusted with."""
    return FIRST_NAMES[synthesis_engine() or "say"]


def two_voice_dialogue() -> list[tuple[str, str]]:
    """The two-voice dialogue, carrying the first names of this machine."""
    first, second = first_names()
    return [(who, line.format(first=first, second=second)) for who, line in _DIALOGUE]

# A second meeting, the same voices but **no first name spoken**. It is what
# proves the voice bank: if names come out anyway, they can only come from
# recognising the voices.
DIALOGUE_WITHOUT_NAMES = [
    ("A", "On reprend là où nous nous étions arrêtés la dernière fois, avec le "
          "calendrier de la semaine prochaine et les points encore en suspens."),
    ("B", "Les deux anomalies sont validées depuis ce matin, la version peut donc "
          "partir en production dès que vous donnez votre accord."),
    ("A", "Parfait, dans ce cas nous lançons la mise en production demain matin, "
          "et je préviens les utilisateurs dès cet après-midi par courriel."),
    ("B", "Je prépare la procédure de retour arrière au cas où, et je la partagerai "
          "avec l'équipe avant la fin de la journée."),
]

# A meeting held **round a table**: three people, one microphone, no system
# loopback. The channel then designates nobody, which is the whole point of the
# case: it is the only configuration where attribution rests on the
# segmentation and the voice bank alone.
DIALOGUE_PRESENTIEL = [
    ("A", "Bonjour à tous, moi c'est Jacques, on se retrouve autour de la table pour "
          "faire le point sur le calendrier de la recette, qui nous occupe depuis lundi."),
    ("B", "Merci Jacques. De mon côté la préproduction est en place depuis vendredi, "
          "et je n'ai relevé aucun incident sur les traitements de nuit."),
    ("A", "Pierre, tu peux nous dire où en est la reprise des données, celle que nous "
          "avions repoussée la semaine dernière ?"),
    ("C", "Elle est terminée depuis hier soir. Il reste à valider les écarts de "
          "facturation, ce que l'équipe fonctionnelle fera demain matin."),
    ("A", "Merci Pierre. On garde donc jeudi pour la recette, et nous préviendrons "
          "les utilisateurs mercredi en fin de journée."),
    ("B", "Je m'occupe du message aux utilisateurs, et je le fais relire avant de "
          "l'envoyer à l'ensemble des services concernés."),
]

#: Three voices for the room. Sandy neither introduces herself nor is ever
#: addressed by name: she has to stay a voice waiting for one, and if she does
#: not, the chain is inventing.
#: The voices that lend their timbre to the dialogue. **Not the ones carrying
#: the first names in it**: « Jacques », « Sandy » and « Rocko » are
#: « eloquence » voices, the formant synthesiser macOS has dragged along since
#: the nineteen-eighties. Measured: whisper gets **nothing at all** out of them.
#: On a forty-five-second test meeting, both lines of the « Sandy » voice were
#: absent from the transcript, with or without speech detection, at a level
#: identical to the others. The test set was therefore proving that the chain
#: could not find a first name, when it had never been handed the sentence
#: carrying it.
#:
#: « Thomas » and « Amélie » are concatenative voices: audibly synthetic, but a
#: transcription model understands them, which is all that is asked of them.
IN_ROOM_VOICE = {"A": "Thomas", "B": "Amélie", "C": "Rocko"}

#: Leak measured in the system loopback of a meeting held round a table: -53 dB
#: instead of the expected silence, sound having leaked into it at some point.
#: That is **exactly** the case that trapped the verdict, when a loopback that
#: was not strictly nil was enough to conclude « video call ». Hence a leak in
#: the test file, rather than a silent second channel that would make the test
#: too easy.
LEAK_DB = -40.0


# Two voices as far apart as possible: the segmentation has to tell them apart,
# or the test would measure the speech synthesis rather than the chain.
VOICE = {"A": "Thomas", "B": "Amélie"}
SILENCE = 0.4  # seconds between two lines, as in a real discussion

#: In a dialogue, a line whose speaker is this is a pause: its text is the
#: number of seconds nobody talks, the time a room leaves the assistant to answer.
PAUSE = None


#: The speaker ids of the French VITS voice, for machines without « say ».
#: Two timbres and not three: the network carries two (`num_speakers = 2`),
#: which is what the two-voice dialogue needs and what the round table does not.
SID_VITS = {"Thomas": 0, "Amélie": 1}

_LOADED: dict[int, object] = {}


def _installed_voice() -> Path | None:
    """The assistant's voice folder, when this machine has one.

    Read through the settings rather than guessed: the folder follows
    `chemins.modeles`, which a machine may well have moved.
    """
    try:
        from greffier.adapters.configuration import Config
        from greffier.adapters.voice_neural import NeuralVoice
    except ImportError:  # launched outside the venv, without the package
        return None
    folder = Config().paths.models / "voix"
    return folder if NeuralVoice(folder).installed else None


def synthesis_engine() -> str | None:
    """« say », the installed VITS voice, or nothing at all.

    ffmpeg is required either way: it is what resamples and stitches, and
    without it there is no meeting to build.
    """
    if not shutil.which("ffmpeg"):
        return None
    if shutil.which("say"):
        return "say"
    return "vits" if _installed_voice() is not None else None


def _speak(engine: str, voice: str, text: str, folder: Path, index: int) -> Path:
    """One line spoken into a file, by whichever engine the machine has."""
    if engine == "say":
        raw = folder / f"{index:02d}.aiff"
        subprocess.run(
            ["say", "-v", voice, "-o", str(raw), text], check=True, capture_output=True,
        )
        return raw
    from greffier.adapters.voice_neural import NeuralVoice

    sid = SID_VITS[voice]
    if sid not in _LOADED:
        # One instance per timbre, kept: the network is loaded on first use and
        # reloading it for every line would cost more than the meeting itself.
        _LOADED[sid] = NeuralVoice(_installed_voice(), voice=sid, rate=1.0)
    raw = folder / f"{index:02d}-brut.wav"
    if _LOADED[sid].build_one(text, raw) is None:
        raise RuntimeError(f"la synthèse n'a rien produit pour « {text[:40]}… »")
    return raw


def speak(text: str, voice: str, destination: Path) -> Path | None:
    """One line spoken into `destination`, as the 16 kHz mono wav the chain reads.

    The public door: the integration tests that build their own take -- the live
    thread, the assistant's exchanges -- called `say` directly, each with its own
    copy of the ffmpeg conversion, and skipped everywhere else.
    """
    engine = synthesis_engine()
    if engine is None:
        return None
    if engine != "say" and voice not in SID_VITS:
        return None
    with tempfile.TemporaryDirectory() as folder:
        raw = _speak(engine, voice, text, Path(folder), 0)
        if not raw.exists():
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(destination)],
            check=True,
        )
    return destination


def make(destination: Path, voice: dict | None = None, dialogue=None) -> Path:
    engine = synthesis_engine()
    if engine is None:
        raise RuntimeError(
            "aucune synthèse vocale : « say » sur macOS, sinon la voix de "
            "l'assistant (« python3 tools/install.py »), et ffmpeg dans les deux cas"
        )

    voice = voice or VOICE
    lines = dialogue if dialogue is not None else two_voice_dialogue()
    if engine == "vits":
        unknown_ones = sorted({name for name in voice.values() if name not in SID_VITS})
        if unknown_ones:
            raise RuntimeError(
                f"la voix installée porte {len(SID_VITS)} timbres ; "
                f"{', '.join(unknown_ones)} demande « say »"
            )
    with tempfile.TemporaryDirectory() as folder:
        job = Path(folder)
        chunks: list[Path] = []
        for index, (speaker_index, text) in enumerate(lines):
            if speaker_index is PAUSE:
                chunks.append(_silence(job, float(text), f"{index:02d}-pause"))
            else:
                chunks.append(_speak(engine, voice[speaker_index], text, job, index))

        silence = _silence(job, SILENCE, "silence")

        listing = job / "liste.txt"
        entries = []
        timeline: list[dict[str, object]] = []
        cursor = 0.0
        for (speaker_index, text), chunk in zip(lines, chunks, strict=True):
            converted = chunk.with_name(chunk.stem.removesuffix("-brut") + "-16k.wav")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(chunk),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(converted)],
                check=True,
            )
            entries += [converted, silence]
            length = _length(converted)
            if speaker_index is not PAUSE:
                timeline.append({"speaker": speaker_index, "text": text,
                                 "start": round(cursor, 2), "end": round(cursor + length, 2)})
            cursor += length + SILENCE
        listing.write_text(
            "\n".join(f"file '{path}'" for path in entries) + "\n", encoding="utf-8"
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(listing), "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", str(destination)],
            check=True,
        )
        # Where each line falls, for whoever measures a delay against the file.
        destination.with_suffix(".timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return destination


def _silence(job: Path, seconds: float, name: str) -> Path:
    file = job / f"{name}.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"anullsrc=r=16000:cl=mono:d={seconds}", str(file)],
        check=True,
    )
    return file


def _length(wav: Path) -> float:
    """Seconds of a 16 kHz mono wav, read from its header."""
    with wave.open(str(wav), "rb") as read:
        return read.getnframes() / read.getframerate()


def make_in_the_room(destination: Path) -> Path:
    """Makes a meeting round a table: three voices on the microphone, a leaking loopback.

    The file is **stereo**, the way the recording device renders it: channel 0
    the microphone, channel 1 the system loopback. Round a table the loopback
    carries nothing useful, just the leak measured at -53 dB on the real
    meeting.

    A strictly silent second channel would have made the test too easy: it is
    precisely the leak that wrongly concluded « video call », and attributed
    the whole meeting to whoever was recording.
    """
    with tempfile.TemporaryDirectory() as folder:
        melange = Path(folder) / "micro.wav"
        make(melange, voice=IN_ROOM_VOICE, dialogue=DIALOGUE_PRESENTIEL)
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(melange),
             "-filter_complex",
             f"[0:a]asplit=2[m][f];[f]volume={LEAK_DB}dB[b];[m][b]amerge=inputs=2[s]",
             "-map", "[s]", "-ar", "16000", "-ac", "2", "-c:a", "pcm_s16le",
             str(destination)],
            check=True,
        )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--in-the-room", action="store_true",
        help="trois voix autour d'une table, en stéréo, au lieu de deux en mono",
    )
    arguments = parser.parse_args()
    path = (
        make_in_the_room(arguments.output)
        if arguments.in_the_room
        else make(arguments.output)
    )
    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(path)], capture_output=True, text=True, check=False,
    ).stdout.strip()
    utterances, voice, channels = (
        (len(DIALOGUE_PRESENTIEL), 3, "stéréo")
        if arguments.in_the_room
        else (len(_DIALOGUE), 2, "mono")
    )
    print(f"{path} : {float(duration):.1f} s, {utterances} répliques, {voice} voix, {channels}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
