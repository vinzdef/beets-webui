from beets.library import Item


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_list_albums(client):
    body = client.get("/api/albums").json()
    assert body["total"] == 1
    assert body["results"][0]["album"] == "OK Computer"


def test_album_detail_includes_items(client):
    album_id = client.get("/api/albums").json()["results"][0]["id"]
    body = client.get(f"/api/albums/{album_id}").json()
    assert [i["track"] for i in body["items"]] == [1, 2, 3]
    assert body["items"][0]["path"] == "/music/ok-computer/01.flac"


def test_item_query(client):
    body = client.get("/api/items", params={"q": "artist:portishead"}).json()
    assert body["total"] == 1
    assert body["results"][0]["title"] == "Loose Track"


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
