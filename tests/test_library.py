import io

from beets.library import Item


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_list_albums(client):
    body = client.get("/api/albums").json()
    assert body["total"] == 1
    assert body["results"][0]["album"] == "OK Computer"


def test_artist_view_lists_loose_tracks_with_their_artist(client, lib):
    (album,) = lib.albums()
    album.albumartist = "Radiohead"
    album.store()
    lib.add(Item(title="Airbag", artist="radiohead", path=b"/music/airbag.mp3"))
    body = client.get("/api/artists").json()
    rows = [
        (r["kind"], r.get("album") if r["kind"] == "album" else r["title"]) for r in body["results"]
    ]
    assert rows == [
        ("track", "Loose Track"),  # Portishead
        ("album", "OK Computer"),  # Radiohead: albums first, then loose tracks
        ("track", "Airbag"),
    ]
    assert (body["total"], body["albums"], body["tracks"]) == (3, 1, 2)

    body = client.get("/api/artists", params={"q": "radiohead", "offset": 1}).json()
    assert [r["kind"] for r in body["results"]] == ["track"]


def test_artist_page(client, lib):
    (album,) = lib.albums()
    album.albumartist = "Radiohead"
    album.store()
    lib.add(Item(title="Airbag", artist="radiohead", bitrate=320000, path=b"/music/airbag.mp3"))
    lib.add_album(
        [Item(title="Theirs", artist="Radiohead", album="Mix", albumartist="Various Artists")]
    )

    body = client.get("/api/artist", params={"name": "RADIOHEAD"}).json()
    assert body["name"] == "Radiohead"
    assert [a["album"] for a in body["albums"]] == ["OK Computer"]
    assert [a["album"] for a in body["appears_on"]] == ["Mix"]
    assert [(t["title"], t["bitrate"]) for t in body["tracks"]] == [("Airbag", 320000)]
    assert client.get("/api/artist", params={"name": "Radio"}).status_code == 404


def test_album_detail_includes_items(client):
    album_id = client.get("/api/albums").json()["results"][0]["id"]
    body = client.get(f"/api/albums/{album_id}").json()
    assert [i["track"] for i in body["items"]] == [1, 2, 3]
    assert body["items"][0]["path"] == "/music/ok-computer/01.flac"


def test_item_query(client):
    body = client.get("/api/items", params={"q": "artist:portishead"}).json()
    assert body["total"] == 1
    assert body["results"][0]["title"] == "Loose Track"


def test_songs_sort_and_filter(client):
    def titles(**params):
        return [r["title"] for r in client.get("/api/items", params=params).json()["results"]]

    assert titles(sort="title") == ["Loose Track", "Track 1", "Track 2", "Track 3"]
    assert titles(sort="title", desc=True) == ["Track 3", "Track 2", "Track 1", "Loose Track"]
    assert titles(sort="track", desc=True)[:3] == ["Track 3", "Track 2", "Track 1"]
    assert titles(only="singletons") == ["Loose Track"]
    assert titles(only="on_album", sort="title", desc=True) == ["Track 3", "Track 2", "Track 1"]
    assert titles(q="radiohead", only="singletons") == []
    assert client.get("/api/items", params={"sort": "path"}).status_code == 422


def test_item_file_streams_with_ranges(client, lib, tmp_path):
    song = tmp_path / "song.mp3"
    song.write_bytes(bytes(range(256)) * 4)
    item = lib.items("title:Loose").get()
    item.path = str(song).encode()
    item.store()

    res = client.get(f"/api/items/{item.id}/file")
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert res.content == song.read_bytes()
    res = client.get(f"/api/items/{item.id}/file", headers={"Range": "bytes=10-19"})
    assert res.status_code == 206
    assert res.content == bytes(range(10, 20))
    # The fixture's other tracks have no file on disk.
    other = lib.items("album:OK").get()
    assert client.get(f"/api/items/{other.id}/file").status_code == 404


def test_pagination(client):
    body = client.get("/api/items", params={"offset": 1, "limit": 2}).json()
    assert body["total"] == 4
    assert len(body["results"]) == 2


def test_missing_album(client):
    assert client.get("/api/albums/999").status_code == 404
    assert client.get("/api/albums/999/art").status_code == 404


def test_update_preview_lists_missing_files(client, lib, tmp_path):
    lib.directory = str(tmp_path).encode()
    missing = client.get("/api/library/update").json()["missing"]
    assert sorted(m["title"] for m in missing) == ["Loose Track", "Track 1", "Track 2", "Track 3"]
    assert client.get("/api/items").json()["total"] == 4


def test_update_removes_missing_files(client, lib, tmp_path):
    lib.directory = str(tmp_path).encode()
    # None of the fixture's files exist on disk.
    body = client.post("/api/library/update").json()
    assert body == {"removed_items": 4, "removed_albums": 1}
    assert client.get("/api/items").json()["total"] == 0


def test_update_refuses_without_library_folder(client, lib, tmp_path):
    lib.directory = str(tmp_path / "unmounted").encode()
    assert client.post("/api/library/update").status_code == 409
    assert client.get("/api/items").json()["total"] == 4


def test_album_art_falls_back_to_folder_image(client, lib, tmp_path):
    album = lib.albums().get()
    folder = tmp_path / "ok-computer"
    folder.mkdir()
    (folder / "Cover.JPG").write_bytes(b"\xff\xd8\xff fake jpeg")
    for item in album.items():
        item.path = str(folder / f"{item.track:02d}.flac").encode()
        item.store()
    res = client.get(f"/api/albums/{album.id}/art")
    assert res.status_code == 200
    assert res.content == b"\xff\xd8\xff fake jpeg"


def test_album_art_thumbnail(client, lib, tmp_path):
    from PIL import Image

    album = lib.albums().get()
    cover = tmp_path / "cover.png"
    Image.new("RGB", (1200, 1200), (200, 10, 10)).save(cover)
    album.artpath = str(cover).encode()
    album.store()

    res = client.get(f"/api/albums/{album.id}/art", params={"thumb": True})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(res.content)).size == (400, 400)
    (thumb,) = (tmp_path / "webui-thumbs").iterdir()  # next to the library database, made once
    assert client.get(f"/api/albums/{album.id}/art", params={"thumb": True}).content == res.content
    assert list((tmp_path / "webui-thumbs").iterdir()) == [thumb]
    # The full cover is still there without `thumb`.
    assert client.get(f"/api/albums/{album.id}/art").content == cover.read_bytes()


def test_library_health(client, lib):
    # The fixture's files don't exist, and it was never matched or given art.
    lib.add_album([Item(title="Again", artist="Radiohead", album="OK Computer", path=b"/x.flac")])
    body = client.get("/api/library/health").json()
    assert body["albums"] == 2
    assert body["healthy"] == 0
    failed = {c["id"]: len(c["albums"]) for c in body["checks"]}
    assert failed == {
        "missing_files": 2,
        "missing_tracks": 0,
        "no_art": 2,
        "unmatched": 2,
        "duplicates": 2,
    }


def test_albums_filtered_by_problem(client, lib):
    album = lib.albums().get()
    for item in album.items():
        item.tracktotal = 5
        item.store()
    other = lib.add_album(
        [Item(title="Again", artist="Radiohead", album="OK Computer", path=b"/x")]
    )

    def ids(**params):
        body = client.get("/api/albums", params=params).json()
        return [a["id"] for a in body["results"]]

    assert ids(problem="missing_tracks") == [album.id]
    assert sorted(ids(problem="duplicates")) == sorted([album.id, other.id])
    assert sorted(ids(problem="any")) == sorted([album.id, other.id])
    assert ids(problem="missing_tracks", q="artist:portishead") == []
    assert client.get("/api/albums", params={"problem": "bogus"}).status_code == 400

    problems = {p["id"]: p for p in client.get(f"/api/albums/{album.id}").json()["problems"]}
    assert problems["missing_tracks"]["detail"] == "Missing tracks 4, 5, going by the track totals."
    assert problems["missing_files"]["detail"].startswith("3 files gone: 01.flac, 02.flac")
    assert [a["id"] for a in problems["duplicates"]["others"]] == [other.id]


def test_problem_scan_is_reused_until_the_library_changes(client, lib, monkeypatch):
    from beetsplug.webui.routes import maintenance

    scans = []
    real = maintenance.scan_library
    monkeypatch.setattr(maintenance, "scan_library", lambda lib: scans.append(1) or real(lib))
    maintenance._forget_scan()

    for _ in range(3):
        client.get("/api/albums", params={"problem": "any"})
    client.get("/api/library/health")
    assert len(scans) == 1

    album = lib.albums().get()
    album.label = "Changed"
    album.store()
    client.get("/api/library/health")
    assert len(scans) == 2


def two_disc_album(lib, numbering, drop=()):
    """A 2x3 album numbered across the release (1-6, total 6) or per disc (1-3, total 3)."""
    items = []
    for disc in (1, 2):
        for n in (1, 2, 3):
            across = (disc - 1) * 3 + n
            if across in drop:
                continue
            track, total = (across, 6) if numbering == "across" else (n, 3)
            items.append(
                Item(
                    title=f"T{across}",
                    album="Double",
                    albumartist="X",
                    disc=disc,
                    track=track,
                    tracktotal=total,
                    path=f"/x/{across}.flac".encode(),
                )
            )
    return lib.add_album(items)


def missing_detail(client, album):
    problems = {p["id"]: p for p in client.get(f"/api/albums/{album.id}").json()["problems"]}
    return problems.get("missing_tracks", {}).get("detail")


def test_complete_two_disc_albums_miss_nothing(client, lib):
    for numbering in ("across", "per disc"):
        assert missing_detail(client, two_disc_album(lib, numbering)) is None


def test_two_disc_albums_name_what_is_missing(client, lib):
    across = two_disc_album(lib, "across", drop={5})
    assert missing_detail(client, across) == "Missing track 5, going by the track totals."
    per_disc = two_disc_album(lib, "per disc", drop={5})
    assert missing_detail(client, per_disc) == (
        "Missing track 2 of disc 2, going by the track totals."
    )


def test_a_scan_overtaken_by_a_change_is_not_kept(client, lib, monkeypatch):
    from beetsplug.webui.routes import maintenance

    maintenance._forget_scan()
    real = maintenance.scan_library
    scans = []

    def scan_while_editing(lib):
        scans.append(1)
        result = real(lib)
        if len(scans) == 1:
            album = lib.albums().get()
            album.label = "Changed mid-scan"
            album.store()
        return result

    monkeypatch.setattr(maintenance, "scan_library", scan_while_editing)
    client.get("/api/library/health")
    client.get("/api/library/health")
    assert len(scans) == 2  # the first result was stale, so it wasn't reused


def test_album_page_sees_duplicates_beyond_ascii(client, lib):
    first = lib.add_album([Item(title="a", albumartist="Björk", album="Homogenic", path=b"/b1")])
    second = lib.add_album([Item(title="a", albumartist="BJÖRK", album="Homogenic", path=b"/b2")])
    problems = {p["id"]: p for p in client.get(f"/api/albums/{first.id}").json()["problems"]}
    assert [a["id"] for a in problems["duplicates"]["others"]] == [second.id]


def test_imports_wait_for_a_library_update(client):
    from beetsplug.webui.routes.common import update_lock

    with update_lock:
        res = client.post("/api/imports", json={"album_id": 1})
    assert res.status_code == 409


def test_album_tracks_come_in_album_order(client, lib):
    items = [
        Item(title=title, artist=artist, album="Wait for Me", track=n, path=f"/m/{n}.flac".encode())
        for n, title, artist in [
            (1, "On Air", "Moby"),
            (2, "Feelings Come Undone", "Moby feat. Raquel Rodriguez"),
            (3, "Medusa", "Moby"),
        ]
    ]
    album = lib.add_album(items)
    tracks = client.get(f"/api/albums/{album.id}").json()["items"]
    assert [t["track"] for t in tracks] == [1, 2, 3]
