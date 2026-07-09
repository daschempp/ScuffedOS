#!/usr/bin/env bash
# Build the ScuffedOS.app on an Apple-Silicon Mac. Orchestrates: vendor
# Postgres+pgvector, vendor Python, build the launcher stub, render the icon,
# build the frontend, and cargo tauri build. Unsigned by default; first
# launch requires a one-time right-click > Open (quarantine). If
# APPLE_SIGNING_IDENTITY is set, an optional final stage signs, notarizes,
# and staples the app via scripts/sign-notarize.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
TRIPLE="aarch64-apple-darwin"

# cargo / cargo-tauri live under ~/.cargo/bin, which may not be on PATH in a
# non-interactive shell.
if ! command -v cargo >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
fi

echo "==> [1/7] Vendor Postgres + pgvector"
bash "$ROOT/scripts/vendor-postgres.sh"

echo "==> [2/7] Vendor Python env"
bash "$ROOT/scripts/vendor-python.sh"

echo "==> [3/7] Build the launcher stub (target-triple-suffixed externalBin)"
( cd "$ROOT/src-tauri/launcher" && cargo build --release )
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/src-tauri/launcher/target/release/scuffedos-backend" \
   "$ROOT/src-tauri/binaries/scuffedos-backend-${TRIPLE}"
codesign --force -s - "$ROOT/src-tauri/binaries/scuffedos-backend-${TRIPLE}"

echo "==> [4/7] Render icon (logo-mark.svg -> 1024 PNG -> .icns)"
SRC_SVG="$ROOT/frontend/public/assets/logo-mark.svg"
FALLBACK_PNG="$ROOT/src-tauri/icons/icon.png"
ICONSET="$BUILD/ScuffedOS.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET" "$ROOT/src-tauri/icons"

mkdir -p "$BUILD"
ICON_SRC_PNG="$BUILD/icon-1024.png"
rm -f "$ICON_SRC_PNG"

render_ok=false
if command -v rsvg-convert >/dev/null 2>&1 && [ -f "$SRC_SVG" ]; then
  echo "    using rsvg-convert"
  rsvg-convert -w 1024 -h 1024 "$SRC_SVG" -o "$ICON_SRC_PNG"
  render_ok=true
elif command -v qlmanage >/dev/null 2>&1 && [ -f "$SRC_SVG" ]; then
  # rsvg-convert / cairosvg / inkscape / magick are all unavailable on this
  # machine. qlmanage -t thumbnails the SVG but does NOT scale vector content
  # to fill the requested canvas -- a 48x48 logo-mark.svg renders into only
  # the source's native pixel footprint in the top-left corner of a 1024x1024
  # canvas, padded with opaque white. Auto-crop to the non-white content bbox
  # first, then let sips upscale the crop to fill the icon frame.
  echo "    using qlmanage + autocrop (rsvg-convert/cairosvg/inkscape/magick unavailable)"
  QLDIR="$BUILD/_ql"
  rm -rf "$QLDIR"; mkdir -p "$QLDIR"
  qlmanage -t -s 1024 -o "$QLDIR" "$SRC_SVG" >/dev/null 2>&1 || true
  QL_OUT="$QLDIR/$(basename "$SRC_SVG").png"
  if [ -f "$QL_OUT" ] && python3 "$ROOT/scripts/_png_autocrop.py" "$QL_OUT" "$BUILD/icon-cropped.png"; then
    sips -z 1024 1024 "$BUILD/icon-cropped.png" --out "$ICON_SRC_PNG" >/dev/null
  fi
fi

# Validate the rendered PNG is non-degenerate (qlmanage can silently emit a
# tiny/blank placeholder for some SVGs). Require it to actually be ~1024px.
if [ -f "$ICON_SRC_PNG" ]; then
  DIM="$(sips -g pixelWidth -g pixelHeight "$ICON_SRC_PNG" 2>/dev/null | awk '/pixelWidth|pixelHeight/{print $2}' | sort -u)"
  MINDIM="$(echo "$DIM" | sort -n | head -1)"
  if [ -n "$MINDIM" ] && [ "$MINDIM" -ge 512 ] 2>/dev/null; then
    render_ok=true
  else
    render_ok=false
  fi
fi

if [ "$render_ok" = true ] && [ -f "$ICON_SRC_PNG" ]; then
  echo "    rendered icon source: $ICON_SRC_PNG"
else
  echo "WARN: SVG rasterization unavailable/degenerate; falling back to placeholder $FALLBACK_PNG"
  test -f "$FALLBACK_PNG" || { echo "FATAL: no fallback icon at $FALLBACK_PNG"; exit 1; }
  cp "$FALLBACK_PNG" "$ICON_SRC_PNG"
fi

for s in 16 32 64 128 256 512 1024; do
  sips -z "$s" "$s" "$ICON_SRC_PNG" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  h=$((s*2))
  if [ "$h" -le 1024 ]; then
    sips -z "$h" "$h" "$ICON_SRC_PNG" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  fi
done
iconutil -c icns "$ICONSET" -o "$ROOT/src-tauri/icons/icon.icns"

echo "==> [5/7] Build frontend"
( cd "$ROOT/frontend" && npm ci && npm run build )

echo "==> [6/7] cargo tauri build (.app only)"
( cd "$ROOT/src-tauri" && cargo tauri build --bundles app )

APP="$ROOT/src-tauri/target/release/bundle/macos/ScuffedOS.app"

if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
  echo "==> [7/7] Sign + notarize (APPLE_SIGNING_IDENTITY set)"
  bash "$ROOT/scripts/sign-notarize.sh" "$APP"
else
  echo "==> [7/7] Skipping sign + notarize (APPLE_SIGNING_IDENTITY unset) — unsigned build"
fi

echo "==> Done. App at: $APP"
du -sh "$APP" || true
