"""Endpoints for browsing, searching and editing the library."""

import mimetypes
import os
from typing import Literal

from beets import ui, util
from beets.dbcore.query import StringQuery
from beets.library import Album, Item
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .art import find_art
from .common import find_plugin, get_lib, paginate, serialize
from .imports import require_same_origin
from .maintenance import HEALTH_CHECKS, cached_scan, problems_of

router = APIRouter()

# Sort tokens appended to the query for each way of grouping albums.
ALBUM_ORDER = {"artist": "albumartist+ year+ album+", "album": "album+ albumartist+"}
# Sorting songs by a column: that field first (either way), then these to break ties.
SONG_ORDER = {
    "track": ["track", "album", "title"],
    "title": ["title", "artist"],
    "artist": ["artist", "album", "disc", "track"],
    "album": ["album", "disc", "track"],
    "bitrate": ["bitrate", "artist", "album"],
}
# Content types for the player, by extension; others are guessed. Browsers play most of these
# (FLAC, MP3, AAC, Ogg, Opus, WAV); ALAC, WMA, APE and the like depend on the browser.
AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".wma": "audio/x-ms-wma",
}
# Filters for the songs view: tracks on no album ("singletons"), or only those on one.
SONG_FILTERS = {"singletons": "singleton:true", "on_album": "singleton:false"}

# Fields the UI can edit; values arrive as strings, parsed by each field's beets type as
# `beet modify` does. Album fields are copied to the album's tracks, as in beets.
ALBUM_EDIT_FIELDS = {"album", "albumartist", "year", "genres", "label", "catalognum", "country"}
ITEM_EDIT_FIELDS = {"title", "artist", "track", "disc"}
# A single track has no album to hold these, so it carries them itself.
SINGLETON_EDIT_FIELDS = ITEM_EDIT_FIELDS | {"album", "albumartist", "year", "genres"}
# Bulk edits on tracks; album fields reach the album once all of its tracks agree.
BULK_ITEM_FIELDS = {"artist", "albumartist", "album", "year", "genres"}


@router.get("/albums")
def list_albums(
    request: Request,
    q: str = Query("", description="beets query string, e.g. 'artist:radiohead year:1997'"),
    order: Literal["default", "artist", "album"] = "default",
    problem: str | None = Query(
        None, description="only albums failing this health check, or 'any' for any of them"
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    lib = get_lib(request)
    albums = lib.albums(f"{q} {ALBUM_ORDER.get(order, '')}".strip())
    if problem:
        if problem != "any" and problem not in HEALTH_CHECKS:
            raise HTTPException(400, f"no such health check: {problem}")
        _, problems = cached_scan(lib)
        albums = [
            a
            for a in albums
            if a.id in problems and (problem == "any" or problem in problems[a.id])
        ]
    return paginate(albums, offset, limit)


@router.get("/artists")
def list_by_artist(
    request: Request,
    q: str = Query("", description="beets query string"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """The artist view: albums and the tracks on no album, by artist (album artist for albums),
    each artist's albums before their loose tracks. Rows say which they are in `kind`."""
    lib = get_lib(request)
    albums = [("album", a.albumartist, a) for a in lib.albums(f"{q} {ALBUM_ORDER['artist']}")]
    tracks = [("track", i.artist, i) for i in lib.items(f"{q} singleton:true artist+ title+")]
    # A stable sort keeps beets' order (by year and album, or by title) within each artist.
    rows = sorted(albums + tracks, key=lambda r: (r[1].lower(), r[0] == "track"))
    return {
        "total": len(rows),
        "albums": len(albums),
        "tracks": len(tracks),
        "offset": offset,
        "limit": limit,
        "results": [
            serialize(obj) | {"kind": kind} for kind, _, obj in rows[offset : offset + limit]
        ],
    }


@router.get("/artist")
def get_artist(request: Request, name: str = Query(..., min_length=1)):
    """An artist's page: their albums, the albums of others they have tracks on (compilations,
    say) and their tracks on no album. Names match whole, ignoring case."""
    lib = get_lib(request)
    albums = sorted(
        lib.albums(StringQuery("albumartist", name)), key=lambda a: (a.year or 0, a.album.lower())
    )
    own = {a.id for a in albums}
    tracks = list(lib.items(StringQuery("artist", name)))
    others = {i.album_id for i in tracks if i.album_id is not None and i.album_id not in own}
    appears_on = sorted(
        filter(None, (lib.get_album(album_id) for album_id in others)),
        key=lambda a: (a.year or 0, a.album.lower()),
    )
    loose = sorted((i for i in tracks if i.album_id is None), key=lambda i: i.title.lower())
    if not (albums or appears_on or loose):
        raise HTTPException(404, "no albums or tracks by that artist")
    return {
        # As the library spells it, rather than as typed.
        "name": albums[0].albumartist if albums else tracks[0].artist,
        "albums": [serialize(a) for a in albums],
        "appears_on": [serialize(a) for a in appears_on],
        "tracks": [serialize(i) for i in loose],
    }


@router.get("/albums/{album_id}")
def get_album(request: Request, album_id: int):
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    data = serialize(album)
    # In album order: beets' default item sort starts with the artist, which puts a track by
    # "Artist feat. Guest" after all of the artist's own.
    tracks = sorted(album.items(), key=lambda i: (i.disc or 0, i.track or 0, i.title))
    data["items"] = [serialize(i) for i in tracks]
    found = find_art(album)
    data["art_source"] = found[0] if found else None
    data["can_refresh"] = bool(album.mb_albumid) and find_plugin("mbsync") is not None
    data["problems"] = problems_of(get_lib(request), album)
    return data


@router.delete("/albums/{album_id}", dependencies=[Depends(require_same_origin)])
def delete_album(
    request: Request,
    album_id: int,
    delete_files: bool = Query(True, description="also delete its files and cover from disk"),
):
    """Like `beet remove -a` (with -d to delete the files): remove an album and its tracks.
    Deleting also removes the folders it leaves empty."""
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    tracks = len(album.items())
    album.remove(delete=delete_files, with_items=True)
    return {"removed_items": tracks, "deleted_files": delete_files}


@router.get("/items")
def list_items(
    request: Request,
    q: str = Query("", description="beets query string"),
    sort: Literal["track", "title", "artist", "album", "bitrate"] | None = Query(
        None, description="sort by this column instead of beets' default order"
    ),
    desc: bool = Query(False, description="sort that column descending"),
    only: Literal["singletons", "on_album"] | None = Query(
        None, description="only tracks on no album, or only those on one"
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    parts = [q, SONG_FILTERS[only] if only else ""]
    if sort:
        first, *rest = SONG_ORDER[sort]
        parts += [f"{first}{'-' if desc else '+'}", *(f"{f}+" for f in rest)]
    return paginate(get_lib(request).items(" ".join(p for p in parts if p)), offset, limit)


@router.get("/items/{item_id}")
def get_item(request: Request, item_id: int):
    item = get_lib(request).get_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    data = serialize(item)
    # Album tracks are refreshed with their album.
    data["can_refresh"] = (
        item.album_id is None and bool(item.mb_trackid) and find_plugin("mbsync") is not None
    )
    return data


@router.get("/items/{item_id}/file")
def get_item_file(request: Request, item_id: int):
    """The track's audio file, for the player. Range requests let it seek."""
    item = get_lib(request).get_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    path = util.syspath(item.path)
    if not os.path.isfile(path):
        raise HTTPException(404, "The file is missing.")
    ext = os.path.splitext(path)[1].lower()
    media_type = AUDIO_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


def refresh(request: Request, kind: Literal["albums", "singletons"], obj_id: int) -> None:
    """Like `beet mbsync`: fetch the matched release or recording again and apply it.

    Only the one method: album and item ids overlap, so `id:5` means a different thing to each.
    """
    mbsync = find_plugin("mbsync")
    if mbsync is None:
        raise HTTPException(400, "Add mbsync to the plugins in your beets config to refresh.")
    sync = mbsync.albums if kind == "albums" else mbsync.singletons
    sync(get_lib(request), [f"id:{obj_id}"], ui.should_move(), False, ui.should_write())


@router.post("/albums/{album_id}/refresh", dependencies=[Depends(require_same_origin)])
def refresh_album(request: Request, album_id: int):
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    if not album.mb_albumid:
        raise HTTPException(
            400, "This album isn't matched to a release, so there's nothing to refresh."
        )
    refresh(request, "albums", album_id)
    return get_album(request, album_id)


@router.post("/items/{item_id}/refresh", dependencies=[Depends(require_same_origin)])
def refresh_item(request: Request, item_id: int):
    item = get_lib(request).get_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if item.album_id is not None:
        raise HTTPException(400, "This track is on an album: refresh the album instead.")
    if not item.mb_trackid:
        raise HTTPException(
            400, "This track isn't matched to a recording, so there's nothing to refresh."
        )
    refresh(request, "singletons", item_id)
    return get_item(request, item_id)


def check_fields(fields: dict[str, str], allowed: set[str], what: str) -> None:
    if unknown := set(fields) - allowed:
        raise HTTPException(400, f"can't edit {what} fields: {', '.join(sorted(unknown))}")


def save_album(album: Album, fields: dict[str, str]) -> None:
    """Like `beet modify -a`: store, copy to the tracks, write their tags and move files."""
    for key, value in fields.items():
        album.set_parse(key, value)
    album.try_sync(ui.should_write(), ui.should_move(), inherit=True)


def save_item(item: Item, fields: dict[str, str]) -> None:
    """Like `beet modify`: store, write the tags and move the file to match."""
    for key, value in fields.items():
        item.set_parse(key, value)
    item.try_sync(ui.should_write(), ui.should_move())


class AlbumEdit(BaseModel):
    album: dict[str, str] = {}
    items: dict[int, dict[str, str]] = {}


@router.patch("/albums/{album_id}", dependencies=[Depends(require_same_origin)])
def edit_album(request: Request, album_id: int, body: AlbumEdit):
    """Edit an album's fields and its tracks' fields in one go."""
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    check_fields(body.album, ALBUM_EDIT_FIELDS, "album")
    items = {item.id: item for item in album.items()}
    for item_id, fields in body.items.items():
        if item_id not in items:
            raise HTTPException(400, f"track {item_id} isn't on this album")
        check_fields(fields, ITEM_EDIT_FIELDS, "track")

    if body.album:
        save_album(album, body.album)
    # Reloaded, so tracks carry the album fields just copied to them.
    for item in album.items():
        if item.id in body.items:
            save_item(item, body.items[item.id])
    return get_album(request, album_id)


@router.patch("/items/{item_id}", dependencies=[Depends(require_same_origin)])
def edit_item(request: Request, item_id: int, fields: dict[str, str]):
    """Edit one track. An album's track takes album fields from its album, so it can't set them."""
    item = get_lib(request).get_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    check_fields(
        fields, SINGLETON_EDIT_FIELDS if item.album_id is None else ITEM_EDIT_FIELDS, "track"
    )
    save_item(item, fields)
    return serialize(item)


class BulkEdit(BaseModel):
    ids: list[int] = Field(min_length=1)
    fields: dict[str, str] = Field(min_length=1)


@router.patch("/albums", dependencies=[Depends(require_same_origin)])
def edit_albums(request: Request, body: BulkEdit):
    """Set the same fields on several albums (and so on all of their tracks)."""
    check_fields(body.fields, ALBUM_EDIT_FIELDS, "album")
    lib = get_lib(request)
    albums = [lib.get_album(album_id) for album_id in body.ids]
    if None in albums:
        raise HTTPException(404, "album not found")
    for album in albums:
        save_album(album, body.fields)
    return {"updated": len(albums)}


@router.patch("/items", dependencies=[Depends(require_same_origin)])
def edit_items(request: Request, body: BulkEdit):
    """Set the same fields on several tracks.

    Album fields (album artist, year, …) belong to the album for an album's tracks. When every
    track of an album ends up with the same value, the album takes it too; otherwise the tracks
    differ from their album, as after `beet modify` on some of them.
    """
    check_fields(body.fields, BULK_ITEM_FIELDS, "track")
    lib = get_lib(request)
    items = [lib.get_item(item_id) for item_id in body.ids]
    if None in items:
        raise HTTPException(404, "item not found")
    for item in items:
        save_item(item, body.fields)

    album_keys = [key for key in body.fields if key in Album.item_keys]
    for album_id in {item.album_id for item in items if item.album_id is not None}:
        album = lib.get_album(album_id)
        tracks = list(album.items())
        agreed = {
            key: tracks[0][key] for key in album_keys if len({repr(t[key]) for t in tracks}) == 1
        }
        if agreed:
            # Synced like an album edit: moving the tracks above went by the album's old values,
            # so this is what puts the files and the art where the new ones say.
            album.update(agreed)
            album.try_sync(ui.should_write(), ui.should_move(), inherit=True)
    return {"updated": len(items)}
