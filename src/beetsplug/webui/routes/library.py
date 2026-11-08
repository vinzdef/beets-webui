"""Read-only endpoints for browsing and searching the library."""

from itertools import islice
from typing import Any

from beets import util
from beets.dbcore import Model
from beets.library import Library
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

router = APIRouter()

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
