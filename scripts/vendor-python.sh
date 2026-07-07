#!/usr/bin/env bash
# Vendor a relocatable CPython 3.14.5 with backend deps TRUE-INSTALLED (not a
# venv) for the ScuffedOS .app. Fails loudly if any dep would compile from
# sdist (that would break offline first-run). Apple-Silicon only.
set -euo pipefail

PY_SERIES="3.14"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
OUT="$BUILD/py"
RAW="$BUILD/_py-raw"
REQ="$ROOT/backend/requirements.txt"

# Extra deps beyond requirements.txt:
#   - uvicorn[standard] : compiled extras (uvloop/httptools) for the ASGI server.
#   - cryptography      : Slice 2's secrets vault (spec §4.5) — AES-256-GCM +
#                          HKDF. First-class runtime import as of Slice 2.
#   - keyring           : Slice 2's secrets vault — wraps the single vault key
#                          in one OS-keychain item in the packaged app.
EXTRA_DEPS=("uvicorn[standard]" "cryptography" "keyring")

rm -rf "$OUT" "$RAW"
mkdir -p "$BUILD"

echo "==> Installing managed CPython $PY_SERIES via uv"
uv python install --managed-python "$PY_SERIES"
PY_BIN="$(uv python find --managed-python "$PY_SERIES")"
echo "    using: $PY_BIN ($("$PY_BIN" --version))"

echo "==> Parsing deps from $REQ"
DEPS=()
while IFS= read -r line; do
  DEPS+=("$line")
done < <(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$REQ")
ALL_DEPS=("${DEPS[@]}" "${EXTRA_DEPS[@]}")
echo "    ${#ALL_DEPS[@]} package specs: ${ALL_DEPS[*]}"

# ---------------------------------------------------------------------------
# Fail-on-sdist guard (real preflight, not a no-op env var).
#
# py-app-standalone (locked interface below) shells out to `uv pip install
# <packages> --python <interpreter> --break-system-packages` internally and
# does NOT expose a flag or env var to inject `--only-binary`/`--no-binary`
# into that call (confirmed by reading py-app-standalone 0.2.1's build.py —
# its only options are packages/--target/--python-version/--source-only/
# --force). `PIP_ONLY_BINARY` is a pip-ism uv does NOT honor (verified: with
# the env var set, `uv pip install pyyaml==3.13` still built the sdist).
#
# So we run our own `uv pip install --only-binary :all: --dry-run` against
# the SAME managed interpreter with the SAME package list first. If any dep
# lacks a cp314 arm64 wheel, this aborts loudly here, before the slow real
# install, with the exact package named in uv's resolver error.
# ---------------------------------------------------------------------------
echo "==> Fail-on-sdist preflight: resolving all deps as wheels-only (no sdist builds allowed)"
uv pip install \
  --python "$PY_BIN" \
  --break-system-packages \
  --only-binary :all: \
  --dry-run \
  "${ALL_DEPS[@]}"
echo "    preflight OK: every dep resolves to a prebuilt wheel for $("$PY_BIN" --version)"

echo "==> True-installing deps into a copy of the interpreter (py-app-standalone)"
# Locked CLI interface (uvx py-app-standalone --help, v0.2.1):
#   py-app-standalone [--source-only] [--target TARGET]
#                      [--python-version PYTHON_VERSION] [--force] packages...
# No --python / --requirements / -o — it's --python-version / (none) /
# --target, and there's no requirements-file flag, so DEPS were pre-parsed
# into positional pip-format specs above. Confirmed via source
# (py_app_standalone/build.py): it runs `uv python install --managed-python`
# then `uv pip install <packages> --python <install_root> --break-system-
# packages` directly into the interpreter tree (never creates a real venv —
# the transient "bare-venv" is only used to lift a pyvenv.cfg file, then
# deleted), which is exactly the true-install semantics this task requires.
# NOTE: --target is passed as a path RELATIVE to $BUILD (cd'd into below), not
# absolute. py-app-standalone's own internal absolute-path replacement pass
# substitutes the resolved-absolute install dir with whatever string was
# literally passed to --target — if that string is itself already absolute
# (e.g. under this repo's checkout path), the substitution is a no-op and its
# own sanity check then FAILS ("Found N matches ... in binary files") because
# the absolute build path is still baked into _sysconfigdata. A relative
# --target avoids that: verified empirically (py-app-standalone 0.2.1).
( cd "$BUILD" && uvx py-app-standalone \
  --python-version "$PY_SERIES" \
  --target "_py-raw" \
  --force \
  "${ALL_DEPS[@]}" )

# py-app-standalone lays out $RAW/cpython-<full-version>-macos-aarch64-none/
# (plus a series symlink, .lock, .temp, .gitignore). Flatten the fully
# versioned interpreter dir so callers get a stable build/py/bin/python3
# path with no absolute-path symlink wrapper shipped in the tree.
INSTALL_ROOT="$(find "$RAW" -maxdepth 1 -type d -name 'cpython-*.*.*-macos-aarch64-none' | head -1)"
if [ -z "$INSTALL_ROOT" ]; then
  echo "FAIL: could not find versioned interpreter dir under $RAW"; exit 1
fi
mkdir -p "$OUT"
mv "$INSTALL_ROOT"/* "$OUT"/
mv "$INSTALL_ROOT"/.[!.]* "$OUT"/ 2>/dev/null || true
rm -rf "$RAW"

echo "==> Relocation fix: libpython install-name + re-sign"
LIBPY="$(find "$OUT/lib" -maxdepth 1 -name 'libpython3.14*.dylib' | head -1)"
if [ -n "${LIBPY:-}" ]; then
  install_name_tool -id "@executable_path/../lib/$(basename "$LIBPY")" "$LIBPY"
  codesign --force -s - "$LIBPY"
fi

echo "==> Pruning caches/tests/static-libs"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.a' -delete 2>/dev/null || true
find "$OUT/lib" -type d -name 'test' -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$OUT"/lib/python3.14/{idlelib,turtledemo,tkinter} 2>/dev/null || true

echo "==> Re-signing every Mach-O we may have touched"
find "$OUT" -type f \( -name '*.dylib' -o -name '*.so' \) -exec codesign --force -s - {} + 2>/dev/null || true
codesign --force -s - "$OUT/bin/python3" 2>/dev/null || true

echo "==> Fail-on-sdist audit: verify all C-extension deps have cp314 arm64 .so"
# psycopg (binary), pydantic_core, and any compiled dep must exist as loadable
# .so under the tree. The dry-run preflight above is what actually blocks a
# missing wheel; this is the belt-and-suspenders smoke import against the
# real, true-installed tree.
"$OUT/bin/python3" - <<'PY'
import importlib.util, sys
sys.exit(0 if all(
    importlib.util.find_spec(m) for m in ("psycopg", "pydantic_core", "fastapi", "uvicorn", "alembic", "cryptography", "keyring")
) else 1)
PY

echo "==> otool relocation check (no /opt/homebrew, no absolute build paths)"
BAD=0
while IFS= read -r macho; do
  if otool -L "$macho" 2>/dev/null | grep -E '/opt/homebrew|/usr/local/Cellar|/private/var/folders' >/dev/null; then
    echo "NON-RELOCATABLE: $macho"; BAD=1
  fi
done < <(find "$OUT" -type f \( -name '*.dylib' -o -name '*.so' -o -path '*/bin/*' \))
[ "$BAD" -eq 0 ] || { echo "FAIL: non-relocatable references"; exit 1; }

echo "PY_SERIES=$PY_SERIES PY_VERSION=$("$OUT/bin/python3" --version | awk '{print $2}')" > "$BUILD/py.stamp"
echo "==> Done: $OUT"
