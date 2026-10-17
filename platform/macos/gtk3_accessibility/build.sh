#!/bin/zsh
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${EASYHYBRID3_PYTHON:-python3.12}"
PYTHON_INCLUDE="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("include"))')"
OUTPUT="platform/macos/gtk3_accessibility/_gtk3_accessibility.so"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The native GTK3 Quartz accessibility bridge can only be built on macOS." >&2
  exit 2
fi
if ! pkg-config --exists gtk+-quartz-3.0 pygobject-3.0; then
  echo "GTK3 Quartz and PyGObject development files are required." >&2
  exit 2
fi

"$PYTHON" -c 'import platform, sys, gi; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"; assert platform.machine() == "arm64", "Native arm64 Python required"; gi.require_version("Gtk", "3.0"); gi.require_version("Atk", "1.0"); from gi import _gi'
clang++ -arch arm64 -std=c++17 -fobjc-arc -bundle -undefined dynamic_lookup \
  $(pkg-config --cflags gtk+-quartz-3.0 pygobject-3.0) \
  -I"$PYTHON_INCLUDE" \
  platform/macos/gtk3_accessibility/bridge.mm \
  $(pkg-config --libs gtk+-quartz-3.0 pygobject-3.0) \
  -framework AppKit -framework ApplicationServices \
  -o "$OUTPUT"
printf 'Built %s\n' "$OUTPUT"
