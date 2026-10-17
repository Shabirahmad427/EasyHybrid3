#!/bin/zsh
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO_ROOT"
platform/macos/gtk3_accessibility/prototype/build-bridge.sh
printf 'Starting GTK3 Quartz fixture with only the AppKit launch lifecycle experiment.\n'
EASYHYBRID3_AX_FINISH_LAUNCHING=1 \
  /Users/shabir/software/chem312/bin/python -u \
  platform/macos/gtk3_accessibility/prototype/gtk3_probe.py \
  2>&1 | /usr/bin/tee /private/tmp/easyhybrid3-gtk3-finish-only.log
