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
recording is streamed to disk and refused past a configured size.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, BinaryIO

# Imported here and not inside the builder: FastAPI resolves the annotations of
# a handler at runtime, and a name that only exists inside a function cannot be
# resolved -- `request: Request` was then read as a query parameter, and every
# guarded route answered 422 rather than 401. The module is only imported by the
# command that opens the door, which says what to install when it is missing.
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.datastructures import Headers
from fastapi.responses import JSONResponse, PlainTextResponse

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from starlette.types import ASGIApp, Receive, Scope, Send

    from greffier.adapters.configuration import Config

#: The phases a meeting handed over through the door goes through, kept in
#: memory: the state file belongs to the meeting being recorded, and two
#: processings answering into the same file would each erase the other.
_JOBS: dict[str, dict[str, str]] = {}

#: How much of an upload is read at a time. A two-hour WAV is 1.4 GB: read in
#: one go, as `UploadFile.read()` does, it sits in memory in full before a
#: single byte reaches the disk.
_CHUNK = 1 << 20


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="jeton absent ou invalide")


def _holds_the_token(headers: Headers, expected: str) -> bool:
    """Compared in constant time, and false when no token is configured: an empty
    setting is a shut door, not an open one."""
    given = headers.get("authorization", "")
    return bool(expected) and secrets.compare_digest(given, f"Bearer {expected}")


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


def build(config: Config) -> Any:
    """The application, wired to this configuration."""
    api = FastAPI(
        title="Greffier",
        summary="Enregistre une réunion, identifie qui parle, en rédige le compte rendu.",
        version=_version(),
    )
    api.add_middleware(RefusedFromTheHeader, config=config)

    def authorised(request: Request) -> None:
        if not _holds_the_token(request.headers, config.api.token):
            raise _unauthorized()

    kept_one = [Depends(authorised)]

    @api.get("/sante")
    def health() -> dict[str, object]:
        """Open without a token: enough to know the door answers, and no more."""
        return {"outil": "greffier", "version": _version(), "pret": True}

    @api.get("/reunions", dependencies=kept_one)
    def meetings_route() -> list[dict[str, object]]:
        store = _store(config)
        return [_resume(store, identifier) for identifier in store.list_()]

    @api.get("/reunions/{identifier}", dependencies=kept_one)
    def meeting_route(identifier: str) -> dict[str, object]:
        store = _store(config)
        if identifier not in store.list_():
            raise HTTPException(status_code=404, detail="réunion inconnue")
        return _resume(store, identifier)

    @api.get("/reunions/{identifier}/compte-rendu", dependencies=kept_one,
             response_class=PlainTextResponse)
    def minutes_route(identifier: str) -> str:
        return _read(config.paths.minutes_folder / f"{identifier}.md", "compte rendu")

    @api.get("/reunions/{identifier}/transcription", dependencies=kept_one,
             response_class=PlainTextResponse)
    def transcription(identifier: str) -> str:
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
        name = Path(recording.filename or "reunion.wav").name
        target = config.paths.recordings / name
        await _stream_to(recording, target, config.api.max_upload_mb)
        identifier = target.stem
        _JOBS[identifier] = {"phase": "attente", "message": "En file."}
        threading.Thread(
            target=_process, args=(config, target, identifier), daemon=True
        ).start()
        return {"identifiant": identifier}

    @api.get("/travaux/{identifier}", dependencies=kept_one)
    def travail(identifier: str) -> dict[str, str]:
        if identifier not in _JOBS:
            raise HTTPException(status_code=404, detail="aucun traitement pour ce nom")
        return _JOBS[identifier]

    return api


async def _stream_to(recording: UploadFile, target: Path, limit_mb: int) -> None:
    """Writes the upload beside its target, then puts it in place in one move.

    A half-written file under its final name would be picked up by whoever
    lists the folder. The limit bounds what reaches this folder, not what the
    server receives: Starlette has parsed the whole multipart body into a
    spooled temporary file, 1 MiB in memory and the rest in the system's temp
    folder, before the handler runs (measured: a 3 MiB body against a 1 MiB
    limit arrived with recording.size == 3145728, then got its 413). Copying it
    in chunks keeps it out of this process's memory, and the count stops at the
    limit, so a refused upload leaves no temporary behind to fill the disk one
    failed upload at a time. The temporary is opened like any file the tool
    writes, so a deposited recording gets the mode the umask gives; `tempfile`
    would have made it 0600, unreadable by another tool a site points at the
    folder under another user.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".depot-{secrets.token_hex(8)}.partiel")
    try:
        with temporary.open("xb") as stream:
            await _copy_bounded(recording, stream, limit_mb)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


async def _copy_bounded(recording: UploadFile, stream: BinaryIO, limit_mb: int) -> None:
    allowed, written = limit_mb << 20, 0
    while chunk := await recording.read(_CHUNK):
        written += len(chunk)
        if written > allowed:
            raise _too_large(limit_mb)
        stream.write(chunk)


def _process(config: Config, audio: Path, identifier: str) -> None:
    """Runs the chain and publishes its phases, without ever raising."""
    from greffier.wiring import wire_up

    def say(phase: str, message: str = "") -> None:
        _JOBS[identifier] = {"phase": phase, "message": message}

    try:
        chain = wire_up(config)
        chain.log = type("Journal", (), {"publish": staticmethod(say)})()
        chain.run_chain(audio, send=False)
        say("termine", "Compte rendu prêt.")
    except Exception as trouble:  # noqa: BLE001 - handed to the client, never swallowed
        say("echec", str(trouble))


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
