import pytest
from beets.library import Item, Library
from fastapi.testclient import TestClient

from beetsplug.webui.app import create_app


@pytest.fixture(autouse=True)
def isolated_beetsdir(tmp_path, monkeypatch):
    # Keep tests away from the developer's real beets config and library.
    monkeypatch.setenv("BEETSDIR", str(tmp_path / "beets"))


@pytest.fixture
def lib(tmp_path):
    # Not ":memory:": beets opens one connection per thread and FastAPI serves sync
    # endpoints from a thread pool, so each thread would see its own empty database.
    lib = Library(str(tmp_path / "library.db"))
    items = [
        Item(title=f"Track {n}", artist="Radiohead", album="OK Computer", track=n, year=1997)
        for n in range(1, 4)
    ]
    for item in items:
        item.path = f"/music/ok-computer/{item.track:02d}.flac".encode()
    lib.add_album(items)
    lib.add(Item(title="Loose Track", artist="Portishead", path=b"/music/loose.mp3"))
    yield lib
    lib._close()


@pytest.fixture
def client(lib):
    return TestClient(create_app(lib))
