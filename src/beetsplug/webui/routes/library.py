"""Endpoints for browsing and searching the library, and for syncing it with the files."""

import os
import threading
from itertools import islice
from typing import Any

from beets import ui, util
from beets.dbcore import Model
from beets.library import Library
from beets.ui.commands.update import update_items
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from .imports import require_same_origin

router = APIRouter()

_update_lock = threading.Lock()

PATH_FIELDS = {"path", "artpath"}


def get_lib(request: Request) -> Library:
    return request.app.state.lib


def serialize(obj: Model) -> dict[str, Any]:
    out = {}
    # Not obj.items(): on Album that returns the album's tracks, not its fields.
    for key in obj.keys():
        value = obj.get(key)
        if key in PATH_FIELDS:
            value = util.displayable_path(value) if value else None
        elif isinstance(value, bytes):
            continue  # opaque blobs such as embedded art
        out[key] = value
    return out


def paginate(results, offset: int, limit: int) -> dict[str, Any]:
    rows = [serialize(r) for r in islice(results, offset, offset + limit)]
    return {"total": len(results), "offset": offset, "limit": limit, "results": rows}


@router.get("/albums")
def list_albums(
    request: Request,
    q: str = Query("", description="beets query string, e.g. 'artist:radiohead year:1997'"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    return paginate(get_lib(request).albums(q), offset, limit)


@router.get("/albums/{album_id}")
def get_album(request: Request, album_id: int):
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    data = serialize(album)
    data["items"] = [serialize(i) for i in album.items()]
    return data


@router.get("/albums/{album_id}/art")
def get_album_art(request: Request, album_id: int):
    album = get_lib(request).get_album(album_id)
    if album is None or not album.artpath:
        raise HTTPException(404, "no art")
    return FileResponse(util.syspath(album.artpath))


@router.get("/items")
def list_items(
    request: Request,
    q: str = Query("", description="beets query string"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    return paginate(get_lib(request).items(q), offset, limit)


@router.get("/items/{item_id}")
def get_item(request: Request, item_id: int):
    item = get_lib(request).get_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return serialize(item)


@router.post("/library/update", dependencies=[Depends(require_same_origin)])
def update_library(request: Request):
    """Like `beet update`: drop entries whose files are gone and re-read tags that changed."""
    lib = get_lib(request)
    job = request.app.state.imports.job
    if job is not None and job.active:
        raise HTTPException(409, "Wait for the import to finish before updating the library.")
    # `beet update` asks before going on without the library folder (an unmounted drive would
    # drop every entry); with nobody to ask, refuse.
    if not os.path.isdir(util.syspath(lib.directory)):
        folder = util.displayable_path(lib.directory)
        raise HTTPException(409, f"The library folder {folder} is missing, so nothing was updated.")
    if not _update_lock.acquire(blocking=False):
        raise HTTPException(409, "The library is already being updated.")
    try:
        items = list(lib.items())
        albums = len(lib.albums())
        if items:
            update_items(lib, items, ui.should_move(), pretend=False, fields=None)
        return {
            "removed_items": len(items) - len(lib.items()),
            "removed_albums": albums - len(lib.albums()),
        }
    finally:
        _update_lock.release()
