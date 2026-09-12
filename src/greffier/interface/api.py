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
from typing import TYPE_CHECKING, Any

# Imported here and not inside the builder: FastAPI resolves the annotations of
# a handler at runtime, and a name that only exists inside a function cannot be
# resolved -- `request: Request` was then read as a query parameter, and every
# guarded route answered 422 rather than 401. The module is only imported by the
# command that opens the door, which says what to install when it is missing.
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from greffier.adapters.configuration import Config

#: The phases a meeting handed over through the door goes through, kept in
#: memory: the state file belongs to the meeting being recorded, and two
#: processings answering into the same file would each erase the other.
_TRAVAUX: dict[str, dict[str, str]] = {}


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

    gardee = [Depends(authorised)]

    @api.get("/sante")
    def sante() -> dict[str, object]:
        """Open without a token: enough to know the door answers, and no more."""
        return {"outil": "greffier", "version": _version(), "pret": True}

    @api.get("/reunions", dependencies=gardee)
    def reunions() -> list[dict[str, object]]:
        store = _store(config)
        return [_resume(store, identifier) for identifier in store.lister()]

    @api.get("/reunions/{identifiant}", dependencies=gardee)
    def reunion(identifiant: str) -> dict[str, object]:
        store = _store(config)
        if identifiant not in store.lister():
            raise HTTPException(status_code=404, detail="réunion inconnue")
        return _resume(store, identifiant)

    @api.get("/reunions/{identifiant}/compte-rendu", dependencies=gardee,
             response_class=PlainTextResponse)
    def compte_rendu(identifiant: str) -> str:
        return _read(config.paths.minutes_folder / f"{identifiant}.md", "compte rendu")

    @api.get("/reunions/{identifiant}/transcription", dependencies=gardee,
             response_class=PlainTextResponse)
    def transcription(identifiant: str) -> str:
        return _read(config.paths.transcripts / f"{identifiant}.txt", "transcription")

    @api.get("/memoire", dependencies=gardee)
    def memoire() -> list[dict[str, object]]:
        """What earlier meetings left: decisions, open points, documents."""
        from dataclasses import asdict

        from greffier.wiring import memory

        return [asdict(trace) for trace in memory(config).recall()]

    @api.post("/reunions", dependencies=gardee, status_code=202)
    async def deposer(enregistrement: UploadFile) -> dict[str, str]:
        """Takes a recording in and answers at once: an hour is not a request.

        202 and an identifier. The phases are read back from /travaux, the same
        ones the window paints.
        """
        nom = Path(enregistrement.filename or "reunion.wav").name
        cible = config.paths.recordings / nom
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(await enregistrement.read())
        identifiant = cible.stem
        _TRAVAUX[identifiant] = {"phase": "attente", "message": "En file."}
        threading.Thread(
            target=_process, args=(config, cible, identifiant), daemon=True
        ).start()
        return {"identifiant": identifiant}

    @api.get("/travaux/{identifiant}", dependencies=gardee)
    def travail(identifiant: str) -> dict[str, str]:
        if identifiant not in _TRAVAUX:
            raise HTTPException(status_code=404, detail="aucun traitement pour ce nom")
        return _TRAVAUX[identifiant]

    return api


def _process(config: Config, audio: Path, identifiant: str) -> None:
    """Runs the chain and publishes its phases, without ever raising."""
    from greffier.wiring import wire_up

    def dire(phase: str, message: str = "") -> None:
        _TRAVAUX[identifiant] = {"phase": phase, "message": message}

    try:
        chaine = wire_up(config)
        chaine.log = type("Journal", (), {"publish": staticmethod(dire)})()
        chaine.run_chain(audio, send=False)
        dire("termine", "Compte rendu prêt.")
    except Exception as trouble:  # noqa: BLE001 - rendu au client, jamais avalé
        dire("echec", str(trouble))


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("greffier")
    except PackageNotFoundError:  # pragma: no cover - paquet non installé
        return "0"


def _store(config: Config) -> Any:
    from greffier.adapters.store_files import FileStore

    return FileStore(config.paths.data / "reunions")


def _resume(store: Any, identifiant: str) -> dict[str, object]:
    """A meeting as a list shows it: who, how long, how much was said."""
    reunion = store.read(identifiant)
    return {
        "identifiant": identifiant,
        "titre": reunion.subject or identifiant,
        "tenue_le": reunion.started_at.isoformat() if reunion.started_at else "",
        "duree_s": round(reunion.duration, 1),
        "personnes": sorted({nom for nom in reunion.names.values() if nom}),
        "mots": sum(len(u.text.split()) for u in reunion.utterances),
    }


def _read(file: Path, quoi: str) -> str:
    if not file.exists():
        raise HTTPException(status_code=404, detail=f"{quoi} introuvable")
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
