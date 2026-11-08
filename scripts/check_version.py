"""Check that the package version follows the beets version it supports, and print the latter.

    python scripts/check_version.py [vX.Y.Z]

The version is <beets major>.<beets minor>.<our release number>: 2.14.N works with beets 2.14.
Fails unless the version's major.minor matches both the `beets` requirement in pyproject.toml and
the beets version locked in uv.lock, and (if given) the git tag equals `v<version>`. Prints the
locked beets version, which the Docker image installs. Needs Python 3.11+ (tomllib).
"""

import re
import sys
from pathlib import Path

import tomllib

root = Path(__file__).resolve().parent.parent
project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
lock = tomllib.loads((root / "uv.lock").read_text())

version = project["version"]
requirement = next(d for d in project["dependencies"] if re.match(r"beets\b", d))
locked = next(p["version"] for p in lock["package"] if p["name"] == "beets")

errors = []
series = ".".join(version.split(".")[:2])
# ">=2.1" mustn't pass for "beets>=2.14": the series has to end where a number does.
pinned = re.search(rf">={re.escape(series)}(?!\d)", requirement)
if not pinned or not locked.startswith(f"{series}."):
    errors.append(
        f"version {version} must match beets {series}.x, but pyproject requires "
        f"{requirement!r} and uv.lock has beets {locked}"
    )
if len(sys.argv) > 1 and sys.argv[1] != f"v{version}":
    errors.append(f"tag {sys.argv[1]} doesn't match version {version} (expected v{version})")

if errors:
    sys.exit("\n".join(errors))
print(locked)
