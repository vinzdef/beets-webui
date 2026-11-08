import time
from pathlib import Path

import pytest
from beets.autotag import AlbumInfo, TrackInfo
from beets.library import Library
from beets.test.helper import AutotagStub, ConfigMixin
from fastapi.testclient import TestClient
from mediafile import MediaFile

from beetsplug.webui.app import create_app

# One frame of silent MPEG-1 Layer III (128 kbps, 44.1 kHz); enough for mediafile to tag.
MP3_FRAME = bytes([0xFF, 0xFB, 0x90, 0x64]) + bytes(413)


def make_album(directory: Path, tracks: int = 2) -> Path:
    directory.mkdir(parents=True)
    for n in range(1, tracks + 1):
        path = directory / f"{n:02d}.mp3"
        path.write_bytes(MP3_FRAME * 40)
        media = MediaFile(path)
        media.update(
            {"artist": "Tag Artist", "album": "Tag Album", "title": f"Tag Track {n}", "track": n}
        )
        media.save()
    return directory


@pytest.fixture
def config(tmp_path):
    config = ConfigMixin().config
    config["directory"] = str(tmp_path / "library")
    config["threaded"] = True  # the web session must cope with real pipeline threads
    config["import"].set({"copy": True, "write": True, "resume": False, "timid": True})
    config["webui"]["inboxes"] = {
        "Downloads": str(tmp_path / "inbox"),
        "Rips": str(tmp_path / "rips"),
    }
    return config


@pytest.fixture
def matcher(request):
    stub = AutotagStub(getattr(request, "param", AutotagStub.GOOD)).install()
    yield stub
    stub.restore()


@pytest.fixture
def lib(tmp_path, config):
    lib = Library(str(tmp_path / "library.db"), str(tmp_path / "library"))
    yield lib
    lib._close()


@pytest.fixture
def client(lib, matcher):
    with TestClient(create_app(lib)) as client:
        yield client


@pytest.fixture
def album(tmp_path):
    return make_album(tmp_path / "inbox" / "Tag Album")


def wait_for(client, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get("/api/imports/current").json()
        if state and predicate(state):
            return state
        time.sleep(0.02)
    raise AssertionError(f"timed out; last state: {state}")


def question(client, kind="match"):
    state = wait_for(client, lambda s: s["question"] or s["status"] not in ("running",))
    assert state["question"] and state["question"]["kind"] == kind, state
    return state["question"]


def finished(client):
    return wait_for(client, lambda s: s["status"] not in ("running", "waiting"))


def answer(client, q, **body):
    response = client.post("/api/imports/current/answer", json={"question": q["id"], **body})
    assert response.status_code == 200, response.json()


def test_lists_named_inboxes_in_config_order(client, album, tmp_path):
    make_album(tmp_path / "rips" / "Rip")

    inboxes = client.get("/api/inboxes").json()["inboxes"]

    assert [i["name"] for i in inboxes] == ["Downloads", "Rips"]
    assert [e["name"] for e in inboxes[0]["entries"]] == ["Tag Album"]
    assert inboxes[0]["entries"][0]["is_dir"]
    assert [e["name"] for e in inboxes[1]["entries"]] == ["Rip"]


def test_imports_from_any_inbox(client, lib, tmp_path):
    rip = make_album(tmp_path / "rips" / "Rip")
    client.post("/api/imports", json={"paths": [str(rip)]}).raise_for_status()
    answer(client, question(client), type="apply", candidate=0)

    assert finished(client)["status"] == "done"
    assert len(lib.albums()) == 1


def test_missing_inbox_folder_is_reported(client):
    inboxes = client.get("/api/inboxes").json()["inboxes"]
    assert inboxes[1] == {
        "name": "Rips",
        "path": inboxes[1]["path"],
        "exists": False,
        "entries": [],
    }


def test_inboxes_must_be_a_mapping(client, config):
    config["webui"]["inboxes"] = ["/somewhere"]
    response = client.get("/api/inboxes")
    assert response.status_code == 500
    assert "mapping" in response.json()["detail"]


def test_refuses_paths_outside_inbox(client, tmp_path):
    outside = make_album(tmp_path / "elsewhere")
    response = client.post("/api/imports", json={"paths": [str(outside)]})
    assert response.status_code == 400


def test_refuses_cross_origin_requests(client, album):
    response = client.post(
        "/api/imports", json={"paths": [str(album)]}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_apply_candidate(client, lib, album):
    client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()

    q = question(client)
    assert q["task"]["name"] == "Tag Album"
    assert len(q["task"]["items"]) == 2
    first = q["candidates"][0]
    assert first["name"] == "Applied Album"
    assert [t["track"]["title"] for t in first["tracks"]] == ["Applied Track 1", "Applied Track 2"]
    assert {"s", "u", "t", "g", "b"} <= {c["short"] for c in q["choices"]}

    answer(client, q, type="apply", candidate=0)
    state = finished(client)

    assert state["status"] == "done", state
    assert [a.album for a in lib.albums()] == ["Applied Album"]
    assert any(e["kind"] == "imported" for e in state["log"])


def test_skip(client, lib, album):
    client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()
    answer(client, question(client), type="choice", short="s")

    assert finished(client)["status"] == "done"
    assert len(lib.albums()) == 0


def test_search_asks_again_with_new_candidates(client, album):
    client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()
    q = question(client)
    answer(client, q, type="search", artist="Other Artist", name="Other Album")

    q2 = wait_for(client, lambda s: s["question"] and s["question"]["id"] != q["id"])["question"]
    assert q2["candidates"][0]["name"] == "Other Album"
    client.post("/api/imports/current/abort").raise_for_status()


def test_abort_releases_waiting_session(client, lib, album):
    client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()
    question(client)

    client.post("/api/imports/current/abort").raise_for_status()

    assert finished(client)["status"] == "aborted"
    assert len(lib.albums()) == 0


def test_only_one_import_at_a_time(client, album):
    client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()
    question(client)

    assert client.post("/api/imports", json={"paths": [str(album)]}).status_code == 409
    client.post("/api/imports/current/abort").raise_for_status()


def test_rejects_invalid_answers(client, album):
    client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()
    q = question(client)

    url = "/api/imports/current/answer"
    assert (
        client.post(url, json={"question": q["id"], "type": "apply", "candidate": 99}).status_code
        == 400
    )
    assert (
        client.post(url, json={"question": q["id"], "type": "choice", "short": "z"}).status_code
        == 400
    )
    assert (
        client.post(url, json={"question": q["id"] + 1, "type": "choice", "short": "s"}).status_code
        == 409
    )
    client.post("/api/imports/current/abort").raise_for_status()


def test_duplicate_question(client, lib, album, config):
    config["import"]["duplicate_action"] = "ask"
    for _ in range(2):
        client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()
        answer(client, question(client), type="apply", candidate=0)
        state = wait_for(
            client,
            lambda s: s["status"] == "done" or (s["question"] or {}).get("kind") == "duplicate",
        )
    q = state["question"]
    assert q["existing"][0]["description"] == "Applied Artist - Applied Album"
    assert "k" in {o["value"] for o in q["options"]}

    answer(client, q, type="duplicate", action="s")
    assert finished(client)["status"] == "done"
    assert len(lib.albums()) == 1


def test_import_options_do_not_leak_into_global_config(client, album, config):
    client.post("/api/imports", json={"paths": [str(album)], "singletons": True}).raise_for_status()
    assert question(client)["task"]["kind"] == "track"
    answer(client, question(client), type="choice", short="b")
    finished(client)

    assert config["import"]["singletons"].get() is False
    assert config["import"]["timid"].get() is True  # the test config's value, untouched by the job


def test_unset_options_keep_config_values(client, album):
    # timid is on in the test config; without it a strong match would be applied unasked.
    client.post("/api/imports", json={"paths": [str(album)]}).raise_for_status()
    assert client.get("/api/imports/current").json()["options"] == {}
    answer(client, question(client), type="choice", short="b")


def stub_candidate(matcher, monkeypatch, album_name):
    """Make the stub return one candidate matching the fixture files except for its album name."""

    def candidates(items, artist, album, va_likely):
        tracks = [
            TrackInfo(
                title=f"Tag Track {n}",
                track_id=f"t{n}",
                artist="Tag Artist",
                length=1.0425,
                index=n,
                medium=1,
                medium_index=n,
                medium_total=len(items),
            )
            for n in range(1, len(items) + 1)
        ]
        yield AlbumInfo(
            tracks=tracks,
            artist="Tag Artist",
            album=album_name,
            album_id="x",
            artist_id="a",
            va=False,
            mediums=1,
        )

    monkeypatch.setattr("beets.metadata_plugins.candidates", candidates)


@pytest.mark.parametrize(
    ("album_name", "exact_only", "asked"),
    [
        ("Tag Album", False, False),  # perfect match: applied unasked
        ("Tag Album", True, False),  # ...in either mode
        ("Tag Albun", False, False),  # strong but imperfect: beets applies it unasked
        ("Tag Albun", True, True),  # ...but exact-only mode asks
    ],
)
def test_exact_only(
    client, lib, album, matcher, monkeypatch, config, album_name, exact_only, asked
):
    stub_candidate(matcher, monkeypatch, album_name)
    body = {"paths": [str(album)], "timid": False, "exact_only": exact_only}
    client.post("/api/imports", json=body).raise_for_status()
    state = wait_for(client, lambda s: s["question"] or s["status"] == "done")

    assert bool(state["question"]) == asked, state
    if asked:
        assert 0 < state["question"]["candidates"][0]["distance"] < 0.04
        client.post("/api/imports/current/abort").raise_for_status()
    else:
        assert [a.album for a in lib.albums()] == [album_name]
    finished(client)
    assert config["match"]["strong_rec_thresh"].as_number() == 0.04  # restored after the import
