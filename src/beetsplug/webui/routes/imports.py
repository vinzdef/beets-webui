"""Endpoints for starting imports and answering their questions."""

import json
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import anyio
import confuse
from beets import config
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..imports import ImportBusyError, ImportManager

router = APIRouter()

# How long an event stream waits for a change before sending a keep-alive comment.
KEEPALIVE_SECONDS = 15


def require_same_origin(request: Request) -> None:
    """Reject cross-site requests: these endpoints read, copy and move files."""
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "cross-origin request refused")


def get_manager(request: Request) -> ImportManager:
    return request.app.state.imports


Manager = Annotated[ImportManager, Depends(get_manager)]


def configured_inboxes() -> dict[str, Path]:
    """The inboxes from `webui.inboxes`, a mapping of name to folder, in config order."""
    view = config["webui"]["inboxes"]
    try:
        names = list(view.get(dict))
    except confuse.NotFoundError:
        return {}
    except confuse.ConfigTypeError:
        raise HTTPException(
            500, "webui.inboxes must be a mapping of names to folders, e.g. Downloads: ~/Downloads"
        ) from None
    # as_filename expands ~ and resolves relative paths against the beets config directory,
    # like beets does for `directory` and `library`.
    return {str(name): Path(view[name].as_filename()).resolve() for name in names}


def resolve_in_inbox(path: str) -> Path:
    resolved = Path(path).resolve()
    folders = configured_inboxes().values()
    if not any(resolved == f or resolved.is_relative_to(f) for f in folders):
        raise HTTPException(400, f"not inside an inbox: {path}")
    if not resolved.exists():
        raise HTTPException(400, f"no such file or directory: {path}")
    return resolved


@router.get("/inboxes")
def list_inboxes():
    inboxes = []
    for name, folder in configured_inboxes().items():
        entries = []
        if folder.is_dir():
            for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                if entry.name.startswith("."):
                    continue
                entries.append({"name": entry.name, "path": str(entry), "is_dir": entry.is_dir()})
        inboxes.append(
            {"name": name, "path": str(folder), "exists": folder.is_dir(), "entries": entries}
        )
    return {"inboxes": inboxes}


class StartImport(BaseModel):
    paths: list[str] = []
    # Re-import (and so re-match) an album already in the library instead of inbox paths.
    album_id: int | None = None
    # Unset options keep whatever the beets config says.
    # auto: apply strong matches unasked; manual: only perfect ones; timid: ask about all.
    mode: Literal["auto", "manual", "timid"] | None = None
    singletons: bool | None = None
    group_albums: bool | None = None


@router.post("/imports", dependencies=[Depends(require_same_origin)], status_code=201)
def start_import(body: StartImport, manager: Manager):
    query = None
    if body.album_id is not None:
        album = manager.lib.get_album(body.album_id)
        if album is None:
            raise HTTPException(404, "album not found")
        paths = [f"{album.albumartist} – {album.album}"]
        query = f"id:{album.id}"
    elif body.paths:
        paths = [str(resolve_in_inbox(p)) for p in body.paths]
    else:
        raise HTTPException(400, "no paths given")
    options = body.model_dump(exclude={"paths", "album_id"}, exclude_none=True)
    try:
        job = manager.start(paths, options, query)
    except ImportBusyError:
        raise HTTPException(409, "an import is already running") from None
    return job.snapshot()


@router.get("/imports/current")
def current_import(manager: Manager):
    return manager.job.snapshot() if manager.job else None


@router.get("/imports/current/events")
async def import_events(request: Request, manager: Manager):
    """Server-sent events: the current job's full state, each time it changes."""

    async def stream():
        version = -1
        while not await request.is_disconnected():
            new_version = await anyio.to_thread.run_sync(
                manager.wait_for_change, version, KEEPALIVE_SECONDS
            )
            if new_version == version:
                yield ": keep-alive\n\n"
                continue
            version = new_version
            snapshot = manager.job.snapshot() if manager.job else None
            yield f"data: {json.dumps(snapshot)}\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


class Answer(BaseModel):
    question: int
    type: Literal["apply", "choice", "search", "id", "duplicate", "resume"]
    candidate: int | None = None
    short: str | None = None
    artist: str = ""
    name: str = ""
    ids: str = ""
    action: str | None = None
    resume: bool | None = None


@router.post("/imports/current/answer", dependencies=[Depends(require_same_origin)])
def answer_question(body: Answer, manager: Manager):
    job = manager.job
    question = job.question if job else None
    if question is None or question["id"] != body.question:
        raise HTTPException(409, "that question is no longer open")

    answer = validate_answer(question, body)
    try:
        job.answer(body.question, answer)
    except LookupError:
        raise HTTPException(409, "that question is no longer open") from None
    return {"ok": True}


@router.post("/imports/current/abort", dependencies=[Depends(require_same_origin)])
def abort_import(manager: Manager):
    if manager.job is None or not manager.job.active:
        raise HTTPException(409, "no import is running")
    manager.job.abort()
    return {"ok": True}


def validate_answer(question: dict[str, Any], body: Answer) -> dict[str, Any]:
    """Check an answer against the open question before it reaches the import thread."""
    kind = question["kind"]
    if kind == "match":
        if body.type == "apply":
            if body.candidate is None or not 0 <= body.candidate < len(question["candidates"]):
                raise HTTPException(400, "invalid candidate")
            return {"type": "apply", "candidate": body.candidate}
        if body.type == "choice":
            if body.short not in {c["short"] for c in question["choices"]}:
                raise HTTPException(400, "invalid choice")
            return {"type": "choice", "short": body.short}
        if body.type == "search":
            if not (body.artist.strip() or body.name.strip()):
                raise HTTPException(400, "enter an artist or a name to search for")
            return {"type": "search", "artist": body.artist, "name": body.name}
        if body.type == "id":
            if not body.ids.strip():
                raise HTTPException(400, "enter an ID")
            return {"type": "id", "ids": body.ids}
    elif kind == "duplicate" and body.type == "duplicate":
        if body.action not in {o["value"] for o in question["options"]}:
            raise HTTPException(400, "invalid duplicate action")
        return {"action": body.action}
    elif kind == "resume" and body.type == "resume" and body.resume is not None:
        return {"resume": body.resume}
    raise HTTPException(400, f"invalid answer for a {kind} question")
