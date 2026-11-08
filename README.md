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
docker build -t beets-webui .
docker run -p 8338:8338 -v ~/.config/beets:/config -v ~/Music:/music beets-webui
```

If `/config/config.yaml` doesn't exist, a minimal one is created. Make sure `webui` is listed in
`plugins`.

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
- [ ] Interactive imports. Plan: subclass `beets.importer.ImportSession` and implement
      `choose_match` / `choose_item` / `resolve_duplicate` / `should_resume`. The session runs in
      a worker thread. Each decision point publishes the task and its candidates (with distance
      and penalties) over a WebSocket, then blocks on a queue until the browser replies. This
      gives the same choices as the CLI: apply, skip, as-is, search by ID or name, and
      merge/keep/remove duplicates.
