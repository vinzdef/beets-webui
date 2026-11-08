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
