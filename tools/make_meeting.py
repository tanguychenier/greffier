#!/usr/bin/env python3
"""Fabrique une fausse réunion à deux voix, pour les tests d'intégration.

Les vraies réunions ne peuvent pas servir de jeu d'essai : elles contiennent des
échanges de travail et des voix identifiables. On synthétise donc un dialogue
avec deux voix du système, ce qui donne un fichier audio réel, passé par le
même chemin que n'importe quel enregistrement, sans la moindre donnée
personnelle, et rejouable par qui veut.

    python3 tools/make_meeting.py sortie.wav

Deux moteurs de synthèse, selon le poste : « say » sur macOS, et ailleurs la
voix VITS que Greffier installe déjà pour l'assistant, tenue par le sherpa-onnx
qui sert à la segmentation, aucune dépendance nouvelle, aucun appel réseau.
Le réseau français porte deux timbres, ce qui suffit au dialogue à deux voix et
pas à la réunion de table, qui reste sur « say ».
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Le dialogue est écrit pour exercer les trois façons de nommer quelqu'un, et
# pour que chaque voix accumule assez d'indices pour être certaine :
#   Jacques  auto-présentation (3) + « Merci Jacques » (1) = 4
#   Sandy    interpellation (2) + « Merci Sandy » (1)      = 3
# Chaque réplique dépasse trois secondes, seuil en deçà duquel une empreinte
# vocale ne porte pas assez de voix pour être exploitable.
_DIALOGUE = [
    ("A", "Bonjour à tous, moi c'est {premier}, je vous propose de commencer par le "
          "point sur la recette, qui nous occupe depuis le début de la semaine."),
    ("B", "Merci {premier}. De mon côté, le déploiement en préproduction est terminé "
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
PRENOMS = {"say": ("Jacques", "Sandy"), "vits": ("Jacques", "Sophie")}


def first_names() -> tuple[str, str]:
    """The two first names this machine's synthesiser can be trusted with."""
    return PRENOMS[synthesis_engine() or "say"]


def two_voice_dialogue() -> list[tuple[str, str]]:
    """The two-voice dialogue, carrying the first names of this machine."""
    premier, second = first_names()
    return [(who, line.format(premier=premier, second=second)) for who, line in _DIALOGUE]

# Une seconde réunion, avec les mêmes voix mais **aucun prénom prononcé**. Elle
# sert à prouver la banque de voix : si des noms apparaissent malgré tout, ils ne
# peuvent venir que de la reconnaissance vocale.
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

# Une réunion tenue **autour d'une table** : trois personnes, un seul micro,
# aucune boucle système. Le canal ne désigne alors personne, et c'est tout
# l'intérêt du cas, c'est la seule configuration où l'attribution ne repose que
# sur la segmentation et la banque de voix.
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

#: Trois voix pour le présentiel. Sandy ne se présente pas et n'est jamais
#: interpellée : elle doit rester une voix à nommer, sinon c'est que la chaîne
#: invente.
#: Les voix qui prêtent leur timbre au dialogue. **Pas celles qui portent les
#: prénoms du dialogue** : « Jacques », « Sandy » et « Rocko » sont des voix
#: « eloquence », le synthétiseur par formants que macOS traîne depuis les
#: années 1980. Mesuré : whisper n'en tire **rien du tout** : sur une réunion
#: d'essai de quarante-cinq secondes, les deux répliques de la voix « Sandy »
#: étaient absentes de la transcription, avec ou sans détection de parole, à
#: niveau sonore pourtant identique aux autres. Le jeu d'essai prouvait donc que
#: la chaîne ne retrouvait pas un prénom, quand elle n'avait jamais reçu la
#: phrase qui le porte.
#:
#: « Thomas » et « Amélie » sont des voix par concaténation : elles s'entendent,
#: mais un modèle de transcription les comprend, ce qui est tout ce qu'on leur
#: demande ici.
VOIX_PRESENTIEL = {"A": "Thomas", "B": "Amélie", "C": "Rocko"}

#: Fuite mesurée dans la boucle système d'une réunion tenue autour d'une table :
#: -53 dB au lieu du silence attendu, du son y ayant fui à un moment. C'est
#: **exactement** le cas qui piégeait le verdict, quand une boucle non nulle
#: suffisait à conclure « visio », d'où une fuite dans le fichier d'essai, et
#: non un second canal muet qui rendrait l'épreuve trop facile.
FUITE_DB = -40.0


# Deux voix aussi éloignées que possible : la segmentation doit pouvoir les
# distinguer, sinon le test mesurerait la synthèse vocale et non la chaîne.
VOICE = {"A": "Thomas", "B": "Amélie"}
SILENCE = 0.4  # secondes entre deux répliques, comme dans une vraie discussion


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
    except ImportError:  # lancé hors du venv, sans le paquet
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
    if _LOADED[sid].fabriquer(text, raw) is None:
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
    lignes = dialogue if dialogue is not None else two_voice_dialogue()
    if engine == "vits":
        inconnues = sorted({name for name in voice.values() if name not in SID_VITS})
        if inconnues:
            raise RuntimeError(
                f"la voix installée porte {len(SID_VITS)} timbres ; "
                f"{', '.join(inconnues)} demande « say »"
            )
    with tempfile.TemporaryDirectory() as folder:
        job = Path(folder)
        chunks = []
        for index, (speaker_index, text) in enumerate(lignes):
            chunks.append(_speak(engine, voice[speaker_index], text, job, index))

        silence = job / "silence.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"anullsrc=r=16000:cl=mono:d={SILENCE}", str(silence)],
            check=True,
        )

        listing = job / "liste.txt"
        entrees = []
        for morceau in chunks:
            converti = morceau.with_name(morceau.stem.removesuffix("-brut") + "-16k.wav")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(morceau),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(converti)],
                check=True,
            )
            entrees += [converti, silence]
        listing.write_text(
            "\n".join(f"file '{path}'" for path in entrees) + "\n", encoding="utf-8"
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(listing), "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", str(destination)],
            check=True,
        )
    return destination


def make_in_the_room(destination: Path) -> Path:
    """Fabrique une réunion de table : trois voix sur le micro, une boucle qui fuit.

    Le fichier est **stéréo**, comme ce que rend le périphérique d'enregistrement :
    canal 0 le micro, canal 1 la boucle système. Autour d'une table, la boucle ne
    porte rien d'utile, juste la fuite mesurée à -53 dB sur la vraie réunion.

    Un second canal strictement muet aurait rendu l'épreuve trop facile : c'est
    précisément la fuite qui faisait conclure « visio » à tort, et attribuait
    toute la réunion à la personne qui enregistrait.
    """
    with tempfile.TemporaryDirectory() as folder:
        melange = Path(folder) / "micro.wav"
        make(melange, voice=VOIX_PRESENTIEL, dialogue=DIALOGUE_PRESENTIEL)
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(melange),
             "-filter_complex",
             f"[0:a]asplit=2[m][f];[f]volume={FUITE_DB}dB[b];[m][b]amerge=inputs=2[s]",
             "-map", "[s]", "-ar", "16000", "-ac", "2", "-c:a", "pcm_s16le",
             str(destination)],
            check=True,
        )
    return destination


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("output", type=Path)
    analyseur.add_argument(
        "--in-the-room", action="store_true",
        help="trois voix autour d'une table, en stéréo, au lieu de deux en mono",
    )
    arguments = analyseur.parse_args()
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
