"""Album art: serving it from wherever music players would find it, and fetching, uploading,
embedding or saving it as a file."""

import os
import tempfile
from pathlib import Path
from typing import Literal

import mediafile
from beets import logging, plugins, util
from beets.library import Album, Item

# Private to beets' bundled plugins, but what `beet embedart` and `beet extractart` run; beets is
# pinned to one minor version, so it doesn't move under us.
from beetsplug._utils.art import embed_album, extract_first
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .common import get_lib
from .imports import require_same_origin

router = APIRouter()
# beets' logger: the art helpers format messages with {} placeholders.
log = logging.getLogger("beets")

# Images music players pick up from an album's folder, in order of preference.
FOLDER_ART = ("cover", "folder", "front", "album")
ART_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
ART_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_UPLOAD = 25 * 1024 * 1024

ArtSource = Literal["file", "folder", "embedded"]


def stored_art(album: Album) -> str | None:
    """The art file beets keeps for the album, if it's still there."""
    if album.artpath and os.path.isfile(util.syspath(album.artpath)):
        return util.syspath(album.artpath)
    return None


def folder_image(item: Item) -> Path | None:
    """A cover image next to the item's file that beets doesn't know about."""
    folder = Path(util.syspath(os.path.dirname(item.path)))
    if not folder.is_dir():
        return None
    images = {p.name.lower(): p for p in folder.iterdir() if p.suffix.lower() in ART_EXTENSIONS}
    for name in FOLDER_ART:
        for ext in ART_EXTENSIONS:
            if name + ext in images:
                return images[name + ext]
    return None


def embedded_art(item: Item) -> bytes | None:
    try:
        return mediafile.MediaFile(util.syspath(item.path)).art
    except (OSError, mediafile.UnreadableFileError):
        return None


def find_art(album: Album) -> tuple[ArtSource, str | Path | bytes] | None:
    """The album's art: what beets stored, else a cover image in its folder, else embedded art."""
    if path := stored_art(album):
        return "file", path
    item = album.items().get()
    if item is None:
        return None
    if image := folder_image(item):
        return "folder", image
    if data := embedded_art(item):
        return "embedded", data
    return None


def art_response(found: tuple[ArtSource, str | Path | bytes] | None) -> Response:
    if found is None:
        raise HTTPException(404, "no art")
    _, art = found
    if isinstance(art, bytes):
        return Response(art, media_type=mediafile.image_mime_type(art) or "image/jpeg")
    return FileResponse(art)


def get_album_or_404(request: Request, album_id: int) -> Album:
    album = get_lib(request).get_album(album_id)
    if album is None:
        raise HTTPException(404, "album not found")
    return album


@router.get("/albums/{album_id}/art")
def get_album_art(request: Request, album_id: int):
    return art_response(find_art(get_album_or_404(request, album_id)))


@router.get("/items/{item_id}/art")
def get_item_art(request: Request, item_id: int):
    """An album track shows its album's art; a single track only its own embedded art."""
    lib = get_lib(request)
    item = lib.get_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if album := item.get_album():
        return art_response(find_art(album))
    data = embedded_art(item)
    return art_response(("embedded", data) if data else None)


@router.post("/albums/{album_id}/art/fetch", dependencies=[Depends(require_same_origin)])
def fetch_album_art(request: Request, album_id: int):
    """Like `beet fetchart -f` for one album, using the sources configured for fetchart."""
    album = get_album_or_404(request, album_id)
    fetchart = next((p for p in plugins.find_plugins() if p.name == "fetchart"), None)
    if fetchart is None:
        raise HTTPException(400, "Add fetchart to the plugins in your beets config to fetch art.")
    fetchart.batch_fetch_art(get_lib(request), [album], force=True, quiet=True)
    album.load()
    if not stored_art(album):
        raise HTTPException(404, "None of fetchart's sources had art for this album.")
    return {"art_source": "file"}


@router.put("/albums/{album_id}/art", dependencies=[Depends(require_same_origin)])
async def upload_album_art(request: Request, album_id: int):
    """Replace the album's art file with the uploaded image (the request body)."""
    album = get_album_or_404(request, album_id)
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "That image is too big (25 MB at most).")
    ext = ART_TYPES.get(mediafile.image_mime_type(data) or "")
    if ext is None:
        raise HTTPException(400, "Upload a JPEG, PNG or WebP image.")
    set_art_from_bytes(album, data, ext)
    return {"art_source": "file"}


@router.post("/albums/{album_id}/art/save", dependencies=[Depends(require_same_origin)])
def save_album_art(request: Request, album_id: int):
    """Turn art beets doesn't track yet (a folder image or embedded art) into its art file."""
    album = get_album_or_404(request, album_id)
    found = find_art(album)
    if found is None:
        raise HTTPException(404, "This album has no art to save.")
    source, art = found
    if source == "folder":
        album.set_art(os.fsencode(art), copy=True)
        album.store()
    elif source == "embedded":
        with tempfile.TemporaryDirectory() as tmp:
            out = extract_first(log, os.fsencode(os.path.join(tmp, "cover")), album.items())
            if out is None:
                raise HTTPException(500, "Couldn't extract the embedded art.")
            album.set_art(out, copy=True)
            album.store()
    return {"art_source": "file"}


@router.post("/albums/{album_id}/art/embed", dependencies=[Depends(require_same_origin)])
def embed_album_art(request: Request, album_id: int):
    """Like `beet embedart`: write the album's art file into each of its tracks."""
    album = get_album_or_404(request, album_id)
    if not stored_art(album):
        raise HTTPException(400, "Fetch, upload or save art for this album first.")
    embed_album(log, album, quiet=True)
    return {"ok": True}


def set_art_from_bytes(album: Album, data: bytes, ext: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cover" + ext)
        Path(path).write_bytes(data)
        album.set_art(os.fsencode(path), copy=True)
        album.store()
