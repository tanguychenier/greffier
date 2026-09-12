"""Composition root: here, and only here, is what is plugged where.

Every other module receives what it needs and knows nothing of who built it.
That is what makes the domain testable without audio, without a model and
without a network.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from greffier.adapters.audio_ffmpeg import FfmpegRecorder
from greffier.adapters.channels_file import FileChannelReader
from greffier.adapters.configuration import Config
from greffier.adapters.devices_coreaudio import CoreAudioLister
from greffier.adapters.diarisation_sherpa import SherpaDiariser
from greffier.adapters.email import (
    FileSender,
    OutlookSender,
    SmtpSender,
)
from greffier.adapters.notifications import SystemNotifier
from greffier.adapters.store_files import FileStore
from greffier.adapters.voice_bank_files import FileVoiceBank
from greffier.adapters.voiceprints_titanet import TitaNetExtractor
from greffier.adapters.writer_ollama import OllamaWriter
from greffier.application.follow import Follower, files, known_people
from greffier.application.name_voice import Naming
from greffier.application.process import Chain
from greffier.application.record import Recording
from greffier.application.take_part import AssistantSettings
from greffier.domain.context import Context as WorkContext
from greffier.domain.live import Certainty, LiveThread
from greffier.domain.names import NamedSpan
from greffier.domain.participation import Manners
from greffier.ports import outbound


def _transcriber(config: Config) -> outbound.Transcriber:
    models = config.paths.models
    if config.transcription.engine == "whisper.cpp":
        from greffier.adapters.transcription_whisper_cpp import WhisperCppTranscriber

        return WhisperCppTranscriber(
            model=models / "ggml-large-v3-turbo.bin",
            vad=models / "ggml-silero-v5.1.2.bin",
        )
    from greffier.adapters.transcription_faster_whisper import FasterWhisperTranscriber

    return FasterWhisperTranscriber(taille=config.transcription.model)

def _live_model(config: Config) -> str:
    """The model this machine can run in the noise of a recording."""
    from greffier.adapters import system_diagnostic as diagnostic

    return diagnostic.recorder(config.paths.data).advised_model

def light_transcriber(config: Config) -> outbound.Transcriber | None:
    """The live transcription model: fast rather than precise."""
    taille = config.live.model or _live_model(config)
    if config.transcription.engine == "whisper.cpp":
        models = config.paths.models
        candidats = [models / f"ggml-{taille}.bin", models / "ggml-large-v3-turbo.bin"]
        model = next((m for m in candidats if m.exists()), None)
        if model is None:
            return None
        from greffier.adapters.transcription_whisper_cpp import WhisperCppTranscriber

        return WhisperCppTranscriber(model=model, vad=None)
    from greffier.adapters.transcription_faster_whisper import FasterWhisperTranscriber

    return FasterWhisperTranscriber(taille=taille)

def follower(config: Config, identifier: str) -> Follower:
    """The thread shown during the meeting, and what feeds it."""
    log, requests = files(config.paths.live, identifier)
    bank = FileVoiceBank(config.paths.voice_bank)
    extractor: outbound.VoiceprintExtractor | None = None
    try:
        extractor = TitaNetExtractor(
            config.paths.models / "diarisation" / "nemo_en_titanet_large.onnx"
        )
    except FileNotFoundError:
        extractor = None
    return Follower(
        thread=LiveThread(known=known_people(bank),
                people=config.speakers.people),
        log=log,
        requests=requests,
        channels=FileChannelReader(),
        extractor=extractor,
        bank=bank,
        identifier=identifier,
    )

def writer(config: Config) -> outbound.Writer | None:
    """The writer alone, to regenerate a set of minutes."""
    engine = config.minutes.engine
    language = config.minutes.language or config.transcription.language
    if engine == "ollama":
        return OllamaWriter(config.minutes.effective_model, language=language)
    if engine == "claude":
        from greffier.adapters.writer_claude import ClaudeWriter

        return ClaudeWriter(
            config.minutes.effective_model,
            timeout=config.minutes.timeout,
            language=language,
        )
    return None

def assistant(config: Config) -> outbound.Writer | None:
    """Who answers in the conversation — not who writes the minutes."""
    engine = config.minutes.engine
    if engine == "ollama":
        return OllamaWriter(config.minutes.effective_model,
                               language=config.minutes.language)
    if engine != "claude":
        return None
    from greffier.adapters.writer_claude import (
        CONSIGNES_CONVERSATION,
        ClaudeWriter,
    )

    return ClaudeWriter(
        config.minutes.effective_model,
        timeout=config.minutes.timeout,
        language=config.minutes.language,
        tools=(ClaudeWriter.SEARCH_TOOLS
                if config.conversation.recherche_web else ()),
        consignes_propres=CONSIGNES_CONVERSATION,
    )

def cartographe(config: Config) -> outbound.Writer | None:
    """Who extracts a board's points."""
    engine = config.minutes.engine
    if engine == "ollama":
        return OllamaWriter(config.minutes.effective_model,
                               language=config.minutes.language)
    if engine != "claude":
        return None
    from greffier.adapters.writer_claude import ClaudeWriter
    from greffier.application.map_subjects import GUIDANCE

    return ClaudeWriter(
        config.minutes.effective_model,
        timeout=config.minutes.timeout,
        language=config.minutes.language,
        consignes_propres=GUIDANCE,
    )

def store(config: Config) -> FileStore:
    """The master files, a meeting's source of truth."""
    return FileStore(config.paths.data / "reunions")

def naming(config: Config) -> Naming:
    """The "give a voice a name" use case, after the meeting."""
    diarisation = config.paths.models / "diarisation"
    return Naming(
        store=store(config),
        bank=FileVoiceBank(config.paths.voice_bank),
        extractor=TitaNetExtractor(diarisation / "nemo_en_titanet_large.onnx"),
    )

def _instructions_of(config: Config) -> Callable[[str], list[str]]:
    """Reads what was asked of the tool during a meeting, for the writer.

    Only the human's own turns: the notes and the assistant's answers are not
    instructions. Read at run time and not wired once, because the file belongs
    to the meeting being processed.
    """
    from greffier.adapters import conversations_file

    def lire(identifier: str) -> list[str]:
        turns = conversations_file.read(
            conversations_file.file_for(config.paths.conversations, identifier),
            derniers=0,
        )
        return [x.text.strip() for x in turns if x.who == "moi" and x.text.strip()]

    return lire


def _named_live(config: Config) -> Callable[[str], list[NamedSpan]]:
    """The stretches a human named in the window while the meeting ran.

    Read at run time like the instructions, and from the same place the window
    writes: the live log holds the corrections with the sentences they cover.
    """
    from greffier.application.follow import files, read_from, replay
    from greffier.domain.live import LiveThread

    def lire(identifier: str) -> list[NamedSpan]:
        log, _ = files(config.paths.live, identifier)
        lines, _ = read_from(log, 0)
        thread = LiveThread()
        replay(lines, thread)
        named = []
        for turn in thread.turns:
            voice = thread.voice.get(turn.voice)
            if voice is None or voice.name is None:
                continue
            if voice.certainty is not Certainty.HUMAINE:
                continue
            named.append(NamedSpan(name=voice.name, span=turn.span))
        return named

    return lire


def context(config: Config) -> WorkContext:
    """What the tool knows of the setting, blended from its three sources.

    Least precise first: the vocabulary from config.toml, the names the voice bank
    already knows, then contexte.toml, the only place an acronym carries a meaning.
    """
    from greffier.adapters import context_file

    fondu = context_file.from_vocabulary(config.transcription.vocabulary)
    names = [p.name for p in known_people(FileVoiceBank(config.paths.voice_bank))]
    fondu = fondu.join(context_file.from_the_bank(names))
    return fondu.join(context_file.read(config.paths.context))

def _sender(config: Config, exiger_destinataire: bool = True) -> outbound.Sender | None:
    """How the minutes leave."""
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
    """Audio capture. One construction, three callers."""
    return FfmpegRecorder(config.audio.input, config.audio.maximum_length)

def lister(config: Config) -> CoreAudioLister:
    """Reading the audio hardware, for the watch and the diagnostic."""
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"
    prete = Path(sys.executable).resolve().parent.parent / "Resources/lister-peripheriques"
    return CoreAudioLister(
        source, config.paths.data / "cache", prete if prete.exists() else None
    )

def recording(config: Config) -> Recording:
    """The recording state machine, shared by two commands."""
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
        extractor=TitaNetExtractor(diarisation / "nemo_en_titanet_large.onnx"),
        bank=FileVoiceBank(config.paths.voice_bank),
        writer=writer(config),
        sender=_sender(config),
        log=None,
        notificateur=SystemNotifier(),
        store=store(config),
        dossier_transcriptions=config.paths.transcripts,
        dossier_comptes_rendus=config.paths.minutes_folder,
        language=config.transcription.language,
        prompt_seed=_the_context.prompt_seed(),
        context_header=_the_context.header(),
        instructions=_instructions_of(config),
        named_live=_named_live(config),
        people=config.speakers.people,
        not_first_names=frozenset(m.lower() for m in config.speakers.not_first_names),
        recipient=config.minutes.recipient,
        disclosure=config.conversation.disclosure,
    )

def assistant_voice(config: Config) -> Any | None:
    """Whatever pronounces, or nothing when the assistant takes part in writing."""
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
    """The assistant as a participant in the meeting."""
    if not config.assistant.active:
        return None
    from greffier.adapters import conversations_file

    file = conversations_file.file_for(
        config.paths.conversations, identifier)

    def tracer(who: str, what: str) -> None:
        conversations_file.add(file, who, what)

    lui = AssistantSettings(
        name=config.assistant.name,
        manners=Manners(
            active=True,
            rest=config.assistant.rest,
            creux_minimal=config.assistant.creux_minimal,
        ),
        voice=assistant_voice(config),
        tracer=tracer,
        setting=lambda: context(config).header(),
    )
    cerveau = assistant(config)
    if cerveau is not None and hasattr(cerveau, "consignes_propres"):
        cerveau.consignes_propres = lui.guidance()
        # The same setting as the conversation tab, and for the same reason:
        # its guidance tells it that it may look something up and name the
        # source aloud. Handed no tools, it answered "yes I can search" and
        # "no I have no access" in turn, four times in one meeting.
        from greffier.adapters.writer_claude import ClaudeWriter

        cerveau.tools = (  # type: ignore[attr-defined]
            ClaudeWriter.SEARCH_TOOLS if config.conversation.recherche_web else ()
        )
        if config.conversation.recherche_web:
            # A short sound, the moment a search actually starts. Called by its
            # name the assistant takes a few seconds to answer, and nothing said
            # whether it was thinking or looking something up: waiting without
            # knowing what for is what makes a wait feel long.
            from greffier.adapters.cue_sound import cue

            cerveau.on_search = cue()  # type: ignore[attr-defined]
    lui.cerveau = cerveau
    return lui
