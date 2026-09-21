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
`phonenumbers` module. Extras are resolved from the installed metadata and
demanded too — `psycopg[binary]` installs `psycopg` *and* `psycopg-binary` as
separate distributions, and without the latter `import psycopg` still succeeds
while the first database connect fails. An import smoke of the
compiled/critical modules runs alongside all of it when an interpreter is
given.

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

# The `extra == "name"` clause of a Requires-Dist marker. Searched rather than
# matched: real markers are compound, e.g. psycopg's
# `implementation_name != "pypy" and extra == "binary"`.
_EXTRA_MARKER_RE = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")

# An extra's dependency pinned to a platform this build never targets (the app
# is macOS arm64 only) is legitimately absent from the tree — uvicorn's
# `colorama; sys_platform == 'win32' and extra == 'standard'` must not fail the
# build. Deliberately narrow: an equality against a *named foreign* platform,
# not a general marker evaluation, so uvloop's `sys_platform != 'win32'` is
# still demanded.
_FOREIGN_PLATFORM_RE = re.compile(
    r"""sys_platform\s*==\s*['"](?!darwin)|platform_system\s*==\s*['"](?!Darwin)"""
)

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


def _parse_extras(rest: str) -> tuple[str, ...]:
    """The normalized extras in the `[...]` clause following a project name."""
    if not rest.startswith("["):
        return ()
    closing = rest.find("]")
    if closing == -1:
        raise ValueError(f"unterminated extras clause: {rest}")
    return tuple(
        _normalize(extra.strip())
        for extra in rest[1:closing].split(",")
        if extra.strip()
    )


def parse_requirements(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Return `(normalized name, normalized extras)` per requirement in `text`.

    Version specifiers, environment markers, comments and blank lines are
    stripped. Option lines (`-r`, `-e`, `--...`) and URL requirements raise
    ValueError instead of being skipped: this checker must never pass a file
    containing something it cannot verify.
    """
    requirements: list[tuple[str, tuple[str, ...]]] = []
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
        try:
            extras = _parse_extras(line[match.end():])
        except ValueError as exc:
            raise ValueError(f"line {lineno}: {exc}") from None
        requirements.append((_normalize(match.group()), extras))
    return requirements


def parse_requirement_names(text: str) -> list[str]:
    """The normalized project names in requirements-file `text`, extras dropped."""
    return [name for name, _ in parse_requirements(text)]


def _installed(site_packages: str) -> dict[str, importlib.metadata.Distribution]:
    """Installed distributions under `site_packages`, keyed by normalized name.

    A .dist-info with no METADATA, or none carrying a `Name:`, is skipped:
    `metadata["Name"]` would emit a DeprecationWarning on 3.14 — output on the
    success path of a build-gating script — and raise KeyError on a later one.
    """
    index: dict[str, importlib.metadata.Distribution] = {}
    for dist in importlib.metadata.distributions(path=[site_packages]):
        name = dist.metadata.get("Name")
        if name:
            index.setdefault(_normalize(name), dist)
    return index


def missing_distributions(names: list[str], site_packages: str) -> list[str]:
    """The `names` with no installed distribution under `site_packages`."""
    installed = _installed(site_packages)
    return [name for name in names if _normalize(name) not in installed]


def _extra_dependencies(
    dist: importlib.metadata.Distribution, extras: tuple[str, ...]
) -> list[str]:
    """The distributions `dist` declares for `extras` (one level, as installed).

    Markers are otherwise ignored, except that a dependency gated to a foreign
    platform is skipped — see `_FOREIGN_PLATFORM_RE`.
    """
    wanted = set(extras)
    names: list[str] = []
    for entry in dist.metadata.get_all("Requires-Dist", []):
        requirement, _, marker = entry.partition(";")
        found = _EXTRA_MARKER_RE.search(marker)
        if found is None or _normalize(found.group(1)) not in wanted:
            continue
        if _FOREIGN_PLATFORM_RE.search(marker):
            continue
        match = _NAME_RE.match(requirement.strip())
        if match:
            names.append(_normalize(match.group()))
    return names


def missing_extra_distributions(
    requirements: list[tuple[str, tuple[str, ...]]], site_packages: str
) -> list[str]:
    """The distributions a requirement's extras install that are absent.

    Extras are separate distributions: `psycopg[binary,pool]` installs
    `psycopg`, `psycopg-binary` and `psycopg-pool`. Checking only the base name
    passes a tree that imports fine and then fails at the first connect, so the
    extras are resolved from the *installed* base distribution's
    `Requires-Dist` metadata — nothing to keep in sync by hand. A requirement
    whose base is itself absent is skipped; `missing_distributions` reports it.
    """
    installed = _installed(site_packages)
    missing: list[str] = []
    for name, extras in requirements:
        dist = installed.get(_normalize(name))
        if dist is None or not extras:
            continue
        for required in _extra_dependencies(dist, extras):
            if required not in installed and required not in missing:
                missing.append(required)
    return missing


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
            requirements = parse_requirements(handle.read())
        requirements += parse_requirements("\n".join(args.extra))
    except (OSError, ValueError) as exc:
        print(f"cannot verify {args.requirements}: {exc}", file=sys.stderr)
        return 1
    requirements = list(dict.fromkeys(requirements))

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

    names = list(dict.fromkeys(name for name, _ in requirements))
    problems += [
        f"missing distribution: {name}"
        for name in missing_distributions(names, site_packages)
    ]
    problems += [
        f"missing extra distribution: {name}"
        for name in missing_extra_distributions(requirements, site_packages)
    ]

    for problem in sorted(set(problems)):
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
