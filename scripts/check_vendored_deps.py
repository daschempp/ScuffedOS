#!/usr/bin/env python3
"""Verify a vendored Python tree actually has every backend dependency.

`scripts/vendor-python.sh` installs `backend/requirements.txt` into `build/py`
and Tauri bundles that tree verbatim into the .app. The old smoke check was a
hard-coded tuple of module names, so a dependency added to requirements.txt
after the last vendoring — this is exactly what happened to `phonenumberslite`
— shipped missing and surfaced only as an ImportError at runtime.

This checker derives what must be present from requirements.txt itself, so it
cannot go stale. It looks up *distributions*, not module imports, because the
two names differ: the `phonenumberslite` distribution provides the
`phonenumbers` module. An import smoke of the compiled/critical modules runs
alongside it when an interpreter is given.

Python 3.11+, standard library only (it runs against the vendored interpreter,
which has no dev tooling installed).
"""
from __future__ import annotations

import argparse
import importlib.metadata
import re
import subprocess
import sys

# Import smoke: modules whose absence breaks the app at runtime — the compiled
# deps (a bad wheel imports as a broken .so rather than a missing distribution)
# plus the ones a stale vendoring has historically dropped. These are MODULE
# names, not distribution names.
MODULES = (
    "psycopg",
    "pydantic_core",
    "fastapi",
    "uvicorn",
    "alembic",
    "cryptography",
    "keyring",
    "phonenumbers",
)

# PEP 508 project name: alphanumeric at both ends, `-`, `_` and `.` inside.
_NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")

_PURELIB = "import sysconfig; print(sysconfig.get_paths()['purelib'])"

_SMOKE = """\
import importlib.util
for module in {modules!r}:
    try:
        found = importlib.util.find_spec(module) is not None
    except Exception:
        found = False
    if not found:
        print(module)
"""


def _normalize(name: str) -> str:
    """PEP 503: lowercase, with runs of `-`, `_` and `.` collapsed to `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_names(text: str) -> list[str]:
    """Return the normalized project names in requirements-file `text`.

    Extras, version specifiers, environment markers, comments and blank lines
    are stripped. Option lines (`-r`, `-e`, `--...`) and URL requirements raise
    ValueError instead of being skipped: this checker must never pass a file
    containing something it cannot verify.
    """
    names: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            raise ValueError(f"line {lineno}: unsupported option line: {line}")
        if "://" in line:
            raise ValueError(f"line {lineno}: unsupported URL requirement: {line}")
        match = _NAME_RE.match(line)
        if not match:
            raise ValueError(f"line {lineno}: cannot parse a project name: {line}")
        names.append(_normalize(match.group()))
    return names


def missing_distributions(names: list[str], site_packages: str) -> list[str]:
    """The `names` with no installed distribution under `site_packages`."""
    installed = {
        _normalize(dist.metadata["Name"])
        for dist in importlib.metadata.distributions(path=[site_packages])
        if dist.metadata["Name"]
    }
    return [name for name in names if _normalize(name) not in installed]


def _purelib(python: str) -> str:
    """The site-packages directory `python` installs pure-Python packages into."""
    probe = subprocess.run(
        [python, "-c", _PURELIB], capture_output=True, text=True, check=True
    )
    return probe.stdout.strip()


def _failed_imports(python: str) -> list[str]:
    """The MODULES that `python` cannot resolve."""
    smoke = subprocess.run(
        [python, "-c", _SMOKE.format(modules=MODULES)],
        capture_output=True,
        text=True,
        check=True,
    )
    return smoke.stdout.split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requirements", required=True, help="requirements.txt path")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--site-packages", help="the site-packages directory to check")
    target.add_argument("--python", help="an interpreter to check (resolves its own)")
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="SPEC",
        help="a dependency installed beyond requirements.txt (repeatable)",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.requirements, encoding="utf-8") as handle:
            names = parse_requirement_names(handle.read())
        names += parse_requirement_names("\n".join(args.extra))
    except (OSError, ValueError) as exc:
        print(f"cannot verify {args.requirements}: {exc}", file=sys.stderr)
        return 1

    problems: list[str] = []
    if args.python:
        try:
            site_packages = _purelib(args.python)
            problems = [f"import failed: {mod}" for mod in _failed_imports(args.python)]
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"cannot run {args.python}: {exc}", file=sys.stderr)
            return 1
    else:
        site_packages = args.site_packages

    problems += [
        f"missing distribution: {name}"
        for name in missing_distributions(list(dict.fromkeys(names)), site_packages)
    ]

    for problem in sorted(problems):
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
