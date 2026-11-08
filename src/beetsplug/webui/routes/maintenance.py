"""Keeping the library in shape: syncing it with the files, and checking its health."""

import os
import threading
from collections import defaultdict
from typing import Any

from beets import ui, util
from beets.library import Album, Item, Library
from beets.ui.commands.update import update_items
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .art import embedded_art, folder_image, stored_art
from .common import find_plugin, get_lib
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


def missing_track_numbers(items: list[Item]) -> dict[int, list[int]]:
    """Per disc with fewer tracks than its track total, the numbers no track has (possibly none,
    when tracks share a number). Discs without a total are skipped."""
    discs: dict[int, list[Item]] = defaultdict(list)
    for item in items:
        discs[item.disc or 1].append(item)
    missing = {}
    for disc, tracks in sorted(discs.items()):
        total = max(t.tracktotal or 0 for t in tracks)
        if 0 < len(tracks) < total:
            have = {t.track for t in tracks}
            missing[disc] = [n for n in range(1, total + 1) if n not in have]
    return missing


def has_art(album: Album, items: list[Item]) -> bool:
    # Cheapest first: embedded art means reading a file's tags.
    if stored_art(album):
        return True
    return bool(items) and bool(folder_image(items[0]) or embedded_art(items[0]))


def unmatched(album: Album) -> bool:
    return not (album.mb_albumid or album.discogs_albumid or album.get("data_source"))


def duplicates_of(albums: list[Album]) -> dict[int, set[int]]:
    """For each album that has duplicates, the other albums: same release, or same name."""
    groups: dict[Any, list[int]] = defaultdict(list)
    for album in albums:
        if album.mb_albumid:
            groups["mb", album.mb_albumid].append(album.id)
        groups["name", album.albumartist.lower(), album.album.lower()].append(album.id)
    others: dict[int, set[int]] = defaultdict(set)
    for ids in groups.values():
        for album_id in ids:
            others[album_id].update(i for i in ids if i != album_id)
    return {album_id: ids for album_id, ids in others.items() if ids}


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def album_problems(
    album: Album, items: list[Item], duplicates: dict[int, set[int]]
) -> dict[str, str]:
    """The checks an album fails, each with what exactly is wrong."""
    problems = {}
    if gone := [i for i in items if file_missing(i)]:
        names = ", ".join(os.path.basename(util.displayable_path(i.path)) for i in gone[:5])
        more = f" and {len(gone) - 5} more" if len(gone) > 5 else ""
        problems["missing_files"] = f"{plural(len(gone), 'file')} gone: {names}{more}."
    if missing := missing_track_numbers(items):
        several_discs = len({i.disc or 1 for i in items}) > 1
        parts = []
        for disc, numbers in missing.items():
            what = (
                f"{'track' if len(numbers) == 1 else 'tracks'} {', '.join(map(str, numbers))}"
                if numbers
                else "tracks (some share a number)"
            )
            parts.append(f"{what} of disc {disc}" if several_discs else what)
        problems["missing_tracks"] = f"Missing {'; '.join(parts)}, going by the track totals."
    if not has_art(album, items):
        problems["no_art"] = "No cover file, cover image in the folder or embedded art."
    if unmatched(album):
        problems["unmatched"] = "Not matched to a MusicBrainz or Discogs release."
    if others := duplicates.get(album.id):
        problems["duplicates"] = f"Same release or name as {plural(len(others), 'other album')}."
    return problems


def scan_library(lib: Library) -> tuple[list[Album], dict[int, dict[str, str]]]:
    """Every album, and the problems of those that have any."""
    albums = list(lib.albums())
    tracks: dict[int, list[Item]] = defaultdict(list)
    for item in lib.items("singleton:false"):
        tracks[item.album_id].append(item)
    duplicates = duplicates_of(albums)
    problems = {}
    for album in albums:
        if found := album_problems(album, tracks.get(album.id, []), duplicates):
            problems[album.id] = found
    return albums, problems


def problems_of(lib: Library, album: Album) -> list[dict[str, Any]]:
    """One album's problems, for its page; duplicates name the other albums."""
    duplicates = duplicates_of(list(lib.albums()))
    found = album_problems(album, list(album.items()), duplicates)
    out = []
    for check, detail in found.items():
        problem: dict[str, Any] = {"id": check, "label": HEALTH_CHECKS[check][0], "detail": detail}
        if check == "duplicates":
            problem["others"] = [
                {"id": a.id, "album": a.album, "albumartist": a.albumartist, "year": a.year}
                for a in (lib.get_album(i) for i in sorted(duplicates[album.id]))
                if a is not None
            ]
        out.append(problem)
    return out


@router.get("/library/health")
def library_health(request: Request):
    """Which albums have problems, by check, and the share of albums that have none."""
    albums, problems = scan_library(get_lib(request))
    return {
        "albums": len(albums),
        "healthy": len(albums) - len(problems),
        "checks": [
            {
                "id": check,
                "label": label,
                "description": description,
                "albums": [
                    {"id": a.id, "album": a.album, "albumartist": a.albumartist, "year": a.year}
                    for a in albums
                    if check in problems.get(a.id, {})
                ],
            }
            for check, (label, description) in HEALTH_CHECKS.items()
        ],
    }


def ftintitle_plugin():
    """The ftintitle plugin from the beets config: its settings (format, drop, …) apply."""
    plugin = find_plugin("ftintitle")
    if plugin is None:
        raise HTTPException(
            400, "Add ftintitle to the plugins in your beets config to move featured artists."
        )
    return plugin


def moved_feat(plugin, item: Item) -> Item | None:
    """The track as ftintitle would leave it, or None when it has nothing to move."""
    copy = item.copy()
    return copy if plugin.ft_in_title(copy, item.get("albumartist") or "") else None


@router.get("/library/ftintitle")
def preview_ftintitle(request: Request):
    """Every track whose artist names a featured artist, with the artist and title it'd get."""
    plugin = ftintitle_plugin()
    changes = []
    for item in get_lib(request).items():
        if (after := moved_feat(plugin, item)) is not None:
            changes.append(
                {
                    "id": item.id,
                    "album_id": item.album_id,
                    "album": item.album,
                    "artist": item.artist,
                    "title": item.title,
                    "new_artist": after.artist,
                    "new_title": after.title,
                }
            )
    return {"changes": changes, "moves_files": ui.should_move()}


class ApplyFtInTitle(BaseModel):
    # The tracks approved in the preview.
    ids: list[int] = Field(min_length=1)


@router.post("/library/ftintitle", dependencies=[Depends(require_same_origin)])
def apply_ftintitle(request: Request, body: ApplyFtInTitle):
    """Like `beet ftintitle` on the approved tracks: store, write the tags, move files to match."""
    plugin = ftintitle_plugin()
    lib = get_lib(request)
    write, move = ui.should_write(), ui.should_move()
    changed = 0
    for item_id in body.ids:
        item = lib.get_item(item_id)
        if item is not None and plugin.ft_in_title(item, item.get("albumartist") or ""):
            item.try_sync(write, move)
            changed += 1
    return {"changed": changed}
