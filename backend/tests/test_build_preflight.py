"""The build-time preflight that refuses a stale or incomplete `build/py`.

`scripts/vendor-python.sh` installs `backend/requirements.txt` into `build/py`
and Tauri bundles that tree verbatim, so a build against a `build/py` older than
its inputs ships a runtime missing a dependency — the incident that shipped an
.app without `phonenumberslite`. That incident's path was a HAND-RUN `cargo tauri
build`, not `scripts/build-app.sh`, so the guard cannot live only inside
build-app.sh: `scripts/preflight-vendored-python.sh` is a standalone script that

  * `scripts/build-app.sh` runs at `[5b/7]` (belt-and-braces there — `[2/7]`
    always re-vendors), and
  * `src-tauri/tauri.conf.json` runs as `build.beforeBuildCommand`, so a bare
    `cargo tauri build` refuses on its own.

These tests drive the script against a throwaway repo layout with a STUB
`check_vendored_deps.py` that records its argv, so they pin the staleness rules,
the exact checker invocation, and the cwd-independence the Tauri hook depends on
— without vendoring anything (the real scripts download toolchains).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
PREFLIGHT = SCRIPTS / "preflight-vendored-python.sh"
BUILD_APP = SCRIPTS / "build-app.sh"
VENDOR_PY = SCRIPTS / "vendor-python.sh"
VENDOR_PG = SCRIPTS / "vendor-postgres.sh"
TAURI_CONF = REPO_ROOT / "src-tauri" / "tauri.conf.json"

# vendor-python.sh's EXTRA_DEPS, in order. A test below pins that these stay
# equal to what the vendoring script actually installs.
EXPECTED_EXTRAS = ["uvicorn[standard]", "cryptography", "keyring"]

# A stand-in for scripts/check_vendored_deps.py: records the argv it was called
# with, and fails when STUB_CHECKER_EXIT says so.
STUB_CHECKER = """\
import json, os, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "build", "checker-argv.json"), "w") as handle:
    json.dump(sys.argv[1:], handle)
sys.exit(int(os.environ.get("STUB_CHECKER_EXIT", "0")))
"""


def _fake_repo(tmp_path: Path, *, stamp: bool = True) -> Path:
    """A throwaway repo the preflight can resolve itself inside."""
    root = tmp_path / "repo"
    (root / "backend").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "build" / "py" / "bin").mkdir(parents=True)

    (root / "backend" / "requirements.txt").write_text("fastapi>=0.115.0\n")
    shutil.copy(PREFLIGHT, root / "scripts" / "preflight-vendored-python.sh")
    shutil.copy(VENDOR_PY, root / "scripts" / "vendor-python.sh")
    shutil.copy(VENDOR_PG, root / "scripts" / "vendor-postgres.sh")
    (root / "scripts" / "check_vendored_deps.py").write_text(STUB_CHECKER)
    # The interpreter path is only ever passed through to the checker here.
    (root / "build" / "py" / "bin" / "python3").symlink_to(sys.executable)
    if stamp:
        (root / "build" / "py.stamp").write_text("PY_SERIES=3.14 PY_VERSION=3.14.5\n")
        _stamp_is_newest(root)
    return root


def _stamp_is_newest(root: Path, *, skew: int = 100) -> None:
    """Age every input so the stamp is unambiguously the most recent file."""
    stamp = root / "build" / "py.stamp"
    now = stamp.stat().st_mtime
    for older in (root / "backend" / "requirements.txt",
                  root / "scripts" / "vendor-python.sh",
                  root / "scripts" / "vendor-postgres.sh"):
        os.utime(older, (now - skew, now - skew))
    os.utime(stamp, (now, now))


def _touch_newer_than_stamp(path: Path, stamp: Path, *, skew: int = 100) -> None:
    when = stamp.stat().st_mtime + skew
    os.utime(path, (when, when))


def _run_preflight(root: Path, *, cwd: Path | None = None,
                   checker_exit: int = 0) -> subprocess.CompletedProcess:
    env = dict(os.environ, STUB_CHECKER_EXIT=str(checker_exit))
    return subprocess.run(
        ["bash", str(root / "scripts" / "preflight-vendored-python.sh")],
        capture_output=True, text=True, cwd=str(cwd or root), env=env,
    )


def _checker_argv(root: Path) -> list[str] | None:
    recorded = root / "build" / "checker-argv.json"
    return json.loads(recorded.read_text()) if recorded.exists() else None


# ---- the staleness rules -----------------------------------------------------
def test_preflight_fails_with_a_distinct_message_when_the_stamp_is_missing(tmp_path):
    # Never vendored (or build/ wiped): a different fault from "stale", and the
    # operator needs a different instruction, so it gets its own message.
    root = _fake_repo(tmp_path, stamp=False)

    result = _run_preflight(root)

    assert result.returncode != 0
    assert "build/py.stamp" in result.stderr
    assert "missing" in result.stderr.lower()
    assert "stale" not in result.stderr.lower()
    assert _checker_argv(root) is None          # never got as far as the checker


@pytest.mark.parametrize("newer", ["backend/requirements.txt", "scripts/vendor-python.sh"])
def test_preflight_fails_when_an_input_is_newer_than_the_stamp(tmp_path, newer):
    # This is the incident: a dependency added to requirements.txt after the last
    # vendoring. The vendoring script itself counts too (it pins the interpreter
    # series and the extras).
    root = _fake_repo(tmp_path)
    _touch_newer_than_stamp(root / newer, root / "build" / "py.stamp")

    result = _run_preflight(root)

    assert result.returncode != 0
    assert "stale" in result.stderr.lower()
    assert "vendor-python.sh" in result.stderr      # tells the operator what to run
    assert _checker_argv(root) is None


def test_preflight_fails_when_the_postgres_vendoring_script_outdates_its_stamp(tmp_path):
    # Same rule for build/pgsql, but only when that tree has a stamp to compare
    # against: vendor-postgres.sh writes build/pgsql.stamp, and an older Postgres
    # tree ships just as verbatim as an older build/py.
    root = _fake_repo(tmp_path)
    pgsql_stamp = root / "build" / "pgsql.stamp"
    pgsql_stamp.write_text("PG_VERSION=17.10.0\n")
    os.utime(pgsql_stamp, ((root / "build" / "py.stamp").stat().st_mtime,) * 2)
    _touch_newer_than_stamp(root / "scripts" / "vendor-postgres.sh", pgsql_stamp)

    result = _run_preflight(root)

    assert result.returncode != 0
    assert "vendor-postgres.sh" in result.stderr
    assert _checker_argv(root) is None


def test_preflight_ignores_postgres_when_that_tree_was_never_stamped(tmp_path):
    # No build/pgsql.stamp means nothing to compare; the rule must not turn into
    # "you may never build" for a checkout that has not vendored Postgres yet.
    root = _fake_repo(tmp_path)
    assert not (root / "build" / "pgsql.stamp").exists()

    result = _run_preflight(root)

    assert result.returncode == 0, result.stderr


# ---- what it runs once the tree is fresh -------------------------------------
def test_preflight_checks_the_vendored_interpreter_with_every_extra(tmp_path):
    root = _fake_repo(tmp_path)

    result = _run_preflight(root)

    assert result.returncode == 0, result.stderr
    argv = _checker_argv(root)
    assert argv is not None, "the checker must run once the stamp is fresh"
    extras = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--extra"]
    assert extras == EXPECTED_EXTRAS
    assert argv[:4] == [
        "--requirements", str(root / "backend" / "requirements.txt"),
        # the VENDORED interpreter, not whatever python3 the shell has
        "--python", str(root / "build" / "py" / "bin" / "python3"),
    ]


def test_preflight_fails_when_the_checker_fails(tmp_path):
    # A fresh stamp proves only the timestamps; the tree must also be complete.
    root = _fake_repo(tmp_path)

    result = _run_preflight(root, checker_exit=1)

    assert result.returncode != 0
    assert _checker_argv(root) is not None


@pytest.mark.parametrize("where", ["scripts", "backend", "outside"])
def test_preflight_resolves_the_repo_from_its_own_path_not_the_cwd(tmp_path, where):
    """Tauri runs beforeBuildCommand through `sh -c` with a cwd it picks itself
    (the resolved *frontend* directory), and build-app.sh's own cwd wanders too.
    The script must therefore depend on nothing but its own location."""
    root = _fake_repo(tmp_path)
    cwd = tmp_path if where == "outside" else root / where

    result = _run_preflight(root, cwd=cwd)

    assert result.returncode == 0, result.stderr
    argv = _checker_argv(root)
    assert argv[1] == str(root / "backend" / "requirements.txt")    # absolute, from $0


# ---- the two callers ---------------------------------------------------------
def test_build_app_delegates_to_the_preflight_and_keeps_the_bundle_recheck():
    source = BUILD_APP.read_text()
    assert "preflight-vendored-python.sh" in source
    # [6b/7] — the bundled interpreter, checked before signing — is genuinely
    # extra coverage and must survive the move.
    assert "[6b/7]" in source
    assert "Contents/Resources/py/bin/python3" in source
    # the inlined staleness test moved into the preflight script
    assert "py.stamp" not in source.split("[5b/7]", 1)[1].split("[6/7]", 1)[0]


def test_tauri_config_refuses_a_bare_cargo_tauri_build_against_a_stale_tree():
    config = json.loads(TAURI_CONF.read_text())
    hook = config["build"]["beforeBuildCommand"]
    assert isinstance(hook, str), "a plain string: an object's relative cwd " \
                                  "would resolve against the CLI's own cwd"
    assert "preflight-vendored-python.sh" in hook
    # cwd-independent: the hook locates the repo rather than assuming a cwd.
    assert "git rev-parse --show-toplevel" in hook
    # `cargo tauri dev` must stay untouched — the dev path bundles nothing.
    assert "beforeDevCommand" not in config["build"]


def test_preflight_extras_match_the_vendoring_scripts_extra_deps():
    """The two lists are written out twice (the checker takes pip specs, the
    vendoring script installs them); a drift would silently stop verifying one."""
    declared = re.search(r"^EXTRA_DEPS=\((.*)\)$", VENDOR_PY.read_text(), re.M)
    assert declared, "vendor-python.sh no longer declares EXTRA_DEPS"
    installed = [spec.strip('"') for spec in declared.group(1).split()]
    assert installed == EXPECTED_EXTRAS

    verified = re.findall(r'--extra "?([^" \\]+)"?', PREFLIGHT.read_text())
    assert verified == EXPECTED_EXTRAS


@pytest.mark.parametrize("script", [PREFLIGHT, BUILD_APP, VENDOR_PY])
def test_shell_scripts_are_syntactically_valid(script):
    # These scripts download toolchains, so they are never run end to end here.
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
