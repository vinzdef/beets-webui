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


def album_folders(lib: Library) -> dict[int, str]:
    """Each album's folder, relative to the library folder when it's inside it."""
    root = util.displayable_path(lib.directory)
    with lib.transaction() as tx:
        rows = tx.query(
            "SELECT album_id, MIN(path) FROM items WHERE album_id IS NOT NULL GROUP BY album_id"
        )
    folders = {}
    for album_id, path in rows:
        folder = os.path.dirname(util.displayable_path(path))
        if folder.startswith(root.rstrip(os.sep) + os.sep):
            folder = os.path.relpath(folder, root)
        folders[album_id] = folder
    return folders


@router.get("/albums")
def list_albums(
    request: Request,
    q: str = Query("", description="beets query string, e.g. 'artist:radiohead year:1997'"),
    order: Literal["default", "artist", "album", "path"] = "default",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    lib = get_lib(request)
    albums = lib.albums(f"{q} {ALBUM_ORDER.get(order, '')}".strip())
    folders = album_folders(lib)
    if order == "path":
        # By parent folder first, so the albums under one folder heading stay together.
        def folder_key(album):
            folder = folders.get(album.id, "").lower()
            return os.path.dirname(folder), folder

        albums = sorted(albums, key=folder_key)
    page = paginate(albums, offset, limit)
    for album in page["results"]:
        album["folder"] = folders.get(album["id"])
    return page


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
