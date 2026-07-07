#!/usr/bin/env bash
# Vendor a relocatable PostgreSQL 17.10.0 (arm64) with pgvector 0.8.4 for the
# ScuffedOS .app bundle. Run on an Apple-Silicon Mac with Xcode CLT installed.
set -euo pipefail

PG_VERSION="17.10.0"
PGVECTOR_VERSION="0.8.4"
ARCH="aarch64-apple-darwin"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
WORK="$BUILD/_pgwork"
OUT="$BUILD/pgsql"

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$OUT"

echo "==> Downloading PostgreSQL $PG_VERSION ($ARCH) from theseus-rs"
PG_URL="https://github.com/theseus-rs/postgresql-binaries/releases/download/${PG_VERSION}/postgresql-${PG_VERSION}-${ARCH}.tar.gz"
curl -fL "$PG_URL" -o "$WORK/pg.tar.gz"
tar -xzf "$WORK/pg.tar.gz" -C "$WORK"
# theseus tarball extracts to a single top dir; move its contents into OUT.
PGSRC="$(find "$WORK" -maxdepth 1 -type d -name 'postgresql-*' | head -1)"
cp -R "$PGSRC"/. "$OUT"/
PGROOT="$OUT"
PG_CONFIG="$PGROOT/bin/pg_config"
test -x "$PG_CONFIG" || { echo "pg_config missing at $PG_CONFIG"; exit 1; }

echo "==> Building pgvector $PGVECTOR_VERSION against vendored PG"
# The theseus binaries bake their own CI Xcode SDK path into pg_config's
# --cppflags/--ldflags (as PG_SYSROOT in Makefile.global). That path doesn't
# exist on this machine, so override it with the local toolchain's SDK.
SDKROOT="$(xcrun --show-sdk-path)"
curl -fL "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" \
  -o "$WORK/pgvector.tar.gz"
tar -xzf "$WORK/pgvector.tar.gz" -C "$WORK"
PVSRC="$WORK/pgvector-${PGVECTOR_VERSION}"
make -C "$PVSRC" clean || true
make -C "$PVSRC" PG_CONFIG="$PG_CONFIG" PG_SYSROOT="$SDKROOT"
make -C "$PVSRC" PG_CONFIG="$PG_CONFIG" PG_SYSROOT="$SDKROOT" install

echo "==> Ad-hoc re-signing pgvector"
VECTOR_DYLIB="$($PG_CONFIG --pkglibdir)/vector.dylib"
test -f "$VECTOR_DYLIB" || { echo "vector.dylib not installed at $VECTOR_DYLIB"; exit 1; }
codesign --force --sign - "$VECTOR_DYLIB"

echo "==> Relocation check (no /opt/homebrew or absolute build paths)"
BAD=0
while IFS= read -r macho; do
  if otool -L "$macho" 2>/dev/null | grep -E '/opt/homebrew|/usr/local/Cellar' >/dev/null; then
    echo "NON-RELOCATABLE: $macho"
    otool -L "$macho" | grep -E '/opt/homebrew|/usr/local/Cellar'
    BAD=1
  fi
done < <(find "$PGROOT" \( -name '*.dylib' -o -name '*.so' \) -o -path '*/bin/*' -type f)
if [ "$BAD" -ne 0 ]; then
  echo "FAIL: non-relocatable references found"; exit 1
fi

echo "==> Verifying vector.dylib links only relocatable paths"
otool -L "$VECTOR_DYLIB"

echo "PG_VERSION=$PG_VERSION PGVECTOR_VERSION=$PGVECTOR_VERSION ARCH=$ARCH" > "$BUILD/pgsql.stamp"
echo "==> Done: $OUT"
