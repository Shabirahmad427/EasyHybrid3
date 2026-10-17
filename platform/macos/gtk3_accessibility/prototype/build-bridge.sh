#!/bin/zsh
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${EASYHYBRID3_PYTHON:-python3.12}"
PYTHON_INCLUDE="$($PYTHON -c 'import sysconfig; print(sysconfig.get_path("include"))')"
OUTPUT="platform/macos/gtk3_accessibility/prototype/gtk3_ax_bridge.so"

clang++ -std=c++17 -fobjc-arc -bundle -undefined dynamic_lookup \
  $(pkg-config --cflags gtk+-quartz-3.0 pygobject-3.0) \
  -I"$PYTHON_INCLUDE" \
  platform/macos/gtk3_accessibility/prototype/gtk3_ax_bridge.mm \
  $(pkg-config --libs gtk+-quartz-3.0 pygobject-3.0) \
  -framework AppKit -framework ApplicationServices \
  -o "$OUTPUT"

printf 'Built %s\n' "$OUTPUT"
