"""Racine de composition : c'est ici, et seulement ici, qu'on choisit les outils.

Le reste du code ne connaît que des ports. Ce module est le seul à savoir que la
transcription passe par whisper.cpp sur macOS et par faster-whisper ailleurs, ou
que la rédaction interroge Ollama. Changer d'outil ne touche que ce fichier.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

from greffier.adapters.audio_ffmpeg import FfmpegRecorder
from greffier.adapters.channels_file import LecteurCanauxFichier
from greffier.adapters.configuration import Config
from greffier.adapters.devices_coreaudio import CoreAudioLister
from greffier.adapters.diarisation_sherpa import SherpaDiariser
from greffier.adapters.email import (
    FileSender,
    OutlookSender,
    SmtpSender,
)
from greffier.adapters.notifications import NotificateurSysteme
from greffier.adapters.store_files import DepotFichiers
from greffier.adapters.voice_bank_files import BanqueFichiers
from greffier.adapters.voiceprints_titanet import ExtracteurTitaNet
from greffier.adapters.writer_ollama import RedacteurOllama
from greffier.application.follow import Follower, files, known_people
from greffier.application.name_voice import Naming
from greffier.application.process import Chain
from greffier.application.record import Recording
from greffier.application.take_part import AssistantSettings
from greffier.domain.context import Contexte as WorkContext
from greffier.domain.live import LiveThread
from greffier.domain.participation import Manners
from greffier.ports import outbound


def _transcriber(config: Config) -> outbound.Transcriber:
    models = config.paths.models
    if config.transcription.engine == "whisper.cpp":
        from greffier.adapters.transcription_whisper_cpp import TranscripteurWhisperCpp

        return TranscripteurWhisperCpp(
            model=models / "ggml-large-v3-turbo.bin",
            vad=models / "ggml-silero-v5.1.2.bin",
        )
    from greffier.adapters.transcription_faster_whisper import TranscripteurFasterWhisper

    return TranscripteurFasterWhisper(taille=config.transcription.model)

def _live_model(config: Config) -> str:
    """Le modèle que cette machine fait tourner dans le budget d'une tranche.

    Le même critère que la transcription définitive : mémoire et accélération
    disponibles. Mesuré sur un Mac Apple Silicon, tranche de dix secondes réelle
    — 0,72 s avec `small`, 1,44 s avec `large-v3-turbo`, pour un budget de dix
    secondes. Le grand modèle tient avec sept fois la marge, et rend une phrase
    là où le petit rendait trois fragments faux.
    """
    from greffier.adapters import system_diagnostic as diagnostic

    return diagnostic.recorder(config.paths.data).advised_model

def light_transcriber(config: Config) -> outbound.Transcriber | None:
    """Le modèle de la transcription en direct : rapide plutôt que juste.

    Il faut rendre une tranche en moins de temps qu'il n'en faut pour en
    enregistrer une autre, sans quoi l'affichage prend du retard qu'il ne
    rattrape jamais. Ce n'est pas une raison de prendre le plus petit modèle :
    sur une machine qui en a les moyens, le grand tient dans le budget et le
    petit rendait le fil illisible — mesuré, pas supposé.

    Rend `None` quand aucun modèle n'est là : le direct affichera alors ce que
    l'audio dit des canaux, et le dira, plutôt que de rester vide sans raison.
    """
    taille = config.live.model or _live_model(config)
    if config.transcription.engine == "whisper.cpp":
        models = config.paths.models
        candidats = [models / f"ggml-{taille}.bin", models / "ggml-large-v3-turbo.bin"]
        model = next((m for m in candidats if m.exists()), None)
        if model is None:
            return None
        from greffier.adapters.transcription_whisper_cpp import TranscripteurWhisperCpp

        return TranscripteurWhisperCpp(model=model, vad=None)
    from greffier.adapters.transcription_faster_whisper import TranscripteurFasterWhisper

    return TranscripteurFasterWhisper(taille=taille)

def follower(config: Config, identifier: str) -> Follower:
    """Le fil affiché pendant la réunion, et ce qui le corrige.

    L'extracteur d'empreintes est facultatif ici, alors qu'il est requis pour le
    traitement : sans lui, le direct montre ce qui se dit et distingue « toi »
    des autres, ce qui est déjà l'essentiel. Refuser de rien afficher parce
    qu'un modèle manque serait le pire des deux mondes.
    """
    log, requests = files(config.paths.live, identifier)
    bank = BanqueFichiers(config.paths.voice_bank)
    extractor: outbound.VoiceprintExtractor | None = None
    try:
        extractor = ExtracteurTitaNet(
            config.paths.models / "diarisation" / "nemo_en_titanet_large.onnx"
        )
    except FileNotFoundError:
        extractor = None
    return Follower(
        thread=LiveThread(connues=known_people(bank),
                people=config.speakers.people),
        log=log,
        requests=requests,
        channels=LecteurCanauxFichier(),
        extractor=extractor,
        bank=bank,
        identifier=identifier,
    )

def writer(config: Config) -> outbound.Writer | None:
    """Le rédacteur seul, pour régénérer un compte rendu sans tout réassembler."""
    engine = config.minutes.engine
    language = config.minutes.language or config.transcription.language
    if engine == "ollama":
        return RedacteurOllama(config.minutes.effective_model, language=language)
    if engine == "claude":
        from greffier.adapters.writer_claude import RedacteurClaude

        return RedacteurClaude(
            config.minutes.effective_model,
            timeout=config.minutes.timeout,
            language=language,
        )
    return None

def assistant(config: Config) -> outbound.Writer | None:
    """Qui répond dans la conversation — pas qui rédige le compte rendu.

    Deux instances, deux réglages, et c'est volontaire. Le rédacteur du compte
    rendu n'a **aucun** outil : le document se compose de ce qui a été dit et de
    rien d'autre, sans quoi une décision pourrait se voir complétée par ce qu'il
    a trouvé ailleurs. La conversation, elle, sert précisément à aller chercher
    — une définition, une norme, l'état d'un service — et refuser de le faire
    obligeait à quitter la réunion pour ouvrir un navigateur.

    La recherche s'éteint depuis les réglages : elle fait sortir du poste le
    terme cherché, et il y a des réunions où cela ne se fait pas.
    """
    engine = config.minutes.engine
    if engine == "ollama":
        return RedacteurOllama(config.minutes.effective_model,
                               language=config.minutes.language)
    if engine != "claude":
        return None
    from greffier.adapters.writer_claude import (
        CONSIGNES_CONVERSATION,
        RedacteurClaude,
    )

    return RedacteurClaude(
        config.minutes.effective_model,
        timeout=config.minutes.timeout,
        language=config.minutes.language,
        outils=(RedacteurClaude.OUTILS_DE_RECHERCHE
                if config.conversation.recherche_web else ()),
        consignes_propres=CONSIGNES_CONVERSATION,
    )

def cartographe(config: Config) -> outbound.Writer | None:
    """Qui extrait les points d'une carte. Ni le rédacteur, ni l'assistant.

    Une troisième instance, et pour une raison mesurée : `RedacteurClaude`
    préfixe les consignes du compte rendu à tout ce qu'on lui passe. Une demande
    d'extraction JSON arrivait donc **après** cent lignes de « tu rédiges le
    compte rendu d'une réunion », et le modèle suivait les premières — il a
    rendu de la prose, en demandant si c'était bien le tableau attendu.
    L'extraction échouait alors en silence, sur « rien à ajouter ».

    Aucun outil : extraire ce qui a été dit ne demande pas d'aller chercher
    ailleurs, et pourrait au contraire faire entrer dans la carte des points
    qui n'ont pas été prononcés.
    """
    engine = config.minutes.engine
    if engine == "ollama":
        return RedacteurOllama(config.minutes.effective_model,
                               language=config.minutes.language)
    if engine != "claude":
        return None
    from greffier.adapters.writer_claude import RedacteurClaude
    from greffier.application.map_subjects import GUIDANCE

    return RedacteurClaude(
        config.minutes.effective_model,
        timeout=config.minutes.timeout,
        language=config.minutes.language,
        consignes_propres=GUIDANCE,
    )

def store(config: Config) -> DepotFichiers:
    """Les fichiers maîtres, source de vérité d'une réunion traitée."""
    return DepotFichiers(config.paths.data / "reunions")

def naming(config: Config) -> Naming:
    """Le cas d'usage « donner un nom à une voix », après la réunion."""
    diarisation = config.paths.models / "diarisation"
    return Naming(
        store=store(config),
        bank=BanqueFichiers(config.paths.voice_bank),
        extractor=ExtracteurTitaNet(diarisation / "nemo_en_titanet_large.onnx"),
    )

def context(config: Config) -> WorkContext:
    """Ce que l'outil sait du milieu, fondu depuis ses trois sources.

    De la moins précise à la plus précise : le vocabulaire de `config.toml`, le
    nom des habitués que la banque de voix connaît déjà, puis `contexte.toml`,
    seul endroit où un sigle porte son sens. La plus précise l'emporte à égalité
    de nom.

    Assemblé ici et non lu à trois endroits : la transcription en direct, la
    transcription définitive et la rédaction ont besoin du même contexte, et
    trois lectures indépendantes finiraient par diverger — c'est exactement ce
    qui faisait que le direct devinait des termes que l'outil connaissait.
    """
    from greffier.adapters import context_file

    fondu = context_file.from_vocabulary(config.transcription.vocabulary)
    names = [p.name for p in known_people(BanqueFichiers(config.paths.voice_bank))]
    fondu = fondu.join(context_file.from_the_bank(names))
    return fondu.join(context_file.read(config.paths.context))

def _sender(config: Config, exiger_destinataire: bool = True) -> outbound.Sender | None:
    """Comment part le compte rendu.

    Outlook là où il existe : le compte est déjà authentifié, donc aucun mot de
    passe à stocker. Sinon SMTP, s'il est renseigné. Sinon rien ne part, et le
    compte rendu reste simplement sur le disque.

    « greffier envoyer » demande le destinataire à l'écran : il passe
    `exiger_destinataire=False` pour obtenir un expéditeur même quand la
    configuration n'en désigne aucun.
    """
    if exiger_destinataire and not config.minutes.recipient:
        return None
    if config.email.server:
        return SmtpSender(
            server=config.email.server,
            port=config.email.port,
            user=config.email.user,
            sender=config.email.sender,
        )
    if platform.system() == "Darwin":
        return OutlookSender()
    return FileSender(config.paths.minutes_folder)

def _audio_recorder(config: Config) -> FfmpegRecorder:
    """La capture audio. Une seule construction, trois appelants."""
    return FfmpegRecorder(config.audio.input, config.audio.duree_maximale)

def lister(config: Config) -> CoreAudioLister:
    """Lecture du matériel audio, pour la veille et le diagnostic."""
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"
    prete = Path(sys.executable).resolve().parent.parent / "Resources/lister-peripheriques"
    return CoreAudioLister(
        source, config.paths.data / "cache", prete if prete.exists() else None
    )

def recording(config: Config) -> Recording:
    """La machine à états de l'enregistrement, partagée entre deux commandes."""
    return Recording(
        audio_recorder=_audio_recorder(config),
        dossier_audio=config.paths.recordings,
        fichier_etat=config.paths.data / "etat.json",
    )

def wire_up(config: Config) -> Chain:
    models = config.paths.models
    diarisation = models / "diarisation"
    _the_context = context(config)
    return Chain(
        audio_recorder=_audio_recorder(config),
        transcriber=_transcriber(config),
        diariser=SherpaDiariser(
            segmentation=diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
            voiceprints=diarisation / "nemo_en_titanet_large.onnx",
        ),
        extractor=ExtracteurTitaNet(diarisation / "nemo_en_titanet_large.onnx"),
        bank=BanqueFichiers(config.paths.voice_bank),
        writer=writer(config),
        sender=_sender(config),
        log=None,
        notificateur=NotificateurSysteme(),
        store=store(config),
        dossier_transcriptions=config.paths.transcripts,
        dossier_comptes_rendus=config.paths.minutes_folder,
        language=config.transcription.language,
        prompt_seed=_the_context.prompt_seed(),
        context_header=_the_context.header(),
        people=config.speakers.people,
        not_first_names=frozenset(m.lower() for m in config.speakers.not_first_names),
        recipient=config.minutes.recipient,
        disclosure=config.conversation.disclosure,
    )

def assistant_voice(config: Config) -> Any | None:
    """Ce qui prononce, ou rien si l'assistant participe par écrit.

    L'ordre est celui de la qualité : la voix neuronale d'abord, celle du
    système ensuite, rien enfin. Un modèle absent ne fait pas taire l'assistant,
    il le fait parler moins bien — et le diagnostic dit comment y remédier.
    """
    voulu = config.assistant.voice
    if voulu == "aucun":
        return None
    if voulu == "kokoro":
        from greffier.adapters.voice_neural import NeuralVoice

        neuronale = NeuralVoice(
            config.paths.synthetic_voice,
            language=config.transcription.language or "fr",
            voice=config.assistant.effective_speaker,
            rate=config.assistant.rate,
            gag=config.paths.gag,
        )
        if neuronale.available:
            return neuronale
    from greffier.adapters.voice_system import SystemVoice

    system = SystemVoice()
    return system if system.available else None

def assistant_of(config: Config, identifier: str) -> AssistantSettings | None:
    """L'assistant en tant que participant à la réunion.

    Rend `None` quand il n'a pas été activé : la fabrique ne décide pas de sa
    présence, elle la construit quand elle est demandée. Une voix qui sort du
    haut-parleur sans qu'on l'ait voulu serait la pire des surprises.
    """
    if not config.assistant.active:
        return None
    from greffier.adapters import conversations_file

    file = conversations_file.file_for(
        config.paths.conversations, identifier)

    def tracer(qui: str, quoi: str) -> None:
        conversations_file.add(file, qui, quoi)

    lui = AssistantSettings(
        name=config.assistant.name,
        manners=Manners(
            active=True,
            rest=config.assistant.rest,
            creux_minimal=config.assistant.creux_minimal,
        ),
        voice=assistant_voice(config),
        tracer=tracer,
    )
    cerveau = assistant(config)
    if cerveau is not None and hasattr(cerveau, "consignes_propres"):
        cerveau.consignes_propres = lui.guidance()
        cerveau.outils = ()  # type: ignore[attr-defined]
    lui.cerveau = cerveau
    return lui
