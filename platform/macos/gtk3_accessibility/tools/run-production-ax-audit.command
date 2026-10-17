#!/bin/zsh
set -eu
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"
EASYHYBRID3_AX_TARGET=production EASYHYBRID3_AX_READONLY=1 \
  "$ROOT/platform/macos/gtk3_accessibility/tools/run-ax-audit.command"
