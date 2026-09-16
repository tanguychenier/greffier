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
to bind anything else without a token.
"""

from __future__ import annotations

import contextlib
import secrets
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

# Imported here and not inside the builder: FastAPI resolves the annotations of
# a handler at runtime, and a name that only exists inside a function cannot be
# resolved -- `request: Request` was then read as a query parameter, and every
# guarded route answered 422 rather than 401. The module is only imported by the
# command that opens the door, which says what to install when it is missing.
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from greffier.adapters.configuration import Config

#: The phases a meeting handed over through the door goes through, kept in
#: memory: the state file belongs to the meeting being recorded, and two
#: processings answering into the same file would each erase the other.
_JOBS: dict[str, dict[str, str]] = {}


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="jeton absent ou invalide")


def build(config: Config) -> Any:
    """The application, wired to this configuration."""
    api = FastAPI(
        title="Greffier",
        summary="Enregistre une réunion, identifie qui parle, en rédige le compte rendu.",
        version=_version(),
    )

    def authorised(request: Request) -> None:
        expected = config.api.token
        if not expected:
            raise _unauthorized()
        given = request.headers.get("authorization", "")
        if not secrets.compare_digest(given, f"Bearer {expected}"):
            raise _unauthorized()

    kept_one = [Depends(authorised)]

    @api.get("/sante")
    def sante() -> dict[str, object]:
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
    def memoire() -> list[dict[str, object]]:
        """What earlier meetings left: decisions, open points, documents."""
        from dataclasses import asdict

        from greffier.wiring import memory

        return [asdict(trace) for trace in memory(config).recall()]

    @api.post("/reunions", dependencies=kept_one, status_code=202)
    async def deposer(
        recording: Annotated[UploadFile, File(alias="enregistrement")],
    ) -> dict[str, str]:
        """Takes a recording in and answers at once: an hour is not a request.

        202 and an identifier. The phases are read back from /travaux, the same
        ones the window paints.
        """
        name = Path(recording.filename or "reunion.wav").name
        target = config.paths.recordings / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(await recording.read())
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
