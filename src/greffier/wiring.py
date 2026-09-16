"""Composition root: here, and only here, is what is plugged where.

Every other module receives what it needs and knows nothing of who built it.
That is what makes the domain testable without audio, without a model and
without a network.
"""

from __future__ import annotations

import contextlib
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
from greffier.application.company_sources import Reading, Sources, read_all
from greffier.application.follow import Follower, Position, files, known_people
from greffier.application.name_voice import Naming
from greffier.application.process import Chain
from greffier.application.record import Recording
from greffier.application.take_part import AssistantSettings
from greffier.domain.context import Context as WorkContext
from greffier.domain.live import Certainty, LiveThread
from greffier.domain.memory import Trace
from greffier.domain.names import NamedSpan
from greffier.domain.participation import Manners
from greffier.domain.preparation import Preparation
from greffier.domain.tongue import Wording
from greffier.ports import outbound


def _the_card_first(config: Config) -> None:
    """Lets the speaker-turn runtime open before the transcription's own.

    Two ONNX Runtimes cannot share a process, and faster-whisper brings one
    along with its voice detector: whichever opens first keeps the card. Asked
    here, in the composition root, because no adapter can know what the others
    will load after it.
    """
    from greffier.adapters import cuda

    cuda.keep_the_place(
        config.paths.models / "diarisation" / "nemo_en_titanet_large.onnx"
    )

def _transcriber(config: Config) -> outbound.Transcriber:
    _the_card_first(config)
    models = config.paths.models
    if config.transcription.engine == "whisper.cpp":
        from greffier.adapters.transcription_whisper_cpp import WhisperCppTranscriber

        return WhisperCppTranscriber(
            model=models / "ggml-large-v3-turbo.bin",
            vad=models / "ggml-silero-v5.1.2.bin",
        )
    from greffier.adapters.transcription_faster_whisper import FasterWhisperTranscriber

    return FasterWhisperTranscriber(
        size=config.transcription.model, device=config.hardware.device
    )

#: The live thread's model where the card takes the large one. Measured on
#: 2026-09-16 (CUDA, int8): large-v3 reads a minute of meeting in 12.1 s and
#: the eight-second listening pass in 1.95 s, more than the ten-second slice
#: it has to keep up with, and every call to the assistant waited behind it.
#: large-v3-turbo does the same in 3.7 s and 1.3 s, and heard the assistant's
#: name eight times out of eight where base and small heard it four.
LIVE_MODEL = "large-v3-turbo"

def _live_model(config: Config) -> str:
    """The model this machine can run in the noise of a recording."""
    from greffier.adapters import system_diagnostic as diagnostic
    from greffier.adapters.model_files import downloaded

    advised = diagnostic.recorder(config.paths.data).advised_model
    if advised != "large-v3":
        return advised
    # Not fetched here: a download of one and a half gigabytes is the
    # installer's business, never a meeting's.
    return LIVE_MODEL if downloaded(LIVE_MODEL) else advised

def light_transcriber(config: Config) -> outbound.Transcriber | None:
    """The live transcription model: fast rather than precise."""
    _the_card_first(config)
    size = config.live.model or _live_model(config)
    if config.transcription.engine == "whisper.cpp":
        models = config.paths.models
        candidates_ = [models / f"ggml-{size}.bin", models / "ggml-large-v3-turbo.bin"]
        model = next((m for m in candidates_ if m.exists()), None)
        if model is None:
            return None
        from greffier.adapters.transcription_whisper_cpp import WhisperCppTranscriber

        return WhisperCppTranscriber(model=model, vad=None)
    from greffier.adapters.transcription_faster_whisper import FasterWhisperTranscriber

    return FasterWhisperTranscriber(size=size, device=config.hardware.device)

#: The model that transcribes a dictated question. Measured on the same
#: thirty-six seconds: 1.8 s with « base » against 9.4 s with « large-v3 », for
#: the same words. A question dictated into the microphone is close, clean and
#: short, which is the one case where the big model buys nothing and costs four
#: times the wait -- and the wait is the whole point of speaking rather than
#: typing.
DICTATION_MODEL = "base"


def dictation_transcriber(config: Config) -> outbound.Transcriber | None:
    """What listens to a question spoken to the assistant, fast rather than fine."""
    _the_card_first(config)
    if config.transcription.engine == "whisper.cpp":
        return light_transcriber(config)
    from greffier.adapters.transcription_faster_whisper import FasterWhisperTranscriber

    return FasterWhisperTranscriber(
        size=DICTATION_MODEL, device=config.hardware.device
    )


def company_sources(config: Config) -> Sources:
    """The registered outside sources, read for the assistant when a token is there."""
    from greffier.adapters import sources_file
    from greffier.adapters.gitlab_api import tickets
    from greffier.adapters.jira_api import requests

    def read() -> list[Reading]:
        return read_all(
            sources_file.read(config.paths.sources),
            sources_file.token_for,
            lambda source, token: [ticket.say() for ticket in tickets(source, token)],
            lambda source, token: [request.say() for request in requests(source, token)],
        )

    return Sources(read)

def somebody_speaking(where_: Position) -> bool | None:
    """Whether the file being written carries speech at this position.

    What the listening thread watches to listen the moment somebody stops,
    rather than on the clock. None when the file cannot be read yet.
    """
    from greffier.adapters.live_levels import read_level
    from greffier.domain.channels import WhoSpeaks

    reading = read_level(where_.chunk, up_to=where_.written)
    return None if reading is None else reading.who is not WhoSpeaks.NOBODY

def follower(config: Config, identifier: str) -> Follower:
    """The thread shown during the meeting, and what feeds it."""
    log, requests = files(config.paths.live, identifier)
    bank = FileVoiceBank(config.paths.voice_bank)
    extractor: outbound.VoiceprintExtractor | None = None
    try:
        extractor = TitaNetExtractor(
            config.paths.models / "diarisation" / "nemo_en_titanet_large.onnx",
            device=config.hardware.device,
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
    """Who answers in the conversation, not who writes the minutes."""
    engine = config.minutes.engine
    if engine == "ollama":
        return OllamaWriter(config.minutes.effective_model,
                               language=config.minutes.language)
    if engine != "claude":
        return None
    from greffier.adapters.writer_claude import (
        CONVERSATION_GUIDANCE,
        ClaudeWriter,
    )

    return ClaudeWriter(
        config.minutes.effective_model,
        timeout=config.minutes.timeout,
        language=config.minutes.language,
        tools=(ClaudeWriter.SEARCH_TOOLS
                if config.conversation.recherche_web else ()),
        own_guidance=CONVERSATION_GUIDANCE,
    )

def mapper(config: Config) -> outbound.Writer | None:
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
        own_guidance=GUIDANCE,
    )

def troubles(config: Config) -> outbound.TroubleLog:
    """Where an incident is written down, so a report can be answered."""
    from greffier.adapters.trouble_file import TroubleFile
    from greffier.adapters.updates import installed_version

    return TroubleFile(config.paths.troubles, installed_version())


def store(config: Config) -> FileStore:
    """The master files, a meeting's source of truth."""
    return FileStore(config.paths.data / "reunions")

def naming(config: Config) -> Naming:
    """The "give a voice a name" use case, after the meeting."""
    diarisation = config.paths.models / "diarisation"
    return Naming(
        store=store(config),
        bank=FileVoiceBank(config.paths.voice_bank),
        extractor=TitaNetExtractor(
            diarisation / "nemo_en_titanet_large.onnx", device=config.hardware.device
        ),
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
            last_ones=0,
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
            if voice.certainty is not Certainty.HUMAN:
                continue
            named.append(NamedSpan(name=voice.name, span=turn.span))
        return named

    return lire


def memory(config: Config) -> outbound.Memory:
    """What earlier meetings left. A file, read whole, written a line at a time."""
    from greffier.adapters import memory_file

    file = config.paths.memory

    class TheMemory:
        def remember(self, trace: Trace) -> None:
            memory_file.remember(file, trace)
            _index(config, trace)

        def recall(self, limit: int = memory_file.LAST_ONES) -> list[Trace]:
            return memory_file.recall(file, limit)

    return TheMemory()


def _index(config: Config, trace: Trace) -> None:
    from greffier.adapters import graph_sqlite
    from greffier.domain.graph import from_trace

    pending = waiting_preparation(config)
    subject = pending.subject if pending is not None else ""
    nodes, edges = from_trace(trace, subject)
    with contextlib.suppress(Exception):
        graph_sqlite.write(config.paths.graph, nodes, edges)


def known_about(config: Config, subject: str) -> str:
    """What the index knows around a subject, for a meeting being prepared."""
    from greffier.adapters import graph_sqlite

    try:
        return graph_sqlite.known_about(config.paths.graph, subject).header()
    except Exception:  # noqa: BLE001 - an index is a convenience, never a due
        return ""


def what_earlier_meetings_left(config: Config) -> str:
    """The recalled section of the header, empty when nothing was left."""
    from greffier.adapters import memory_file
    from greffier.domain.memory import recalled

    return recalled(memory_file.recall(config.paths.memory))


def waiting_preparation(config: Config) -> Preparation | None:
    """The preparation a meeting starting now would open on, if there is one."""
    from greffier.adapters import preparations_file

    return preparations_file.waiting(config.paths.preparations)


def take_the_preparation(config: Config, identifier: str) -> None:
    """Marks it as taken by this meeting. Consumed once, never twice."""
    from greffier.adapters import preparations_file

    pending = waiting_preparation(config)
    if pending is not None:
        preparations_file.write(
            config.paths.preparations, pending.taken(identifier))


def spoken_language(config: Config) -> str:
    """The language the tool speaks: the setting, or failing that the machine."""
    from greffier.adapters import locale_system
    from greffier.domain.tongue import choose

    return choose(config.interface.language or locale_system.read())


def wording(config: Config) -> Wording:
    """What the tool says, in the language it speaks."""
    from greffier.adapters import wording_files

    return wording_files.wording(spoken_language(config))


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

def _sender(config: Config, require_recipient: bool = True) -> outbound.Sender | None:
    """How the minutes leave."""
    if require_recipient and not config.minutes.recipient:
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

def list_(config: Config) -> CoreAudioLister:
    """Reading the audio hardware, for the watch and the diagnostic."""
    source = Path(__file__).resolve().parent.parent.parent / "macos/creer-peripheriques.swift"
    ready = Path(sys.executable).resolve().parent.parent / "Resources/lister-peripheriques"
    return CoreAudioLister(
        source, config.paths.data / "cache", ready if ready.exists() else None
    )

def recording(config: Config) -> Recording:
    """The recording state machine, shared by two commands."""
    return Recording(
        audio_recorder=_audio_recorder(config),
        audio_folder=config.paths.recordings,
        state_file=config.paths.data / "etat.json",
    )

def wire_up(config: Config) -> Chain:
    from greffier.adapters import her_turns_file

    # Read once, here: the chain is built before the meeting and the preparation
    # cannot change under it. Taken -- marked as consumed -- only when a meeting
    # has actually been recorded, which is the chain's business, not ours.
    _pending = waiting_preparation(config)
    models = config.paths.models
    diarisation = models / "diarisation"
    _the_context = context(config)
    return Chain(
        audio_recorder=_audio_recorder(config),
        transcriber=_transcriber(config),
        diariser=SherpaDiariser(
            segmentation=diarisation / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
            voiceprints=diarisation / "nemo_en_titanet_large.onnx",
            device=config.hardware.device,
        ),
        extractor=TitaNetExtractor(
            diarisation / "nemo_en_titanet_large.onnx", device=config.hardware.device
        ),
        bank=FileVoiceBank(config.paths.voice_bank),
        writer=writer(config),
        sender=_sender(config),
        log=None,
        notificateur=SystemNotifier(),
        store=store(config),
        transcripts_folder=config.paths.transcripts,
        minutes_folder=config.paths.minutes_folder,
        language=config.transcription.language,
        prompt_seed=_the_context.prompt_seed(
            tuple(_pending.expected) if _pending is not None else ()
        ),
        context_header=(
            _the_context.header()
            + what_earlier_meetings_left(config)
            + (_pending.header() if _pending is not None else "")
        ),
        expected_people=tuple(_pending.expected) if _pending is not None else (),
        her_name=config.assistant.name,
        her_turns_of=lambda identifier: tuple(
            her_turns_file.read(her_turns_file.file_for(config.paths.live, identifier))
        ),
        preparation_taken=lambda identifier: take_the_preparation(config, identifier),
        memory=memory(config),
        instructions=_instructions_of(config),
        named_live=_named_live(config),
        people=config.speakers.people,
        not_first_names=frozenset(m.lower() for m in config.speakers.not_first_names),
        recipient=config.minutes.recipient,
        disclosure=config.conversation.disclosure,
    )

def assistant_voice(config: Config) -> Any | None:
    """Whatever pronounces, or nothing when the assistant takes part in writing."""
    wanted_one = config.assistant.voice
    if wanted_one == "aucun":
        return None
    if wanted_one == "kokoro":
        from greffier.adapters.voice_neural import NeuralVoice

        neural = NeuralVoice(
            config.paths.synthetic_voice,
            language=config.transcription.language or "fr",
            voice=config.assistant.effective_speaker,
            rate=config.assistant.rate,
            gag=config.paths.gag,
            device=config.hardware.device,
        )
        if neural.available:
            return neural
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

    her = AssistantSettings(
        name=config.assistant.name,
        manners=Manners(
            active=True,
            rest=config.assistant.rest,
            creux_minimal=config.assistant.creux_minimal,
        ),
        voice=assistant_voice(config),
        tracer=tracer,
        setting=lambda: context(config).header() + what_earlier_meetings_left(config),
    )
    the_brain = spoken_brain(config, her.guidance())
    her.keep_its_turn = _keep_her_turn(config, identifier)
    her.the_brain = the_brain
    return her

def spoken_brain(config: Config, own_guidance: str) -> Any | None:
    """What the assistant thinks with when it answers out loud.

    Not the writer of the minutes: that one starts a process per call, which
    costs five seconds before the first word, and a voice called by its name
    in a room cannot wait that long. With Claude Code the process is started
    once for the meeting and kept warm (see `brain_claude`); with Ollama the
    model is already resident and the writer is fast enough as it is.
    """
    engine = config.minutes.engine
    if engine == "ollama":
        the_brain: Any = OllamaWriter(config.minutes.effective_model,
                                    language=config.minutes.language,
                                    own_guidance=own_guidance)
        return the_brain
    if engine != "claude":
        return None
    from greffier.adapters.brain_claude import ClaudeSession

    on_search = None
    if config.conversation.recherche_web:
        # A short sound, the moment a search actually starts. Called by its
        # name the assistant takes a few seconds to answer, and nothing said
        # whether it was thinking or looking something up: waiting without
        # knowing what for is what makes a wait feel long.
        from greffier.adapters.cue_sound import cue

        on_search = cue()
    # The same tools as the conversation tab, and for the same reason: its
    # guidance tells it that it may look something up and name the source
    # aloud. Handed no tools, it answered "yes I can search" and "no I have
    # no access" in turn, four times in one meeting.
    # Built here, warmed up and closed by whoever runs the meeting: a factory
    # that starts a process is a factory no test can call.
    return ClaudeSession(
        model=config.assistant.model,
        language=config.minutes.language,
        tools=(ClaudeSession.SEARCH_TOOLS if config.conversation.recherche_web else ()),
        own_guidance=own_guidance,
        on_search=on_search,
    )


def _keep_her_turn(config: Config, identifier: str) -> Callable[[float, float], None]:
    from greffier.adapters import her_turns_file

    file = her_turns_file.file_for(config.paths.live, identifier)
    return lambda start, end: her_turns_file.keep(file, start, end)
