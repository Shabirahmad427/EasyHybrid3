#!/bin/zsh
set -eu
cd /Users/shabir/software/EasyHybrid3
EASYHYBRID3_AX_DIAGNOSTIC=1 /Users/shabir/bin/easyhybrid3 "$@" 2>&1 | /usr/bin/tee /private/tmp/easyhybrid3-production-ax.log
