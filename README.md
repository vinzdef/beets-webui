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
```

Then run `beet webui` (or `beet webui 0.0.0.0 8080` to override host/port).

### Docker

```sh
docker compose up -d --build     # http://127.0.0.1:8338, restarts automatically
```

By default the config, music and import inbox live in `./data/`. Override them with
`BEETS_CONFIG_DIR`, `MUSIC_DIR` and `INBOX_DIR` (and the port with `WEBUI_PORT`), e.g. in a `.env`
file next to `compose.yaml`. If `config.yaml` doesn't exist in the config dir, a minimal one is
created; if you bring your own, make sure `webui` is listed in `plugins` and that `directory` and
`library` use the container paths (`/music`, `/config/library.db`).

The port is published on the host's loopback only, because there's no authentication yet.

## Development

Requires [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/).

```sh
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
tests/                   pytest against an in-memory Library
docker/                  entrypoint + default config
```

## Roadmap

- [x] Browse/search albums and items using beets query syntax
- [ ] Edit metadata: `PATCH /api/items/{id}` and `/api/albums/{id}`, then `item.try_sync(write, move)`
      to mirror `beet modify`, with bulk edits over a query
- [ ] Imports: start `beet import` jobs on a path and stream their progress
- [ ] Interactive imports with the same choices as the CLI; see
      [docs/interactive-import.md](docs/interactive-import.md)
- [ ] Security before any write endpoint: CSRF/Origin checks, Host validation, auth for `0.0.0.0`

beets is pinned to 2.14.x because the importer API changes between minor releases.
