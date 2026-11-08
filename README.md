# beets-webui

A web UI for [beets](https://beets.io): browse and search your library, edit tags, and run
interactive imports from the browser.

It ships as a beets plugin, so it uses your existing config, library and plugins exactly as the
`beet` CLI does.

## Usage

```sh
pip install beets-webui
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

- `config/config.yaml`: beets config with the MusicBrainz autotagger, fetchart and the web UI.
  The library database and logs are written next to it.
- `inbox/`: put music to import here. It's the inbox named "Inbox" in the config; add more by
  mounting folders in `compose.yaml` and naming them under `webui.inboxes`.
- `music/`: the beets library folder. Imports *copy* from the inbox, so you can wipe `music/` and
  `config/library.db` and import the same files again.

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
- [ ] Edit metadata: `PATCH /api/items/{id}` and `/api/albums/{id}`, then `item.try_sync(write, move)`
      to mirror `beet modify`, with bulk edits over a query
- [x] Imports from named inbox folders, with live progress
- [x] Interactive matching with the CLI's choices: apply a candidate, skip, as-is, as tracks, group
      albums, rescan, search by name or ID, plugin choices, duplicates, resume; see
      [docs/interactive-import.md](docs/interactive-import.md)
- [ ] Forward plugin terminal prompts (`badfiles`, …) to the browser
- [ ] Security: Host validation and authentication before binding to `0.0.0.0`
      (cross-origin writes are already refused)

beets is pinned to 2.14.x because the importer API changes between minor releases.
