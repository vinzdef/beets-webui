# Interactive import design

Implemented in `src/beetsplug/webui/imports.py` (session and job) and `routes/imports.py` (API).
Still open: forwarding terminal prompts from plugins, blocking edits to items in an active import,
Host validation and authentication.

API: `GET /api/inboxes`, `POST /api/imports`, `GET /api/imports/current`, server-sent events at
`GET /api/imports/current/events` (the full job state on every change), and
`POST /api/imports/current/answer` / `abort`.

Goal: the choices `beet import` offers at the terminal, made from the browser. Verified against
beets 2.14.1; the importer API changes between minor releases, so beets is pinned to `>=2.14,<2.15`.

## Session

A `WebImportSession(beets.importer.ImportSession)` runs `session.run()` in a worker thread. Each
decision hook publishes a question over a WebSocket and blocks on a `queue.Queue` for the answer.
Blocking is fine: with `threaded: yes` every pipeline stage has its own thread, so candidate lookup
for later albums keeps running while one waits — the same as the CLI.

Hooks to implement (`beets/importer/session.py`):

| Hook | Returns |
| --- | --- |
| `choose_match(task)` | an `AlbumMatch` or an `Action` |
| `choose_item(task)` | a `TrackMatch` or an `Action` (singletons and the as-Tracks flow) |
| `get_duplicate_action(task, found_duplicates)` | a `DuplicateAction`: `SKIP`, `MERGE`, `REMOVE`, `KEEP` or `UPGRADE` — never `ASK`, which means "prompt the user" |
| `should_resume(path)` | `bool` |

`Action` is `beets.importer.Action`: `SKIP`, `ASIS`, `TRACKS`, `APPLY`, `ALBUMS`, `RESCAN`
(re-read the directory and match again) and `RETAG` (plugin-only).

`MERGE` builds a new combined task that goes through lookup and `choose_match` again, so the UI
must expect to be asked about the same album twice.

### Before prompting

Replicate what the CLI session does (`beets/ui/commands/import_/session.py`):

- Send `import_task_before_choice`; a plugin may return an action, and more than one doing so is
  an error.
- Apply the automatic decision for strong matches and the `quiet` / `timid` / `quiet_fallback`
  settings. The CLI does this in the private `_summary_judgment`; copy it rather than import it.

### Searching again

`autotag.tag_album(task.source, search_artist=, search_name=, search_ids=)` (and `tag_item`)
return a `Proposal(candidates, recommendation)`. Store both on the task, as the CLI does, then ask
again.

### Plugin choices

`before_choose_candidate` returns `PromptChoice(short, long, callback)`. Render one generic button
each. A callback returns an `Action`, a `Proposal` (new candidates) or `None`.

### Plugins that prompt at the terminal

`badfiles` (`input_options` in `import_task_before_choice`), `edit` (opens an editor) and `play`
read stdin; in Docker there is none, so they fail or hang. While a session runs, replace
`beets.ui.input_` and `beets.ui.input_options` with functions that forward the question to the
browser. That covers current and future plugin prompts in one place; `edit` and `play` still need
a block-list.

### Aborting and shutdown

Raise `beets.importer.ImportAbortError` from a blocked hook to stop the session. It must be that
class (defined in `importer/session.py`): `importer/tasks.py` defines a second, unrelated
`ImportAbortError` that `run()` does not catch. Release every blocked hook this way on server
shutdown, or the process hangs waiting for pipeline threads.

## Modes

An import is started in one of three modes (`mode` in `POST /api/imports`):

- `auto`: beets' normal behaviour. Matches above the configured strong-match threshold
  (`match.strong_rec_thresh`, 96% by default) are applied unasked.
- `manual`: only perfect matches (100%) are applied unasked. The session sets
  `match.strong_rec_thresh` just above zero; beets counts a match as strong when its distance is
  *below* the threshold, so only a distance of 0 qualifies.
- `timid`: every match is shown for approval.

Every mode sets `import.timid` explicitly, so the beets config can't change what the UI shows.
Without a mode the beets config decides.

## Global state

Per-import options (`quiet`, `timid`, `search_ids`, `copy` / `move`, …) live in the global
`config["import"]`, so:

- run one session at a time;
- snapshot the import config before a session and restore it afterwards.

Options to expose: `group_albums`, `singletons`, `incremental` and `incremental_skip_later`,
`from_scratch`, `search_ids`, `set_fields`, `pretend`, resume, and `-L` (re-import a library
query via `session.query`).

## Concurrency with edits

dbcore uses one connection per thread and a global lock around each transaction (5 s timeout), so
concurrent reads and writes are safe. Editing an item while the import is still applying metadata
to it can lose changes, though: reject edits to items in the active session.

## Security (before any write endpoint ships)

- Restrict import paths to the configured inboxes (`webui.inboxes`, name → folder). Done.
- Require a token or check `Origin` on every write and on the WebSocket (CSRF / cross-site
  WebSocket hijacking).
- Validate `Host` to block DNS rebinding against the localhost default.
- Add authentication before supporting `0.0.0.0`.

## Testing

Build a real session against a fake metadata source plugin and drive it through the hooks, so a
beets upgrade that changes the importer API fails in CI instead of at runtime.
