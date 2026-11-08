# beets-webui

A web UI for [beets](https://beets.io): browse and search your library, edit tags, and run
interactive imports from the browser.

It ships as a beets plugin, so it uses your existing config, library and plugins exactly as the
`beet` CLI does.

## Usage

It isn't on PyPI. Install the wheel from a [GitHub release](https://github.com/vinzdef/beets-webui/releases)
into the same environment as beets:

```sh
pip install https://github.com/vinzdef/beets-webui/releases/download/v2.14.15/beets_webui-2.14.15-py3-none-any.whl

# if beets was installed with pipx:
pipx inject beets https://github.com/vinzdef/beets-webui/releases/download/v2.14.15/beets_webui-2.14.15-py3-none-any.whl
```

Pick the release matching your beets version: `2.14.N` works with beets 2.14 (see
[Versioning](#versioning)). It installs beets 2.14 if it isn't there already.

`pip install git+https://github.com/vinzdef/beets-webui` also works, but installs without the web
pages: the compiled frontend isn't in git, only in the release wheels. To install from a checkout
instead, build the frontend first:

```sh
git clone https://github.com/vinzdef/beets-webui && cd beets-webui
(cd frontend && pnpm install && pnpm build)
pip install .
```

Add it to your beets config (`beet config -e`):

```yaml
plugins: webui   # alongside your other plugins

webui:
  host: 127.0.0.1
  port: 8338
  inboxes:                 # named folders the UI may import from
    Downloads: ~/Downloads/music
    Vinyl rips: /mnt/rips
```

Imports are refused for paths outside these folders.

Then run `beet webui` (or `beet webui 0.0.0.0 8080` to override host/port).

For a fuller setup (cover art embedding, Last.fm genres, tag and filename cleanup) start from
[`examples/config.template.yaml`](examples/config.template.yaml).

### Without Docker

`examples/local/` is a ready-made beets setup with its own config, inbox and library folder:

```sh
(cd frontend && pnpm install && pnpm build)
BEETSDIR=examples/local uv run beet webui       # http://127.0.0.1:8338
```

`BEETSDIR` points beets at that folder instead of `~/.config/beets`, so your real library isn't
touched. Put albums in `examples/local/inbox/`. If the Docker example is already using port 8338,
pass another one: `beet webui 127.0.0.1 8339`.

### Docker

An example setup lives in `examples/docker/`:

```sh
cd examples/docker
docker compose up -d --build     # http://127.0.0.1:8338, restarts automatically
```

It's a self-contained test environment:

- `config/config.yaml`: beets config with the MusicBrainz autotagger, fetchart, mbsync, ftintitle
  and the web UI. The library database and logs are written next to it.
- `inbox/`: put music to import here. It's the inbox named "Inbox" in the config; add more by
  mounting folders in `compose.yaml` and naming them under `webui.inboxes`.
- `music/`: the beets library folder. Imports *copy* from the inbox, so you can wipe `music/` and
  `config/library.db` and import the same files again.

To get albums to test with, generate silent ones tagged from MusicBrainz (an exact match, a
missing track, messy tags, an untagged album and loose tracks; about 55 MB):

```sh
uv run python scripts/make_test_albums.py examples/docker/inbox
```

Only the config and empty-folder placeholders are committed; everything else in those folders is
gitignored. To import from the command line until the UI can do it:

```sh
docker compose exec beets-webui beet import /inbox      # interactive, matches against MusicBrainz
```

To use a real library instead, set `BEETS_CONFIG_DIR`, `MUSIC_DIR` and `INBOX_DIR` (and the port
with `WEBUI_PORT`), e.g. in a `.env` file in `examples/docker/`. If `config.yaml` doesn't exist
in the config dir, a minimal one is created. If you bring your own, list `musicbrainz` and `webui`
in `plugins` (setting `plugins` replaces beets' default of `[musicbrainz]`), and use the container
paths for `directory` and `library` (`/music`, `/config/library.db`).

The port is published on the host's loopback only, because there's no authentication yet.

### Published image

```yaml
services:
  beets-webui:
    image: ghcr.io/vinzdef/beets-webui:2.14   # newest release for beets 2.14
```

Tags: `2.14.N` (one release), `2.14` (newest release for beets 2.14), `latest`, and `edge` (the
current `main`). `docker inspect` shows the exact beets version in the `io.beets.version` label.

### Installing as an app

The web UI is a progressive web app: Chrome, Edge and Android offer to install it (the install
icon in the address bar, or *Add to Home screen*), and Safari can *Add to Dock* or *Add to Home
Screen*. It then opens in its own window with its own icon.

Browsers only allow this on a secure origin: `http://localhost` / `http://127.0.0.1`, or HTTPS.
To install it from another device, put it behind a reverse proxy with a certificate (Caddy,
Traefik, `tailscale serve`, …). Plain `http://192.168.x.x:8338` works in the browser but can't
be installed.

## Versioning

Versions follow the beets release they work with: `<beets major>.<beets minor>.<release>`, so
every `2.14.N` works with beets 2.14, and support for beets 2.15 starts at `2.15.0`. The beets
requirement in `pyproject.toml` is pinned to match.

To release, bump `version` in `pyproject.toml`, commit, and push a matching tag:

```sh
git tag v2.14.1 && git push origin v2.14.1
```

Two workflows run for the tag, and both refuse to publish if the tag, the version and the beets
version disagree (`scripts/check_version.py`):

- **Docker image** installs the beets version locked in `uv.lock` and publishes
  `ghcr.io/vinzdef/beets-webui` for amd64 and arm64.
- **Release** builds the wheel with the web UI inside and attaches it to a GitHub release. For a
  tag pushed before this workflow existed, run it from the Actions tab with that tag.

Update the install URLs in this README to the new version when releasing.

## Development

Requires [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/).

```sh
git config core.hooksPath .githooks      # refuse commits containing music or library files
uv sync                                  # Python deps into .venv
cd frontend && pnpm install && cd ..

uv run beet webui                        # API on :8338 (uses your real beets config)
cd frontend && pnpm dev                  # UI on :5173, proxies /api to :8338
```

Point `BEETSDIR` at a scratch directory to avoid touching your real library while developing.

Checks:

```sh
uv run ruff check && uv run ruff format --check && uv run pytest
cd frontend && pnpm lint && pnpm check && pnpm build
```

`pnpm build` writes the SPA into `src/beetsplug/webui/static/`, which the plugin serves.

## Layout

```
src/beetsplug/webui/     beets plugin + FastAPI app
  __init__.py            WebUIPlugin, `beet webui` command
  app.py                 create_app(lib): routers + SPA static serving
  routes/                API routers (/api/...)
frontend/                SvelteKit (static adapter, SPA mode)
tests/                   pytest against a temporary Library
docker/                  image entrypoint + default config
examples/docker/         compose test environment (config, inbox, music)
examples/local/          the same without Docker (BEETSDIR=examples/local)
```

## Roadmap

- [x] Browse/search albums and items using beets query syntax
- [x] Artists view lists each artist's tracks on no album under their albums; the songs view sorts
      by track, title, artist, album or bitrate and filters to tracks on no album (or on one)
- [x] Artist pages: their albums, albums they appear on, and their tracks on no album
- [x] The library loads more as you scroll; covers in grids are small cached thumbnails
- [x] Edit an album's metadata from its page, mirroring `beet modify` (`PATCH /api/albums/{id}`)
- [x] Song pages: edit a track (and re-import a single track); bulk edits on selected albums or songs
- [x] Album art: fetch (fetchart), upload, save a folder image or embedded art as the art file, embed
- [x] Refresh an album or single track from MusicBrainz (with the `mbsync` plugin)
- [x] Move "feat." from track artists into titles, after approving each change (with `ftintitle`)
- [x] Library health: missing files and tracks, no cover, unmatched albums, duplicates
- [x] Re-import an album already in the library to match it again (`beet import -L`)
- [x] Delete an album, with or without its files (`beet remove -a [-d]`), after confirming
- [x] Installable as a PWA
- [x] Imports from named inbox folders, with live progress
- [x] Interactive matching with the CLI's choices: apply a candidate, skip, as-is, as tracks, group
      albums, rescan, search by name or ID, plugin choices, duplicates, resume; see
      [docs/interactive-import.md](docs/interactive-import.md)
- [x] Enter an album's tags by hand on the match screen, when no release fits (like the `edit`
      plugin's import choice)
- [ ] Forward plugin terminal prompts (`badfiles`, …) to the browser
- [ ] Security: Host validation and authentication before binding to `0.0.0.0`
      (cross-origin writes are already refused)

beets is pinned to 2.14.x because the importer API changes between minor releases.
