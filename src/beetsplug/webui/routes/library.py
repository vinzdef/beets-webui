"""Endpoints for browsing and searching the library, and for syncing it with the files."""

import os
import threading
from itertools import islice
from pathlib import Path
from typing import Any, Literal

import mediafile
from beets import ui, util
from beets.dbcore import Model
from beets.library import Library
from beets.ui.commands.update import update_items
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .imports import require_same_origin

router = APIRouter()

_update_lock = threading.Lock()

# Images music players pick up from an album's folder, in order of preference.
FOLDER_ART = ("cover", "folder", "front", "album")
ART_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# Sort tokens appended to the query for each way of grouping albums.
ALBUM_ORDER = {"artist": "albumartist+ year+ album+", "album": "album+ albumartist+"}

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
    order: Literal["default", "artist", "album"] = "default",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    albums = get_lib(request).albums(f"{q} {ALBUM_ORDER.get(order, '')}".strip())
    return paginate(albums, offset, limit)


@router.get("/albums/{album_id}")
def get_album(request: Request, album_id: int):
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    data = serialize(album)
    data["items"] = [serialize(i) for i in album.items()]
    return data


# Fields the album page can edit. Album fields are copied to the album's tracks, as in beets.
ALBUM_EDIT_FIELDS = {"album", "albumartist", "year", "genres", "label", "catalognum", "country"}
ITEM_EDIT_FIELDS = {"title", "artist", "track", "disc"}


class AlbumEdit(BaseModel):
    # Values are strings, parsed by each field's beets type as `beet modify` does.
    album: dict[str, str] = {}
    items: dict[int, dict[str, str]] = {}


@router.patch("/albums/{album_id}", dependencies=[Depends(require_same_origin)])
def edit_album(request: Request, album_id: int, body: AlbumEdit):
    """Like `beet modify`: store the changes, write them to the files and move files to match."""
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    if unknown := set(body.album) - ALBUM_EDIT_FIELDS:
        raise HTTPException(400, f"can't edit album fields: {', '.join(sorted(unknown))}")
    items = {item.id: item for item in album.items()}
    for item_id, fields in body.items.items():
        if item_id not in items:
            raise HTTPException(400, f"track {item_id} isn't on this album")
        if unknown := set(fields) - ITEM_EDIT_FIELDS:
            raise HTTPException(400, f"can't edit track fields: {', '.join(sorted(unknown))}")

    write, move = ui.should_write(), ui.should_move()
    for key, value in body.album.items():
        album.set_parse(key, value)
    album.store(inherit=True)
    for item in album.items():
        # Album fields reach every track; otherwise only the edited tracks need writing.
        if not body.album and item.id not in body.items:
            continue
        for key, value in body.items.get(item.id, {}).items():
            item.set_parse(key, value)
        item.try_sync(write, move)
    return get_album(request, album_id)


@router.get("/albums/{album_id}/art")
def get_album_art(request: Request, album_id: int):
    """The album's art: what beets stored, else a cover image in its folder, else embedded art."""
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    if album.artpath and os.path.isfile(util.syspath(album.artpath)):
        return FileResponse(util.syspath(album.artpath))
    item = album.items().get()
    if item is None:
        raise HTTPException(404, "no art")
    folder = Path(util.syspath(os.path.dirname(item.path)))
    if folder.is_dir():
        images = {p.name.lower(): p for p in folder.iterdir() if p.suffix.lower() in ART_EXTENSIONS}
        for name in FOLDER_ART:
            for ext in ART_EXTENSIONS:
                if name + ext in images:
                    return FileResponse(images[name + ext])
    try:
        data = mediafile.MediaFile(util.syspath(item.path)).art
    except (OSError, mediafile.UnreadableFileError):
        data = None
    if not data:
        raise HTTPException(404, "no art")
    return Response(data, media_type=mediafile.image_mime_type(data) or "image/jpeg")


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


def check_can_update(request: Request) -> Library:
    lib = get_lib(request)
    job = request.app.state.imports.job
    if job is not None and job.active:
        raise HTTPException(409, "Wait for the import to finish before updating the library.")
    # `beet update` asks before going on without the library folder (an unmounted drive would
    # drop every entry); with nobody to ask, refuse.
    if not os.path.isdir(util.syspath(lib.directory)):
        folder = util.displayable_path(lib.directory)
        raise HTTPException(409, f"The library folder {folder} is missing, so nothing was updated.")
    return lib


@router.get("/library/update")
def preview_library_update(request: Request):
    """What an update would do: remove the entries whose files are gone, and maybe move files."""
    lib = check_can_update(request)
    missing = [
        {
            "id": i.id,
            "artist": i.artist,
            "album": i.album,
            "title": i.title,
            "path": util.displayable_path(i.path),
        }
        for i in lib.items()
        if not i.path or not os.path.exists(util.syspath(i.path))
    ]
    return {"missing": missing, "moves_files": ui.should_move()}


@router.post("/library/update", dependencies=[Depends(require_same_origin)])
def update_library(request: Request):
    """Like `beet update`: drop entries whose files are gone and re-read tags that changed."""
    lib = check_can_update(request)
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
