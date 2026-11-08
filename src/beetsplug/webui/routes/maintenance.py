"""Keeping the library in shape: syncing it with the files, and checking its health."""

import os
import threading
from collections import defaultdict
from typing import Any

from beets import ui, util
from beets.library import Album, Item, Library
from beets.ui.commands.update import update_items
from fastapi import APIRouter, Depends, HTTPException, Request

from .art import embedded_art, folder_image, stored_art
from .common import get_lib
from .imports import require_same_origin

router = APIRouter()

_update_lock = threading.Lock()


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


def file_missing(item: Item) -> bool:
    return not item.path or not os.path.exists(util.syspath(item.path))


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
        if file_missing(i)
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


# Each health check: what it's called, and what it means for an album.
HEALTH_CHECKS = {
    "missing_files": ("Missing files", "Some of the album's files are gone. Update the library."),
    "missing_tracks": (
        "Missing tracks",
        "Fewer tracks than the release has, going by the track totals in the tags.",
    ),
    "no_art": ("No cover", "No art file, cover image in the album's folder or embedded art."),
    "unmatched": (
        "Not matched",
        "Imported as-is, without a MusicBrainz or Discogs release. Re-import to match it.",
    ),
    "duplicates": ("Duplicates", "Another album is the same release, or has the same name."),
}


def missing_tracks(items: list[Item]) -> bool:
    """Whether a disc has fewer tracks than its track total says; untotalled discs are skipped."""
    discs: dict[int, list[Item]] = defaultdict(list)
    for item in items:
        discs[item.disc or 1].append(item)
    return any(
        0 < len(tracks) < max(t.tracktotal or 0 for t in tracks) for tracks in discs.values()
    )


def has_art(album: Album, items: list[Item]) -> bool:
    # Cheapest first: embedded art means reading a file's tags.
    if stored_art(album):
        return True
    return bool(items) and bool(folder_image(items[0]) or embedded_art(items[0]))


def unmatched(album: Album) -> bool:
    return not (album.mb_albumid or album.discogs_albumid or album.get("data_source"))


def duplicate_ids(albums: list[Album]) -> set[int]:
    groups: dict[Any, list[int]] = defaultdict(list)
    for album in albums:
        if album.mb_albumid:
            groups["mb", album.mb_albumid].append(album.id)
        groups["name", album.albumartist.lower(), album.album.lower()].append(album.id)
    return {album_id for ids in groups.values() if len(ids) > 1 for album_id in ids}


@router.get("/library/health")
def library_health(request: Request):
    """Which albums have problems, by check, and the share of albums that have none."""
    lib = get_lib(request)
    albums = list(lib.albums())
    tracks: dict[int, list[Item]] = defaultdict(list)
    for item in lib.items("singleton:false"):
        tracks[item.album_id].append(item)
    duplicates = duplicate_ids(albums)

    found: dict[str, list[Album]] = {check: [] for check in HEALTH_CHECKS}
    healthy = 0
    for album in albums:
        items = tracks.get(album.id, [])
        problems = {
            "missing_files": any(file_missing(i) for i in items),
            "missing_tracks": missing_tracks(items),
            "no_art": not has_art(album, items),
            "unmatched": unmatched(album),
            "duplicates": album.id in duplicates,
        }
        for check, failed in problems.items():
            if failed:
                found[check].append(album)
        healthy += not any(problems.values())

    return {
        "albums": len(albums),
        "healthy": healthy,
        "checks": [
            {
                "id": check,
                "label": label,
                "description": description,
                "albums": [
                    {"id": a.id, "album": a.album, "albumartist": a.albumartist, "year": a.year}
                    for a in found[check]
                ],
            }
            for check, (label, description) in HEALTH_CHECKS.items()
        ],
    }
