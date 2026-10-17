#!/bin/zsh
set -eu
cd /Users/shabir/software/EasyHybrid3
EASYHYBRID3_AX_TARGET=production EASYHYBRID3_AX_READONLY=1 \
  /Users/shabir/software/EasyHybrid3/platform/macos/gtk3_accessibility/tools/run-ax-audit.command
