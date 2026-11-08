"""Create silent test albums tagged with real MusicBrainz data, for trying out imports.

    uv run python scripts/make_test_albums.py examples/docker/inbox

Each album is a folder of silent 32 kbps MP3s (about 10 MB per album) whose tags and track
lengths come from a MusicBrainz release, so beets matches them like real rips. The scenarios
cover an exact match, a missing track (beets always asks about those), slightly messy tags (a
strong but imperfect match: Auto applies it, Manual asks), an untagged album (needs a search) and
loose tracks (for importing as individual tracks).
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mediafile import MediaFile

API = "https://musicbrainz.org/ws/2"
USER_AGENT = "beets-webui-test-albums/0.1 (https://github.com/vinzdef/beets-webui)"

# One MPEG-1 Layer III frame of silence at 32 kbps, 44.1 kHz. Players and mutagen estimate the
# length of a constant-bitrate file from its size, so each frame counts for 104 * 8 / 32000 s.
FRAME = bytes([0xFF, 0xFB, 0x10, 0xC4]) + bytes(100)
SECONDS_PER_FRAME = len(FRAME) * 8 / 32000

_last_request = 0.0


def musicbrainz(path: str, **params: str) -> dict:
    """GET a MusicBrainz API resource, keeping to its limit of one request per second."""
    global _last_request
    url = f"{API}/{path}?{urllib.parse.urlencode({**params, 'fmt': 'json'})}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(6):
        time.sleep(max(0.0, 1.1 - (time.monotonic() - _last_request)))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # 503 means rate-limited (other clients on this IP count too): back off and retry.
            if error.code != 503 or attempt == 5:
                raise
            time.sleep(2**attempt)
        finally:
            _last_request = time.monotonic()
    raise AssertionError("unreachable")


def find_release(artist: str, album: str, tracks: int) -> dict:
    """An official CD release of an album with the usual number of tracks (not a bonus edition)."""
    query = f'release:"{album}" AND artist:"{artist}" AND status:official AND format:CD'
    for candidate in musicbrainz("release/", query=query, limit="10")["releases"]:
        release = musicbrainz(f"release/{candidate['id']}", inc="recordings artist-credits")
        found = [t for medium in release["media"] for t in medium["tracks"]]
        if len(found) == tracks and all(t.get("length") for t in found):
            return release
    raise SystemExit(f"no usable release found for {artist} - {album}")


def write_track(path: Path, length_ms: int, tags: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(FRAME * round(length_ms / 1000 / SECONDS_PER_FRAME))
    if tags:
        media = MediaFile(path)
        media.update(tags)
        media.save()


def artist_name(credit: list[dict]) -> str:
    return "".join(c["name"] + c.get("joinphrase", "") for c in credit)


def album_tracks(release: dict) -> list[tuple[int, dict]]:
    return [(i, t) for i, t in enumerate((t for m in release["media"] for t in m["tracks"]), 1)]


def tags_for(release: dict, number: int, track: dict, total: int) -> dict:
    return {
        "artist": artist_name(track["artist-credit"]),
        "albumartist": artist_name(release["artist-credit"]),
        "album": release["title"],
        "title": track["title"],
        "track": number,
        "tracktotal": total,
        "year": int(release["date"][:4]) if release.get("date") else None,
    }


def make_album(inbox: Path, folder: str, release: dict, *, skip=(), mangle=None) -> None:
    tracks = album_tracks(release)
    for number, track in tracks:
        if number in skip:
            continue
        tags = tags_for(release, number, track, len(tracks))
        if mangle:
            tags = mangle(tags)
        name = f"{number:02d} - {track['title']}.mp3".replace("/", "-")
        write_track(inbox / folder / name, track["length"], tags)


def messy(tags: dict) -> dict:
    """Tags like a careless rip: lower-case names, a year in the album title, stray suffixes."""
    return tags | {
        "artist": tags["artist"].lower(),
        "albumartist": tags["albumartist"].lower(),
        "album": f"{tags['album'].lower()} (2001)",
        "title": f"{tags['title']} (album version)" if tags["track"] % 3 == 0 else tags["title"],
        "year": None,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    inbox = Path(sys.argv[1])
    inbox.mkdir(parents=True, exist_ok=True)

    print("Exact match: Radiohead - OK Computer")
    ok_computer = find_release("Radiohead", "OK Computer", 12)
    make_album(inbox, "Radiohead - OK Computer", ok_computer)

    print("Missing a track: Portishead - Dummy")
    dummy = find_release("Portishead", "Dummy", 11)
    make_album(inbox, "Portishead - Dummy (incomplete)", dummy, skip={len(album_tracks(dummy))})

    print("Messy tags: Daft Punk - Discovery")
    make_album(
        inbox, "daft punk discovery", find_release("Daft Punk", "Discovery", 14), mangle=messy
    )

    print("No tags at all: Massive Attack - Mezzanine")
    make_album(
        inbox, "Unknown album", find_release("Massive Attack", "Mezzanine", 11), mangle=lambda t: {}
    )

    print("Loose tracks from different albums")
    for number, release in ((1, ok_computer), (2, dummy)):
        _, track = album_tracks(release)[number - 1]
        tags = tags_for(release, number, track, len(album_tracks(release)))
        write_track(inbox / "Loose tracks" / f"{track['title']}.mp3", track["length"], tags)

    print(f"Done: {inbox}")


if __name__ == "__main__":
    main()
