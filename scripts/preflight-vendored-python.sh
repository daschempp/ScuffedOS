#!/usr/bin/env bash
# Refuse to build the .app against a stale or incomplete vendored runtime.
#
# Tauri bundles build/py (and build/pgsql) VERBATIM, so anything wrong with
# those trees ships. Reusing a build/py older than requirements.txt is exactly
# what shipped an .app without phonenumberslite: every test passed, and contacts
# sync raised ImportError on the user's Mac.
#
# Two callers, deliberately:
#   * scripts/build-app.sh, at [5b/7]. Belt-and-braces there: [2/7] always
#     re-vendors, so the staleness half cannot fire in a full run.
#   * src-tauri/tauri.conf.json's build.beforeBuildCommand, so a HAND-RUN
#     `cargo tauri build` — the path the incident actually took — refuses too.
#
# Tauri runs that hook through `sh -c` with a cwd it resolves itself, so this
# script depends on nothing but its own location: every path below is derived
# from $0.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
REQ="$ROOT/backend/requirements.txt"
VENDOR_PY="$ROOT/scripts/vendor-python.sh"
VENDOR_PG="$ROOT/scripts/vendor-postgres.sh"
PY_STAMP="$BUILD/py.stamp"
PG_STAMP="$BUILD/pgsql.stamp"
PY_BIN="$BUILD/py/bin/python3"

# Deps vendor-python.sh installs beyond requirements.txt (its EXTRA_DEPS). A
# test pins these two lists equal.
PY_EXTRA_ARGS=(--extra "uvicorn[standard]" --extra "cryptography" --extra "keyring")

# 1) Was anything vendored at all? A different fault from "stale", and a
#    different instruction, so it gets its own message.
if [ ! -f "$PY_STAMP" ]; then
  echo "FAIL: no vendored Python — build/py.stamp is missing." >&2
  echo "      Run: bash scripts/vendor-python.sh" >&2
  exit 1
fi

# 2) Is what was vendored older than its inputs?
if [ "$REQ" -nt "$PY_STAMP" ] || [ "$VENDOR_PY" -nt "$PY_STAMP" ]; then
  echo "FAIL: vendored Python is stale (build/py predates backend/requirements.txt" >&2
  echo "      or scripts/vendor-python.sh)." >&2
  echo "      Run: rm -rf build/py && bash scripts/vendor-python.sh" >&2
  exit 1
fi

# 3) Same rule for Postgres, but only when that tree has a stamp to compare
#    against (vendor-postgres.sh writes build/pgsql.stamp last). No stamp means
#    nothing to judge — build/pgsql may simply not have been vendored yet, and
#    Tauri's own resource check is what catches an absent tree.
if [ -f "$PG_STAMP" ] && [ "$VENDOR_PG" -nt "$PG_STAMP" ]; then
  echo "FAIL: vendored Postgres is stale (build/pgsql predates" >&2
  echo "      scripts/vendor-postgres.sh)." >&2
  echo "      Run: rm -rf build/pgsql && bash scripts/vendor-postgres.sh" >&2
  exit 1
fi

# 4) Fresh timestamps do not mean a complete tree: assert every requirement is
#    really installed in the interpreter that will be bundled.
python3 "$ROOT/scripts/check_vendored_deps.py" \
  --requirements "$REQ" \
  --python "$PY_BIN" \
  "${PY_EXTRA_ARGS[@]}"
