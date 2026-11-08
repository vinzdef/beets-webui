"""Album art: serving it from wherever music players would find it, and fetching, uploading,
embedding or saving it as a file."""

import contextvars
import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import anyio
import mediafile
from beets import logging, util
from beets.library import Album, Item, Library
from beets.util.artresizer import ArtResizer

# Private to beets' bundled plugins, but what `beet embedart` and `beet extractart` run; beets is
# pinned to one minor version, so it doesn't move under us.
from beetsplug._utils.art import embed_album, extract_first
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .common import find_plugin, get_lib
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
    fetchart = find_plugin("fetchart")
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
    too_big = HTTPException(413, "That image is too big (25 MB at most).")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise HTTPException(400, "Bad Content-Length header.") from None
    if declared > MAX_UPLOAD:
        raise too_big
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD:
            raise too_big
    ext = ART_TYPES.get(mediafile.image_mime_type(bytes(data)) or "")
    if ext is None:
        raise HTTPException(400, "Upload a JPEG, PNG or WebP image.")

    # The database and the copy into the album's folder (maybe on a slow drive) block, so they
    # run off the event loop, as sync endpoints do.
    def save() -> None:
        set_art_from_bytes(get_album_or_404(request, album_id), bytes(data), ext)

    await anyio.to_thread.run_sync(save)
    return {"art_source": "file"}


def save_local_art(album: Album) -> ArtSource | None:
    """Give an album without an art file one from art it already has: an image in its folder,
    else art embedded in its tracks. The file is named by `art_filename` (cover.jpg by default),
    so a folder.jpg is copied to cover.jpg. Returns where the art came from."""
    found = find_art(album)
    if found is None or found[0] == "file":
        return None
    source, art = found
    if source == "folder":
        album.set_art(os.fsencode(art), copy=True)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            out = extract_first(log, os.fsencode(os.path.join(tmp, "cover")), album.items())
            if out is None:
                return None
            album.set_art(out, copy=True)
    album.store()
    return source


@router.post("/albums/{album_id}/art/save", dependencies=[Depends(require_same_origin)])
def save_album_art(request: Request, album_id: int):
    """Turn a folder image or embedded art into the album's art file."""
    album = get_album_or_404(request, album_id)
    if not stored_art(album) and save_local_art(album) is None:
        raise HTTPException(404, "This album has no art to save.")
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


class BackgroundJob:
    """Library-wide work in a thread, one run at a time, with a state the page polls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {"running": False}

    def start(self, state: dict[str, Any], work: Callable[[], None]) -> bool:
        with self._lock:
            if self.state["running"]:
                return False
            self.state = {"running": True, "done": 0, **state}

        def run() -> None:
            try:
                work()
            finally:
                with self._lock:
                    self.state["running"] = False

        # beets resolves the library's relative paths through a context variable, which a new
        # thread doesn't inherit; run in a copy of this request's context.
        ctx = contextvars.copy_context()
        threading.Thread(target=ctx.run, args=(run,), name=self.name, daemon=True).start()
        return True

    def update(self, add: dict[str, int] | None = None, **append: Any) -> None:
        """Count one more item done; add to counters and append to lists in the state."""
        with self._lock:
            self.state["done"] += 1
            for key, n in (add or {}).items():
                self.state[key] += n
            for key, value in append.items():
                self.state[key].append(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {k: list(v) if isinstance(v, list) else v for k, v in self.state.items()}


covers = BackgroundJob("webui-covers")


def fill_covers(lib: Library, albums: list[Album], fetch: bool) -> None:
    """Give each album an art file: from its folder or tags first, then fetchart's sources."""
    fetchart = find_plugin("fetchart") if fetch else None
    for album in albums:
        try:
            source = save_local_art(album)
            if source is None and fetchart is not None:
                fetchart.batch_fetch_art(lib, [album], force=False, quiet=True)
                album.load()
                source = "fetched" if stored_art(album) else None
        except Exception:
            log.exception("couldn't get art for {}", album)
            source = None
        if source:
            covers.update({source: 1})
        else:
            covers.update(
                not_found={"id": album.id, "album": album.album, "albumartist": album.albumartist}
            )


@router.get("/library/covers")
def cover_fill_status():
    """How the current (or last) run of filling missing covers is going."""
    return {**covers.snapshot(), "can_fetch": find_plugin("fetchart") is not None}


class FillCovers(BaseModel):
    # Also look online with fetchart's sources, when the plugin is on.
    fetch: bool = True


@router.post("/library/covers", dependencies=[Depends(require_same_origin)])
def fill_missing_covers(request: Request, body: FillCovers):
    lib = get_lib(request)
    albums = [a for a in lib.albums() if not stored_art(a)]
    state = {"total": len(albums), "folder": 0, "embedded": 0, "fetched": 0, "not_found": []}
    if not covers.start(state, lambda: fill_covers(lib, albums, body.fetch)):
        raise HTTPException(409, "Missing covers are already being filled.")
    return cover_fill_status()


shrinking = BackgroundJob("webui-shrink-art")


# Narrower than this, a cover isn't made smaller to meet the size limit.
MIN_WIDTH = 200


def shrink_image(data: bytes, max_width: int, quality: int, max_bytes: int) -> bytes | None:
    """The image as a JPEG at most `max_width` wide and `max_bytes` big, or None when it's
    already within both. Every track carries its own copy of the cover, so this is paid once
    per track. To meet the size, the quality is lowered first, then the image made narrower
    (down to MIN_WIDTH); if even that's too big, the smallest try is used."""
    resizer = ArtResizer.shared
    with tempfile.TemporaryDirectory() as tmp:
        ext = mediafile.image_extension(data) or "jpg"
        path = os.fsencode(os.path.join(tmp, f"in.{ext}"))
        Path(os.fsdecode(path)).write_bytes(data)
        size = resizer.get_size(path)
        if size is None:
            return None  # not an image the resizer can read; leave it be
        if size[0] <= max_width and len(data) <= max_bytes:
            return None
        # Writing a .jpg converts as it resizes: PNGs and the like get much smaller as JPEGs. If
        # that fails (Pillow can't save transparency as JPEG), keep the format. On failure the
        # resizer logs it and hands back the input instead of the output.
        for out_ext in dict.fromkeys(["jpg", ext]):
            out = os.fsencode(os.path.join(tmp, f"out.{out_ext}"))
            width, smallest = min(max_width, size[0]), None
            while True:
                if resizer.resize(width, path, out, quality, max_filesize=max_bytes) != out:
                    break
                result = Path(os.fsdecode(out)).read_bytes()
                if smallest is None or len(result) < len(smallest):
                    smallest = result
                if len(result) <= max_bytes or width <= MIN_WIDTH:
                    return smallest
                width = max(MIN_WIDTH, width * 3 // 4)
            if smallest is not None:
                return smallest
        return None


def shrink_embedded_art(items: list[Item], max_width: int, quality: int, max_bytes: int) -> None:
    """Rewrite each track's embedded covers smaller, keeping its other images and those that
    wouldn't get smaller. Tracks of an album usually share a cover, so each is shrunk once per
    album; only the current album's are kept, so memory doesn't grow with the library."""
    shrunk: dict[str, bytes | None] = {}
    album_id: object = object()
    for item in sorted(items, key=lambda i: (i.album_id is None, i.album_id or 0, i.id)):
        if item.album_id is None or item.album_id != album_id:
            shrunk.clear()
            album_id = item.album_id
        try:
            tags = mediafile.MediaFile(util.syspath(item.path))
            images = tags.images or []
            changed, saved = False, 0
            for i, image in enumerate(images):
                key = hashlib.sha1(image.data).hexdigest()
                if key not in shrunk:
                    shrunk[key] = shrink_image(image.data, max_width, quality, max_bytes)
                smaller = shrunk[key]
                if smaller is not None and len(smaller) < len(image.data):
                    saved += len(image.data) - len(smaller)
                    images[i] = mediafile.Image(smaller, desc=image.desc, type=image.type)
                    changed = True
            if changed:
                tags.images = images
                tags.save()
                # beets would otherwise think the file changed outside it on the next update.
                item.mtime = item.current_mtime()
                item.store()
                shrinking.update({"rewritten": 1, "saved_bytes": saved})
            else:
                shrinking.update({"unchanged" if images else "no_art": 1})
        except Exception:
            log.exception("couldn't shrink the art in {}", util.displayable_path(item.path))
            shrinking.update({"failed": 1})


@router.get("/library/embedded-art")
def shrink_status():
    """How the current (or last) run of shrinking embedded covers is going."""
    return {**shrinking.snapshot(), "can_resize": bool(ArtResizer.shared.local)}


class ShrinkArt(BaseModel):
    max_width: int = Field(1000, ge=100, le=4000)
    quality: int = Field(85, ge=30, le=100)
    # Each cover's target size; covers over it are shrunk even when narrow enough.
    max_kb: int = Field(100, ge=10, le=2000)


@router.post("/library/embedded-art", dependencies=[Depends(require_same_origin)])
def shrink_embedded_covers(request: Request, body: ShrinkArt):
    if not ArtResizer.shared.local:
        raise HTTPException(400, "Shrinking images needs ImageMagick or Pillow on the server.")
    items = list(get_lib(request).items())
    state = {"total": len(items), "rewritten": 0, "unchanged": 0, "no_art": 0, "failed": 0}
    state["saved_bytes"] = 0
    if not shrinking.start(
        state, lambda: shrink_embedded_art(items, body.max_width, body.quality, body.max_kb * 1024)
    ):
        raise HTTPException(409, "Embedded covers are already being shrunk.")
    return shrink_status()
