"""Running beets imports from the browser.

An `ImportJob` runs a `WebImportSession` in a worker thread. Whenever beets needs a decision
(which candidate to apply, what to do with a duplicate, whether to resume), the session publishes a
question on the job and blocks until the browser answers it. See docs/interactive-import.md.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from beets import config, plugins
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

LOG_LIMIT = 500
# Short letters the built-in prompt uses for things that aren't PromptChoices here.
RESERVED_SHORTS = {"a", "e", "i", "m"}


class ImportBusyError(Exception):
    """Raised when an import is started while another one is still running."""


class ImportJob:
    def __init__(
        self,
        lib: Library,
        paths: list[str],
        options: dict[str, Any],
        on_change: Callable[[], None],
    ):
        self.paths = paths
        self.options = options
        self.status = "running"  # running | waiting | done | aborted | failed
        self.error: str | None = None
        self.started = time.time()
        self.finished: float | None = None
        self.log: list[dict[str, Any]] = []
        self.question: dict[str, Any] | None = None

        self._on_change = on_change
        self._cond = threading.Condition()
        # Questions can come from different pipeline stages; ask them one at a time.
        self._ask_lock = threading.Lock()
        self._answer: dict[str, Any] | None = None
        self._next_question = 1
        self._aborted = False
        self._lib = lib
        self._thread = threading.Thread(target=self._run, name="webui-import", daemon=True)

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
                "options": self.options,
                "error": self.error,
                "started": self.started,
                "finished": self.finished,
                "question": self.question,
                "log": self.log[-LOG_LIMIT:],
            }

    def event(self, kind: str, message: str, **data: Any) -> None:
        with self._cond:
            self.log.append({"time": time.time(), "kind": kind, "message": message, **data})
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
        # Per-import options go into the global config; restore it afterwards.
        config["import"].flatten()
        saved_sources = list(config.sources)
        _running_job = self
        try:
            config.set(config_overrides(self.options))
            session = WebImportSession(
                self, self._lib, _import_loghandler(), [p.encode() for p in self.paths]
            )
            session.logger.addHandler(handler)
            beets_log.addHandler(handler)
            self.event("started", f"Importing {', '.join(self.paths)}")
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
        self.job: ImportJob | None = None
        self.version = 0
        self._cond = threading.Condition()
        _install_listeners()

    def start(self, paths: list[str], options: dict[str, Any]) -> ImportJob:
        with self._cond:
            if self.job is not None and self.job.active:
                raise ImportBusyError()
            self.job = ImportJob(self.lib, paths, options, self._changed)
        self.job.start()
        self._changed()
        return self.job

    def wait_for_change(self, version: int, timeout: float) -> int:
        """Block until the state is newer than `version` (or timeout); return the new version."""
        with self._cond:
            self._cond.wait_for(lambda: self.version != version, timeout)
            return self.version

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
                },
            )

            kind = answer["type"]
            if kind == "apply":
                return self._chose(task, task.candidates[answer["candidate"]])
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
            else:
                raise ValueError(f"unknown answer type {kind!r}")

            if isinstance(proposal, Proposal):
                task.candidates, task.rec = proposal.candidates, proposal.recommendation

    def _chose(self, task: ImportTask, choice, reason: str | None = None):
        if isinstance(choice, (AlbumMatch, TrackMatch)):
            what = f"Applying {choice.info.artist} - {choice.info.name}"
        else:
            what = {
                Action.SKIP: "Skipping",
                Action.ASIS: "Importing as-is",
                Action.TRACKS: "Importing as tracks",
                Action.ALBUMS: "Grouping albums",
                Action.RESCAN: "Rescanning",
            }.get(choice, choice.name.title())
        suffix = f" ({reason})" if reason else ""
        self.job.event("choice", f"{what}: {_task_label(task)}{suffix}", path=_task_path(task))
        return choice

    def _choices(self, task: ImportTask) -> list[PromptChoice]:
        """Built-in prompt choices plus those plugins add, like the terminal prompt."""
        choices = [
            PromptChoice("s", "Skip", lambda s, t: Action.SKIP),
            PromptChoice("u", "Use as-is", lambda s, t: Action.ASIS),
        ]
        if task.is_album:
            choices += [
                PromptChoice("t", "as Tracks", lambda s, t: Action.TRACKS),
                PromptChoice("g", "Group albums", lambda s, t: Action.ALBUMS),
            ]
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
    }


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
        data |= {
            "year": info.get("year"),
            "label": info.get("label"),
            "country": info.get("country"),
            "media": info.get("media"),
            "albumtype": info.get("albumtype"),
            "tracks": [
                {"item": serialize_item(item), "track": _serialize_track(track)}
                for item, track in sorted(match.mapping.items(), key=lambda p: p[1].index or 0)
            ],
            "extra_items": [serialize_item(i) for i in match.extra_items],
            "extra_tracks": [_serialize_track(t) for t in match.extra_tracks],
        }
    else:
        data |= {"album": info.get("album"), "length": info.get("length")}
    return data


def _serialize_track(track) -> dict[str, Any]:
    return {
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
