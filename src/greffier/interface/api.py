"""An HTTP door onto the use cases the window already drives.

A primary adapter, like the window and the command line: it holds no rule of
its own, it hands what arrives to the same chain and returns what comes back.
That is the whole point of the ports -- a second door costs a file, not an
architecture.

What it deliberately does **not** expose: the voice bank. Voice prints are
biometric data within the meaning of Article 9, and a door that serves them
turns a tool where nothing leaves the machine into a tool where everything can.
Minutes, transcripts and what earlier meetings left are the material a site
needs; the voices stay here.

Shut unless started, bound to the loopback unless told otherwise, and refusing
to bind anything else without a token. What comes in is bounded as well: a
recording is streamed to disk and refused past a configured size, its name has
to be one the file system and the chain can take, a name already taken is
refused rather than overwritten, and the chains run one at a time. The
documentation wants the token too: a map of the door is not for whoever knocks.
"""

from __future__ import annotations

import contextlib
import os
import queue
import re
import secrets
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, BinaryIO

# Imported here and not inside the builder: FastAPI resolves the annotations of
# a handler at runtime, and a name that only exists inside a function cannot be
# resolved -- `request: Request` was then read as a query parameter, and every
# guarded route answered 422 rather than 401. The module is only imported by the
# command that opens the door, which says what to install when it is missing.
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.datastructures import Headers
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from starlette.types import ASGIApp, Receive, Scope, Send

    from greffier.adapters.configuration import Config

#: How much of an upload is read at a time. A two-hour WAV is 1.4 GB: read in
#: one go, as `UploadFile.read()` does, it sits in memory in full before a
#: single byte reaches the disk.
_CHUNK = 1 << 20

#: The shape of a recording's name without its extension, which is also the
#: identifier every other route takes in its path. The client chooses it, and
#: it becomes a file name in three folders: a letter or digit first, then
#: letters, digits, dot, dash and underscore, 121 characters at most. Starlette
#: already keeps "/" out of a path segment; checking the identifier again is
#: defence in depth for the paths built from it. Matched with `fullmatch`: `$`
#: alone also matches before a trailing newline, the multipart parser accepts a
#: bare line feed inside a quoted file name, and "point\n.wav" reached the disk.
_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")

#: What the door takes in: the formats `adapters.audio_ffmpeg.REPLAYABLE` lets
#: stand in for the microphone. Kept here rather than imported, so that the
#: door's contract is read in the door's file and in the README, and a format
#: the recorder learns to replay reaches the door by decision, not by side
#: effect.
_ACCEPTED = frozenset({".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".mp4", ".mkv", ".webm"})

#: What the chain opens as it is. ffmpeg decodes all nine, but the voice
#: separation reads the recording itself through libsndfile
#: (`adapters/diarisation_sherpa.py`, `sf.read`), and libsndfile 1.2.2 answers
#: "Format not recognised" to the four containers: .m4a, .mp4, .mkv and .webm
#: would transcribe for an hour, then fail at the speakers. The worker extracts
#: their sound track to a .wav first, as the window does for a dropped video.
_READ_AS_IS = frozenset({".wav", ".flac", ".mp3", ".ogg", ".opus"})


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="jeton absent ou invalide")


def _holds_the_token(headers: Headers, expected: str) -> bool:
    """Compared in constant time, and false when no token is configured: an empty
    setting is a shut door, not an open one."""
    given = headers.get("authorization", "")
    return bool(expected) and secrets.compare_digest(given, f"Bearer {expected}")


def _invalid_name() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="nom d'enregistrement invalide : une lettre ou un chiffre d'abord, puis "
               "lettres, chiffres, « . », « - » et « _ », 121 caractères au plus",
    )


def _unsupported_format() -> HTTPException:
    accepted = ", ".join(sorted(_ACCEPTED))
    return HTTPException(
        status_code=422, detail=f"format non pris en charge ; acceptés : {accepted}"
    )


def _already_taken() -> HTTPException:
    return HTTPException(status_code=409, detail="un enregistrement porte déjà ce nom")


def _identifier(identifier: str) -> str:
    """The path parameter, checked before it becomes part of a file path."""
    if not _STEM.fullmatch(identifier):
        raise HTTPException(status_code=422, detail="identifiant invalide")
    return identifier


Identifier = Annotated[str, Depends(_identifier)]


def _too_large(limit_mb: int) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"enregistrement trop volumineux : la limite est de {limit_mb} Mio",
    )


class RefusedFromTheHeader:
    """A request declaring more than the limit is refused with nothing read.

    FastAPI parses a multipart body into a spooled temporary file before it
    resolves a route's dependencies, so nothing hung on the route runs first:
    measured, a dependency on the deposit found `request._form` already filled,
    and a 3 MiB body against a 1 MiB limit reached the handler whole,
    `recording.size == 3145728`, before its 413. This runs ahead of the router,
    on the Content-Length header alone. The header counts the multipart framing
    as well, a few hundred bytes the handler's count leaves out, so the cut is
    one chunk past the limit and the handler draws the exact line. Without the
    token the answer is 401, as on every route: the limit is not for whoever
    knocks. A client that declares no length is received in full and refused by
    the handler.
    """

    def __init__(self, app: ASGIApp, config: Config) -> None:
        self._app = app
        self._config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        refusal = self._refusal(Headers(scope=scope)) if scope["type"] == "http" else None
        if refusal is None:
            await self._app(scope, receive, send)
            return
        response = JSONResponse({"detail": refusal.detail}, status_code=refusal.status_code)
        await response(scope, receive, send)

    def _refusal(self, headers: Headers) -> HTTPException | None:
        """413 past the limit with the token, 401 without it, nothing otherwise."""
        declared = headers.get("content-length", "")
        limit_mb = self._config.api.max_upload_mb
        if not declared.isdigit() or int(declared) <= (limit_mb << 20) + _CHUNK:
            return None
        if not _holds_the_token(headers, self._config.api.token):
            return _unauthorized()
        return _too_large(limit_mb)


class Jobs:
    """The phases of the meetings handed over through the door, in memory.

    The state file belongs to the meeting being recorded, and two processings
    answering into the same file would each erase the other. Kept here, and
    bounded: a door left open for months must not grow an entry for every
    meeting it ever took. The last `kept` finished jobs stay readable, the
    oldest finished one goes first, and a job queued or running is never
    dropped, however old.
    """

    FINISHED = frozenset({"termine", "echec"})

    def __init__(self, kept: int = 200) -> None:
        self._kept = kept
        self._phases: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def publish(self, identifier: str, phase: str, message: str = "") -> None:
        """The job's latest phase. Re-inserted, so the dict stays ordered by last
        publication and a job that finishes takes its turn at the end."""
        with self._lock:
            self._phases.pop(identifier, None)
            self._phases[identifier] = {"phase": phase, "message": message}
            self._forget_the_oldest_finished()

    def get(self, identifier: str) -> dict[str, str] | None:
        with self._lock:
            found = self._phases.get(identifier)
            return dict(found) if found else None

    def _forget_the_oldest_finished(self) -> None:
        finished = [i for i, p in self._phases.items() if p["phase"] in self.FINISHED]
        excess = len(finished) - self._kept
        for identifier in finished[:excess] if excess > 0 else ():
            del self._phases[identifier]


class Worker:
    """One chain at a time.

    A chain loads the models and takes the graphics memory; two of them do not
    fit, and a thread per upload meant a burst of uploads could exhaust the
    machine. The jobs wait in a queue, in the phase "attente", and one daemon
    thread takes them in order, started the first time there is something to do.
    """

    def __init__(self, run: Callable[[Path, str], None]) -> None:
        self._run = run
        self._waiting: queue.Queue[tuple[Path, str] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._lock = threading.Lock()

    def enqueue(self, audio: Path, identifier: str) -> None:
        """Puts the job behind the others, and starts the thread if none runs.

        Refused once stopped: a job put behind the stop order would sit behind
        the sentinel, waiting for a thread that is not coming back, and nobody
        would be told.
        """
        with self._lock:
            if self._stopped:
                raise RuntimeError("Le travailleur est arrêté : plus rien n'est mis en file.")
            self._waiting.put((audio, identifier))
            if self._thread is None or not self._thread.is_alive():
                self._thread = self._started()

    def stop(self, timeout: float | None = None) -> None:
        """Lets the thread finish what is queued, then end; takes nothing after."""
        with self._lock:
            self._stopped = True
            thread = self._thread
            if thread is None or not thread.is_alive():
                return
            self._waiting.put(None)
        thread.join(timeout)

    def _started(self) -> threading.Thread:
        thread = threading.Thread(target=self._drain, daemon=True, name="greffier-api-worker")
        thread.start()
        return thread

    def _drain(self) -> None:
        while (job := self._waiting.get()) is not None:
            self._run(*job)


class _Journal:
    """What the chain publishes its phases into: one job's entry."""

    def __init__(self, jobs: Jobs, identifier: str) -> None:
        self._jobs = jobs
        self._identifier = identifier

    def publish(self, phase: str, message: str = "") -> None:
        self._jobs.publish(self._identifier, phase, message)


def build(config: Config) -> Any:
    """The application, wired to this configuration."""
    api = FastAPI(
        title="Greffier",
        summary="Enregistre une réunion, identifie qui parle, en rédige le compte rendu.",
        version=_version(),
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    api.add_middleware(RefusedFromTheHeader, config=config)
    jobs = Jobs()
    worker = Worker(lambda audio, identifier: _process(config, audio, identifier, jobs))
    #: The one worker the application owns, holding its single chain thread,
    #: reachable from outside the handlers for whoever closes the door.
    api.state.worker = worker

    def authorised(request: Request) -> None:
        if not _holds_the_token(request.headers, config.api.token):
            raise _unauthorized()

    kept_one = [Depends(authorised)]
    _describe_behind(api, kept_one)

    @api.get("/sante")
    def health() -> dict[str, object]:
        """Open without a token: enough to know the door answers, and no more."""
        return {"outil": "greffier", "version": _version(), "pret": True}

    @api.get("/reunions", dependencies=kept_one)
    def meetings_route() -> list[dict[str, object]]:
        store = _store(config)
        return [_resume(store, identifier) for identifier in store.list_()]

    @api.get("/reunions/{identifier}", dependencies=kept_one)
    def meeting_route(identifier: Identifier) -> dict[str, object]:
        store = _store(config)
        if identifier not in store.list_():
            raise HTTPException(status_code=404, detail="réunion inconnue")
        return _resume(store, identifier)

    @api.get("/reunions/{identifier}/compte-rendu", dependencies=kept_one,
             response_class=PlainTextResponse)
    def minutes_route(identifier: Identifier) -> str:
        return _read(config.paths.minutes_folder / f"{identifier}.md", "compte rendu")

    @api.get("/reunions/{identifier}/transcription", dependencies=kept_one,
             response_class=PlainTextResponse)
    def transcription(identifier: Identifier) -> str:
        return _read(config.paths.transcripts / f"{identifier}.txt", "transcription")

    @api.get("/memoire", dependencies=kept_one)
    def memory_() -> list[dict[str, object]]:
        """What earlier meetings left: decisions, open points, documents."""
        from dataclasses import asdict

        from greffier.wiring import memory

        return [asdict(trace) for trace in memory(config).recall()]

    @api.post("/reunions", dependencies=kept_one, status_code=202)
    async def deposit(
        recording: Annotated[UploadFile, File(alias="enregistrement")],
    ) -> dict[str, str]:
        """Takes a recording in and answers at once: an hour is not a request.

        202 and an identifier. The phases are read back from /travaux, the same
        ones the window paints.
        """
        identifier, name = _checked_name(recording.filename or "")
        target = config.paths.recordings / name
        _refuse_duplicates(config.paths.recordings, identifier)
        _claim(target)
        await _stream_to(recording, target, config.api.max_upload_mb)
        jobs.publish(identifier, "attente", "En file.")
        worker.enqueue(target, identifier)
        return {"identifiant": identifier}

    @api.get("/travaux/{identifier}", dependencies=kept_one)
    def travail(identifier: Identifier) -> dict[str, str]:
        found = jobs.get(identifier)
        if found is None:
            raise HTTPException(status_code=404, detail="aucun traitement pour ce nom")
        return found

    return api


def _describe_behind(api: FastAPI, guard: list[Any]) -> None:
    """The schema and its two viewers, served to the token holder only.

    FastAPI registers them open by default. The schema lists every route and
    every field a client may send: a map of the door, which is exactly what
    somebody probing the port wants first.
    """
    schema_url, title = "/openapi.json", "Greffier – documentation"

    @api.get(schema_url, dependencies=guard, include_in_schema=False)
    def openapi_route() -> dict[str, Any]:
        return api.openapi()

    @api.get("/docs", dependencies=guard, include_in_schema=False)
    def docs_route() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url=schema_url, title=title)

    @api.get("/redoc", dependencies=guard, include_in_schema=False)
    def redoc_route() -> HTMLResponse:
        return get_redoc_html(openapi_url=schema_url, title=title)


def _checked_name(filename: str) -> tuple[str, str]:
    """The identifier and the file name a deposit gets, or 422.

    Checked on the name as the client sent it, never on `Path(...).name`: taking
    the last component of "../x.wav" would quietly accept a name that was
    trying something.
    """
    stem, suffix = _split(filename)
    if not _STEM.fullmatch(stem):
        raise _invalid_name()
    if suffix not in _ACCEPTED:
        raise _unsupported_format()
    return stem, filename


def _split(filename: str) -> tuple[str, str]:
    """The stem and the lower-cased suffix, dot included, of a plain name."""
    if "." not in filename:
        return filename, ""
    stem, _, extension = filename.rpartition(".")
    return stem, f".{extension.lower()}"


def _refuse_duplicates(recordings: Path, identifier: str) -> None:
    """A name taken in any format is taken: the minutes and the transcript are
    keyed by the stem, and a second processing would overwrite the first's.

    The stem is compared whole, since a dot may sit inside it: "a.b.wav" does
    not take the name "a".
    """
    if any(found.stem == identifier for found in recordings.glob(f"{identifier}.*")):
        raise _already_taken()


def _claim(target: Path) -> None:
    """The name, taken before a byte of the body is read.

    The handler yields to the event loop while the body is copied, and two
    deposits of one name at once both passed the duplicate check: the second's
    move then erased the first's file. The empty file created here is what the
    next deposit's duplicate check finds, and its exclusive creation lets the
    file system arbitrate should two handlers ever run side by side.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666))
    except FileExistsError:
        raise _already_taken() from None


async def _stream_to(recording: UploadFile, target: Path, limit_mb: int) -> None:
    """Writes the upload beside its claimed name, then puts it in place in one move.

    Whoever reads the folder meets the empty claim or the whole recording,
    never a truncated one. The limit bounds what reaches this folder, not what
    the server receives: Starlette has parsed the whole multipart body into a
    spooled temporary file, 1 MiB in memory and the rest in the system's temp
    folder, before the handler runs (measured: a 3 MiB body against a 1 MiB
    limit arrived with recording.size == 3145728, then got its 413). Copying it
    in chunks keeps it out of this process's memory, and the count stops at the
    limit, so a refused upload leaves neither a temporary nor the claim behind.
    The temporary is opened like any file the tool writes, so a deposited
    recording gets the mode the umask gives; `tempfile` would have made it
    0600, unreadable by another tool a site points at the folder under another
    user.
    """
    temporary = target.with_name(f".depot-{secrets.token_hex(8)}.partiel")
    try:
        with temporary.open("xb") as stream:
            await _copy_bounded(recording, stream, limit_mb)
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise


async def _copy_bounded(recording: UploadFile, stream: BinaryIO, limit_mb: int) -> None:
    allowed, written = limit_mb << 20, 0
    while chunk := await recording.read(_CHUNK):
        written += len(chunk)
        if written > allowed:
            raise _too_large(limit_mb)
        stream.write(chunk)


def _process(config: Config, audio: Path, identifier: str, jobs: Jobs) -> None:
    """Runs the chain and publishes its phases, without ever raising."""
    from greffier.wiring import wire_up

    journal = _Journal(jobs, identifier)
    try:
        readable = _as_the_chain_reads_it(audio, journal.publish)
        chain = wire_up(config)
        chain.log = journal
        chain.run_chain(readable, send=False)
        jobs.publish(identifier, "termine", "Compte rendu prêt.")
    except Exception as trouble:  # noqa: BLE001 - handed to the client, never swallowed
        jobs.publish(identifier, "echec", str(trouble))


def _as_the_chain_reads_it(audio: Path, publish: Callable[[str, str], None]) -> Path:
    """The recording as deposited, or its sound track in a .wav beside it when
    the chain cannot open the container.

    Done in the worker and not in the handler: decoding a two-hour video takes
    a while, and the deposit answers at once. The deposit itself stays as it
    came, the way the window leaves a dropped video where it was.
    """
    if audio.suffix.lower() in _READ_AS_IS:
        return audio
    from greffier.application.publish import extract_sound

    publish("conversion", "Extraction de la piste sonore…")
    return extract_sound(audio, audio.with_suffix(".wav"))


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("greffier")
    except PackageNotFoundError:  # pragma: no cover - paquet non installé
        return "0"


def _store(config: Config) -> Any:
    from greffier.adapters.store_files import FileStore

    return FileStore(config.paths.data / "reunions")


def _resume(store: Any, identifier: str) -> dict[str, object]:
    """A meeting as a list shows it: who, how long, how much was said."""
    meeting = store.read(identifier)
    return {
        "identifiant": identifier,
        "titre": meeting.subject or identifier,
        "tenue_le": meeting.started_at.isoformat() if meeting.started_at else "",
        "duree_s": round(meeting.duration, 1),
        "personnes": sorted({name for name in meeting.names.values() if name}),
        "mots": sum(len(u.text.split()) for u in meeting.utterances),
    }


def _read(file: Path, what: str) -> str:
    if not file.exists():
        raise HTTPException(status_code=404, detail=f"{what} introuvable")
    return file.read_text(encoding="utf-8")


def ensure_a_token(config: Config) -> str:
    """The token, written into the settings the first time it is needed.

    A site is configured once. A token regenerated at every start would mean
    reconfiguring it at every start, and the usual answer to that is to turn
    authentication off.
    """
    if config.api.token:
        return config.api.token
    from greffier.adapters.configuration import save_settings

    config.api.token = secrets.token_urlsafe(32)
    with contextlib.suppress(OSError):
        save_settings(config)
    return config.api.token


def serve(config: Config) -> None:
    """Opens the door. Refuses to listen beyond the machine without a token."""
    import uvicorn

    ensure_a_token(config)
    uvicorn.run(build(config), host=config.api.host, port=config.api.port,
                log_level="warning")
