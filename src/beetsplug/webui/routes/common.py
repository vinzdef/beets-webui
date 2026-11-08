"""Helpers shared by the library routes."""

from itertools import islice
from typing import Any

from beets import util
from beets.dbcore import Model
from beets.library import Library
from fastapi import Request

PATH_FIELDS = {"path", "artpath"}


def get_lib(request: Request) -> Library:
    return request.app.state.lib


def serialize(obj: Model) -> dict[str, Any]:
    out = {}
    # Not obj.items(): on Album that returns the album's tracks, not its fields.
    for key in obj.keys():
        value = obj.get(key)
        if key in PATH_FIELDS:
            value = util.displayable_path(value) if value else None
        elif isinstance(value, bytes):
            continue  # opaque blobs such as embedded art
        out[key] = value
    return out


def paginate(results, offset: int, limit: int) -> dict[str, Any]:
    rows = [serialize(r) for r in islice(results, offset, offset + limit)]
    return {"total": len(results), "offset": offset, "limit": limit, "results": rows}
