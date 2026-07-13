#!/usr/bin/env bash
# Developer-ID codesign + notarize + staple a built ScuffedOS.app. Invoked by
# build-app.sh's [7/7] stage ONLY when APPLE_SIGNING_IDENTITY is set. Signs
# every nested Mach-O deepest-first with the hardened runtime + entitlements,
# then submits to Apple's notary service and staples the ticket.
#
# Required env:
#   APPLE_SIGNING_IDENTITY         e.g. "Developer ID Application: Dylan Schempp (TEAMID)"
#   APPLE_NOTARY_KEYCHAIN_PROFILE  a profile stored via `xcrun notarytool store-credentials`
set -euo pipefail

APP="${1:?usage: sign-notarize.sh /path/to/ScuffedOS.app}"
IDENT="${APPLE_SIGNING_IDENTITY:?APPLE_SIGNING_IDENTITY not set}"
PROFILE="${APPLE_NOTARY_KEYCHAIN_PROFILE:?APPLE_NOTARY_KEYCHAIN_PROFILE not set}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENTITLEMENTS="$ROOT/src-tauri/entitlements.plist"

sign() { codesign --force --timestamp --options runtime \
                  --entitlements "$ENTITLEMENTS" -s "$IDENT" "$1"; }

echo "==> Signing nested Mach-Os (deepest first)"
# 1. Leaf shared libraries under Resources (py + pgsql trees).
find "$APP/Contents/Resources" \( -name '*.dylib' -o -name '*.so' \) -type f -print0 \
  | while IFS= read -r -d '' f; do sign "$f"; done
# 2. Mach-O executables under Resources (python3, postgres, initdb, psql, ...).
# -perm -u+x (owner-exec bit set) catches 700/750/755 alike; -perm -111 would
# require all three exec bits and silently skip an owner-only-exec binary.
find "$APP/Contents/Resources" -type f -perm -u+x ! -name '*.dylib' ! -name '*.so' -print0 \
  | while IFS= read -r -d '' f; do
      if file "$f" | grep -q 'Mach-O'; then sign "$f"; fi
    done
# 3. The sidecar launcher + the main app binary.
sign "$APP/Contents/MacOS/scuffedos-backend"
sign "$APP/Contents/MacOS/scuffedos"
# 4. The bundle itself, last.
sign "$APP"

echo "==> Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> Notarizing (zip -> submit --wait -> staple)"
ZIP="${APP%.app}.zip"
rm -f "$ZIP"
/usr/bin/ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$APP"
rm -f "$ZIP"

echo "==> Signed + notarized: $APP"
