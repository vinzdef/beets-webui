"""Running beets imports from the browser.

An `ImportJob` runs a `WebImportSession` in a worker thread. Whenever beets needs a decision
(which candidate to apply, what to do with a duplicate, whether to resume), the session publishes a
question on the job and blocks until the browser answers it. See docs/interactive-import.md.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import uuid
from array import array
from collections import Counter
from collections.abc import Callable
from typing import Any

from beets import config, metadata_plugins, plugins
from beets.autotag import AlbumMatch, Proposal, Recommendation, TrackMatch, tag_album, tag_item
from beets.importer import (
    Action,
    DuplicateAction,
    ImportAbortError,
    ImportSession,
    ImportTask,
    SingletonImportTask,
)
from beets.library import Album, Item, Library
from beets.plugins import BeetsPlugin
from beets.ui.commands.import_.session import summarize_items
from beets.util import PromptChoice, displayable_path, syspath

log = logging.getLogger("beets")

# Entries the import page shows for the current job; the history file keeps all of them.
LOG_LIMIT = 500
# Short letters the built-in prompt uses for things that aren't PromptChoices here.
RESERVED_SHORTS = {"a", "e", "i", "m"}
# Tags entered by hand on the match screen, in place of a release's: the album's, set on each of
# its files, and each file's own.
MANUAL_ALBUM_FIELDS = (
    "album",
    "albumartist",
    "year",
    "month",
    "day",
    "original_year",
    "genres",
    "label",
    "catalognum",
    "country",
    "albumtypes",
    "albumstatus",
    "albumdisambig",
    "media",
    "barcode",
    "language",
    "script",
    "comp",
)
MANUAL_ITEM_FIELDS = ("disc", "track", "title", "artist")
# Cleared from files tagged by hand, so that nothing (`beet mbsync`, the album page's refresh)
# applies the release they came from over the tags entered.
RELEASE_ID_FIELDS = (
    "mb_albumid",
    "mb_releasegroupid",
    "mb_trackid",
    "mb_releasetrackid",
    "discogs_albumid",
)


class ImportHistory:
    """Every import's log, one JSON object per line, kept across jobs and restarts."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        # Where each entry's line starts, oldest first, and how far into the file they go: the
        # file only grows, so each read indexes just what was appended since, and only the
        # entries asked for are parsed. Offsets, not entries, so memory stays small.
        self._offsets = array("q")
        self._read_to = 0

    def append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, default=str)
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                log.exception("couldn't write the web UI's import log")

    def read(self, offset: int, limit: int) -> tuple[int, list[dict[str, Any]]]:
        """Entries newest first: the total, and those from `offset` on."""
        with self._lock:
            try:
                size = os.path.getsize(self.path)
            except FileNotFoundError:
                size = 0
            if size < self._read_to:  # replaced or emptied: start over
                self._offsets, self._read_to = array("q"), 0
            if size > self._read_to:
                with open(self.path, "rb") as f:
                    f.seek(self._read_to)
                    position = self._read_to
                    # Full lines only; one still being written is indexed next time.
                    for line in f:
                        if not line.endswith(b"\n"):
                            break
                        if line.strip().startswith(b"{"):  # skip blank or cut-short lines
                            self._offsets.append(position)
                        position += len(line)
                    self._read_to = position
            total = len(self._offsets)
            wanted = self._offsets[max(total - offset - limit, 0) : max(total - offset, 0)]
            entries = []
            if wanted:
                with open(self.path, "rb") as f:
                    for start in reversed(wanted):
                        f.seek(start)
                        try:
                            entries.append(json.loads(f.readline()))
                        except ValueError:
                            continue  # a line cut short by a crash
        return total, entries


class ImportBusyError(Exception):
    """Raised when an import is started while another one is still running."""


class ImportJob:
    def __init__(
        self,
        lib: Library,
        paths: list[str],
        options: dict[str, Any],
        on_change: Callable[[], None],
        query: str | None = None,
        history: ImportHistory | None = None,
    ):
        self.id = uuid.uuid4().hex[:12]
        self.paths = paths
        # A library query re-imports albums already in the library (`beet import -L`), in place.
        self.query = query
        self.options = options
        self.status = "running"  # running | waiting | done | aborted | failed
        self.error: str | None = None
        self.started = time.time()
        self.finished: float | None = None
        self.log: list[dict[str, Any]] = []
        self.question: dict[str, Any] | None = None

        self._on_change = on_change
        self._history = history
        self._cond = threading.Condition()
        # Questions can come from different pipeline stages; ask them one at a time.
        self._ask_lock = threading.Lock()
        self._answer: dict[str, Any] | None = None
        self._next_question = 1
        self._aborted = False
        self._lib = lib
        # Run in a copy of the starting request's context: beets keeps the library folder, which
        # its relative item paths resolve against, in a context variable.
        ctx = contextvars.copy_context()
        self._thread = threading.Thread(
            target=ctx.run, args=(self._run,), name="webui-import", daemon=True
        )

    @property
    def active(self) -> bool:
        return self.status in ("running", "waiting")

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def snapshot(self) -> dict[str, Any]:
        with self._cond:
            return {
                "status": self.status,
                "paths": self.paths,
                "reimport": self.query is not None,
                "options": self.options,
                "error": self.error,
                "started": self.started,
                "finished": self.finished,
                "question": self.question,
                "log": self.log[-LOG_LIMIT:],
            }

    def event(self, kind: str, message: str, **data: Any) -> None:
        entry = {"time": time.time(), "kind": kind, "message": message, **data}
        with self._cond:
            self.log.append(entry)
        if self._history is not None:
            self._history.append({"job": self.id, **entry})
        self._on_change()

    # Questions and answers

    def ask(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Publish a question and block the calling pipeline thread until it's answered."""
        with self._ask_lock, self._cond:
            self._raise_if_aborted()
            self.question = {"id": self._next_question, "kind": kind, **data}
            self._next_question += 1
            self._answer = None
            self.status = "waiting"
            self._on_change()

            while self._answer is None and not self._aborted:
                self._cond.wait()
            self._raise_if_aborted()

            answer = self._answer
            self.question = None
            self.status = "running"
        self._on_change()
        return answer

    def answer(self, question_id: int, answer: dict[str, Any]) -> None:
        with self._cond:
            if self.question is None or self.question["id"] != question_id:
                raise LookupError("no such question")
            self._answer = answer
            self._cond.notify_all()

    def abort(self) -> None:
        with self._cond:
            self._aborted = True
            self._cond.notify_all()

    def _raise_if_aborted(self) -> None:
        if self._aborted:
            # Must be the class beets.importer exports: session.run() only catches that one.
            raise ImportAbortError()

    # Worker thread

    def _run(self) -> None:
        global _running_job

        handler = _JobLogHandler(self)
        beets_log = logging.getLogger("beets")
        session: WebImportSession | None = None
        import_log: logging.Handler | None = None
        # Per-import options go into the global config; restore it afterwards.
        config["import"].flatten()
        saved_sources = list(config.sources)
        _running_job = self
        try:
            overrides = config_overrides(self.options)
            if self.query is not None:
                overrides["import"]["library"] = True
            config.set(overrides)
            paths = None if self.query is not None else [p.encode() for p in self.paths]
            import_log = _import_loghandler()
            session = WebImportSession(self, self._lib, import_log, paths, self.query)
            session.logger.addHandler(handler)
            beets_log.addHandler(handler)
            verb = "Re-importing" if self.query is not None else "Importing"
            self.event(
                "started",
                f"{verb} {', '.join(self.paths)}",
                paths=self.paths,
                reimport=self.query is not None,
            )
            session.run()
            plugins.send("import", lib=self._lib, paths=session.paths)
            status = "aborted" if self._aborted else "done"
        except ImportAbortError:
            status = "aborted"
        except Exception as exc:
            log.exception("web import failed")
            self.error = f"{type(exc).__name__}: {exc}"
            status = "failed"
        finally:
            beets_log.removeHandler(handler)
            if session is not None:
                session.logger.removeHandler(handler)
            # beets swaps the importer's handler on the next session without closing this one.
            if import_log is not None:
                if session is not None:
                    session.logger.removeHandler(import_log)
                import_log.close()
            config.sources[:] = saved_sources
            _running_job = None

        with self._cond:
            self.status = status
            self.question = None
            self.finished = time.time()
        self.event(
            status,
            {"done": "Import finished", "aborted": "Import aborted"}.get(
                status, f"Import failed: {self.error}"
            ),
        )


IMPORT_OPTIONS = {"singletons", "group_albums"}
# beets treats a match as strong (and applies it unasked) when its distance is *below* this
# threshold, so anything above zero admits only a perfect match.
EXACT_MATCH_THRESHOLD = 1e-9


def config_overrides(options: dict[str, Any]) -> dict[str, Any]:
    """Turn per-import options from the UI into beets config for the session.

    Modes: "auto" applies matches above the configured strong-match threshold unasked, "manual"
    applies only perfect (100%) matches unasked, and "timid" asks about every match. Without a
    mode, the beets config decides.
    """
    overrides: dict[str, Any] = {
        "import": {k: v for k, v in options.items() if k in IMPORT_OPTIONS}
    }
    mode = options.get("mode")
    if mode is not None:
        overrides["import"]["timid"] = mode == "timid"
    if mode == "manual":
        overrides["match"] = {"strong_rec_thresh": EXACT_MATCH_THRESHOLD}
    return overrides


class ImportManager:
    """Owns the current import job; only one runs at a time."""

    def __init__(self, lib: Library):
        self.lib = lib
        # Next to the library database, e.g. /config/webui-import-log.jsonl in the Docker image.
        self.history = ImportHistory(
            os.path.join(os.path.dirname(os.fsdecode(lib.path)), "webui-import-log.jsonl")
        )
        self.job: ImportJob | None = None
        self.version = 0
        self._cond = threading.Condition()
        _install_listeners()

    def start(
        self, paths: list[str], options: dict[str, Any], query: str | None = None
    ) -> ImportJob:
        with self._cond:
            if self.job is not None and self.job.active:
                raise ImportBusyError()
            self.job = ImportJob(self.lib, paths, options, self._changed, query, self.history)
        self.job.start()
        self._changed()
        return self.job

    def shutdown(self, timeout: float = 10) -> None:
        job = self.job
        if job is not None and job.active:
            job.abort()
            job.join(timeout)

    def _changed(self) -> None:
        with self._cond:
            self.version += 1
            self._cond.notify_all()


class WebImportSession(ImportSession):
    """An import session whose decisions are made in the browser.

    Mirrors beets' TerminalImportSession (beets/ui/commands/import_/session.py).
    """

    def __init__(self, job: ImportJob, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.job = job

    def should_resume(self, path: bytes) -> bool:
        answer = self.job.ask("resume", {"path": displayable_path(path)})
        return bool(answer.get("resume"))

    def choose_match(self, task: ImportTask) -> AlbumMatch | Action:
        return self._choose(task)

    def choose_item(self, task: SingletonImportTask) -> TrackMatch | Action:
        return self._choose(task)

    def get_duplicate_action(self, task: ImportTask, found_duplicates: list) -> DuplicateAction:
        action = super().get_duplicate_action(task, found_duplicates)
        if action is not DuplicateAction.ASK:
            return action
        if config["import"]["quiet"]:
            return DuplicateAction.SKIP

        answer = self.job.ask(
            "duplicate",
            {
                "task": serialize_task(task),
                "existing": [
                    {
                        "summary": summarize_items(
                            list(d.items()) if isinstance(d, Album) else [d], not task.is_album
                        ),
                        "description": _describe(d),
                    }
                    for d in found_duplicates
                ],
                "new": summarize_items(task.imported_items(), not task.is_album),
                "options": [
                    {"value": a.value, "label": a.text}
                    for a in DuplicateAction
                    if a is not DuplicateAction.ASK
                ],
            },
        )
        return DuplicateAction(answer["action"])

    def _choose(self, task: ImportTask) -> AlbumMatch | TrackMatch | Action:
        self.job._raise_if_aborted()
        self.job.event("task", f"Matching {_task_label(task)}", path=_task_path(task))

        results = plugins.send("import_task_before_choice", session=self, task=task)
        actions = [a for a in results if a]
        if len(actions) > 1:
            raise plugins.PluginConflictError(
                "Only one handler for `import_task_before_choice` may return an action."
            )
        if actions:
            return self._chose(task, actions[0], "a plugin")

        # Matches applied without asking leave out files the release doesn't have, as in beets
        # (the log says which); keeping them is a choice made on the match screen.
        action = summary_judgment(task.rec)
        if action is Action.APPLY:
            return self._chose(task, task.candidates[0], "quiet mode")
        if action is not None:
            return self._chose(task, action, "configuration")
        if task.rec == Recommendation.strong and not config["import"]["timid"]:
            return self._chose(task, task.candidates[0], "strong match")

        while True:
            choices = self._choices(task)
            answer = self.job.ask(
                "match",
                {
                    "task": serialize_task(task),
                    "recommendation": task.rec.name,
                    "candidates": [
                        serialize_candidate(i, m) for i, m in enumerate(task.candidates)
                    ],
                    "choices": [{"short": c.short, "long": c.long} for c in choices],
                    # Whether track numbers restart on each disc, or count across the release.
                    "per_disc_numbering": config["per_disc_numbering"].get(bool),
                    # The sources an ID lookup asks, like MusicBrainz or Discogs.
                    "sources": [
                        p.data_source for p in metadata_plugins.find_metadata_source_plugins()
                    ],
                },
            )

            kind = answer["type"]
            if kind == "apply":
                match, reason = task.candidates[answer["candidate"]], None
                if answer.get("mapping") is not None and isinstance(match, AlbumMatch):
                    match, reason = _remap(task, match, answer["mapping"]), "paired by hand"
                return self._chose(
                    task,
                    match,
                    reason,
                    keep_unmatched=bool(answer.get("keep_unmatched")),
                    extra_tags=answer.get("extra_tags") or {},
                )
            if kind == "choice":
                choice = next(c for c in choices if c.short == answer["short"])
                result = choice.callback(self, task)
                if isinstance(result, Action):
                    return self._chose(task, result)
                proposal = result
            elif kind == "search":
                proposal = _tag(task, answer["artist"].strip(), answer["name"].strip())
            elif kind == "id":
                proposal = _tag(task, search_ids=answer["ids"].split())
            elif kind == "manual":
                _tag_by_hand(task, answer["album"], answer["items"])
                return self._chose(task, Action.RETAG)
            else:
                raise ValueError(f"unknown answer type {kind!r}")

            if isinstance(proposal, Proposal):
                task.candidates, task.rec = proposal.candidates, proposal.recommendation

    def _chose(
        self,
        task: ImportTask,
        choice,
        reason: str | None = None,
        keep_unmatched: bool = False,
        extra_tags: dict[str, dict[str, Any]] | None = None,
    ):
        extras = choice.extra_items if isinstance(choice, AlbumMatch) else []
        if extras and keep_unmatched:
            _keep_unmatched(task, choice, extra_tags or {})
        if isinstance(choice, (AlbumMatch, TrackMatch)):
            what = f"Applying {choice.info.artist} - {choice.info.name}"
        else:
            what = {
                Action.SKIP: "Skipping",
                Action.ASIS: "Importing as-is",
                Action.RETAG: "Importing with tags entered by hand",
                Action.TRACKS: "Importing as tracks",
                Action.ALBUMS: "Grouping albums",
                Action.RESCAN: "Rescanning",
            }.get(choice, choice.name.title())
        suffix = f" ({reason})" if reason else ""
        self.job.event("choice", f"{what}: {_task_label(task)}{suffix}", path=_task_path(task))
        if extras:
            names = ", ".join(os.path.basename(displayable_path(i.path)) for i in extras)
            if keep_unmatched:
                self.job.event("choice", f"Keeping files the release doesn't have: {names}")
            else:
                # beets imports only the matched files; say so rather than drop them quietly.
                self.job.event(
                    "log",
                    f"Not imported, the release doesn't have them: {names}",
                    level="warning",
                )
        return choice

    def _choices(self, task: ImportTask) -> list[PromptChoice]:
        """Built-in prompt choices plus those plugins add, like the terminal prompt."""
        choices = [
            PromptChoice("s", "Skip", lambda s, t: Action.SKIP),
            PromptChoice("u", "Use as-is", lambda s, t: Action.ASIS),
        ]
        if task.is_album:
            choices.append(PromptChoice("t", "as Tracks", lambda s, t: Action.TRACKS))
            # Grouping only does something when the files span several albums; otherwise it
            # would just ask about the same album again. (The terminal prompt always offers it.)
            if len({_album_key(i) for i in task.items}) > 1:
                choices.append(PromptChoice("g", "Group albums", lambda s, t: Action.ALBUMS))
            if task.toppath and not task.is_grouped:
                choices.append(PromptChoice("r", "Rescan directory", lambda s, t: Action.RESCAN))
        choices.append(PromptChoice("b", "aBort", _abort))

        taken = RESERVED_SHORTS | {c.short for c in choices}
        for extra in (
            c
            for group in plugins.send("before_choose_candidate", session=self, task=task)
            for c in group
        ):
            if extra.short in taken:
                log.warning("Prompt choice '{}' removed due to a conflicting letter", extra.long)
                continue
            taken.add(extra.short)
            choices.append(extra)
        return choices


def _remap(task: ImportTask, match: AlbumMatch, pairing: dict[str, int | None]) -> AlbumMatch:
    """The same release with files paired to tracks by hand: file path -> the track's position
    on the release, or None for a file the release doesn't have. Tracks no file takes are
    missing. The distance stays beets' own, for the pairing it chose."""
    items = {displayable_path(i.path): i for i in task.items}
    tracks = match.info.tracks
    mapping = {items[path]: tracks[pos] for path, pos in pairing.items() if pos is not None}
    taken = {id(t) for t in mapping.values()}
    return AlbumMatch(
        distance=match.distance,
        info=match.info,
        mapping=mapping,
        extra_items=[i for p, i in items.items() if pairing.get(p) is None],
        extra_tracks=[t for t in tracks if id(t) not in taken],
    )


def _tag_by_hand(task: ImportTask, album: dict[str, str], items: dict[str, dict[str, str]]) -> None:
    """Tag the files as entered on the match screen: `album` on every file, `items` by path.
    Values are strings, parsed by each field's type as `beet modify` does. Importing with
    `Action.RETAG`, as the edit plugin does, writes them to the files."""
    for item in task.items:
        for key in RELEASE_ID_FIELDS:
            item[key] = item._type(key).null
        for key, value in {**album, **items.get(displayable_path(item.path), {})}.items():
            item.set_parse(key, value)


def _keep_unmatched(task: ImportTask, match: AlbumMatch, tags: dict[str, dict[str, Any]]) -> None:
    """Import the files that match no track on the release (bonus tracks, say) with the album.

    beets imports only an album match's matched files. Every later stage asks the task for
    `imported_items()`, so the extra files join the album there; after the release's data is
    applied they take its album fields (album, album artist, year, …) and keep their own title,
    track and disc numbers, unless `tags` (by file path) gives them others.
    """
    extras = list(match.extra_items)
    imported_items, apply_metadata, apply_upgrade = (
        task.imported_items,
        task.apply_metadata,
        task.apply_upgrade,
    )

    def with_extras() -> list[Item]:
        # beets' own list follows the match as it narrows (see below) and the choice made.
        items = imported_items()
        if task.choice_flag == Action.APPLY and task.match is match:
            return [*items, *extras]
        return items

    def upgrade(kept: list[Item], superseded: list[Item], old_album_ids: list[int]) -> None:
        # Upgrading a duplicate keeps only the files that improve on it: kept files too.
        kept_ids = {id(i) for i in kept}
        extras[:] = [i for i in extras if id(i) in kept_ids]
        apply_upgrade(kept, superseded, old_album_ids)

    def apply_with_extras() -> None:
        apply_metadata()
        if not match.items:
            return
        source = match.items[0]
        for item in extras:
            for key in Album.item_keys:
                item[key] = source.get(key)
            given = tags.get(displayable_path(item.path), {})
            if given.get("title"):
                item.title = given["title"]
            for key in ("track", "disc"):
                if given.get(key) is not None:
                    item[key] = given[key]
        # Track totals count the kept files too, as beets counts: per disc with
        # per_disc_numbering, else across the release.
        everything = [*match.items, *extras]
        per_disc = config["per_disc_numbering"].get(bool)
        for disc in {i.disc for i in everything} if per_disc else {None}:
            group = [i for i in everything if disc is None or i.disc == disc]
            total = max(max(i.tracktotal or 0 for i in group), max(i.track or 0 for i in group))
            for item in group:
                item.tracktotal = total

    task.imported_items = with_extras
    task.apply_upgrade = upgrade
    task.apply_metadata = apply_with_extras


def summary_judgment(rec: Recommendation) -> Action | None:
    """Decide without asking, as in quiet mode. Copied from beets' private _summary_judgment."""
    if config["import"]["quiet"]:
        if rec == Recommendation.strong:
            return Action.APPLY
        return config["import"]["quiet_fallback"].as_choice(
            {"skip": Action.SKIP, "asis": Action.ASIS}
        )
    if config["import"]["timid"]:
        return None
    if rec == Recommendation.none:
        return config["import"]["none_rec_action"].as_choice(
            {"skip": Action.SKIP, "asis": Action.ASIS, "ask": None}
        )
    return None


# Serialization


def serialize_task(task: ImportTask) -> dict[str, Any]:
    source = task.source
    return {
        "kind": source.type,
        "paths": [displayable_path(p) for p in task.paths],
        "artist": source.artist,
        "name": source.name,
        "items": [serialize_item(i) for i in source.items],
        # The album's tags in its files (each file's most common value), to start entering
        # tags by hand from.
        "album_tags": {key: _most_common(source.items, key) for key in MANUAL_ALBUM_FIELDS},
    }


def _most_common(items: list[Item], key: str) -> Any:
    values = [i.get(key) for i in items]
    counts = Counter(json.dumps(v, default=str) for v in values)
    best = counts.most_common(1)[0][0] if counts else None
    return next((v for v in values if json.dumps(v, default=str) == best), None)


def serialize_item(item: Item) -> dict[str, Any]:
    return {
        "path": displayable_path(item.path),
        "title": item.title,
        "artist": item.artist,
        "album": item.album,
        "track": item.track,
        "disc": item.disc,
        "length": item.length,
        "format": item.format,
        "bitrate": item.bitrate,
    }


def serialize_candidate(index: int, match: AlbumMatch | TrackMatch) -> dict[str, Any]:
    info = match.info
    distance = match.distance.distance
    data = {
        "index": index,
        "distance": distance,
        "similarity": round((1 - distance) * 100, 1),
        "strength": _strength(distance),
        "penalties": match.distance.generic_penalty_keys,
        "disambig": match.disambig_string,
        "artist": info.artist,
        "name": info.name,
        "id": info.id,
        "data_source": info.get("data_source"),
    }
    if isinstance(match, AlbumMatch):
        # Where each track sits on the release: how answers pair files with tracks by hand.
        positions = {id(t): pos for pos, t in enumerate(info.tracks)}
        data |= {
            "year": info.get("year"),
            "label": info.get("label"),
            "country": info.get("country"),
            "media": info.get("media"),
            "albumtype": info.get("albumtype"),
            "tracks": [
                {"item": serialize_item(item), "track": _serialize_track(track, positions)}
                for item, track in sorted(match.mapping.items(), key=lambda p: p[1].index or 0)
            ],
            "extra_items": [serialize_item(i) for i in match.extra_items],
            "extra_tracks": [_serialize_track(t, positions) for t in match.extra_tracks],
        }
    else:
        data |= {"album": info.get("album"), "length": info.get("length")}
    return data


def _serialize_track(track, positions: dict[int, int]) -> dict[str, Any]:
    return {
        "pos": positions[id(track)],
        "title": track.get("title"),
        "artist": track.get("artist"),
        "index": track.get("index"),
        "medium": track.get("medium"),
        "medium_index": track.get("medium_index"),
        "length": track.get("length"),
    }


def _strength(distance: float) -> str:
    if distance <= config["match"]["strong_rec_thresh"].as_number():
        return "strong"
    if distance <= config["match"]["medium_rec_thresh"].as_number():
        return "medium"
    return "weak"


# Helpers


def _tag(task: ImportTask, artist: str | None = None, name: str | None = None, **kwargs):
    method = tag_item if isinstance(task, SingletonImportTask) else tag_album
    return method(task.source, artist, name, **kwargs)


def _album_key(item: Item) -> tuple[str, str]:
    """The key beets' group_albums stage groups files by."""
    return (item.albumartist or item.artist, item.album)


def _abort(session: ImportSession, task: ImportTask) -> None:
    raise ImportAbortError()


def _task_label(task: ImportTask) -> str:
    return task.source.desc if (task.source.artist or task.source.name) else _task_path(task)


def _task_path(task: ImportTask) -> str:
    return displayable_path(task.paths[0] if task.paths else b"")


def _describe(obj: Album | Item) -> str:
    if isinstance(obj, Album):
        return f"{obj.albumartist} - {obj.album}"
    return f"{obj.artist} - {obj.title}"


def _import_loghandler() -> logging.Handler | None:
    """The import log file, as `beet import` opens it."""
    if config["import"]["log"].get() is None:
        return None
    return logging.FileHandler(syspath(config["import"]["log"].as_filename()), encoding="utf-8")


class _JobLogHandler(logging.Handler):
    """Copies beets' warnings and the importer's own log lines into the job log."""

    def __init__(self, job: ImportJob):
        super().__init__(logging.INFO)
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "beets" and record.levelno < logging.WARNING:
            return
        try:
            message = record.getMessage()
        except Exception:
            return
        self.job.event("log", message, level=record.levelname.lower())


# Plugin events

_running_job: ImportJob | None = None
_listeners_installed = False


def _install_listeners() -> None:
    # Appended directly rather than via BeetsPlugin.register_listener: its wrapper asserts the
    # plugin logger's level is unset, which fails when pipeline threads emit events concurrently.
    global _listeners_installed
    if _listeners_installed:
        return
    BeetsPlugin.listeners["album_imported"].append(_on_album_imported)
    BeetsPlugin.listeners["item_imported"].append(_on_item_imported)
    _listeners_installed = True


def _on_album_imported(lib: Library, album: Album, **_: Any) -> None:
    if (job := _running_job) is not None:
        job.event("imported", f"Imported {_describe(album)}", album_id=album.id)


def _on_item_imported(lib: Library, item: Item, **_: Any) -> None:
    if (job := _running_job) is not None:
        job.event("imported", f"Imported {_describe(item)}", item_id=item.id)
