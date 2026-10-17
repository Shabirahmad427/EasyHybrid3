#!/bin/zsh
set -eu
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PYTHON="${EASYHYBRID3_PYTHON:-python3.12}"
exec "$PYTHON" "$ROOT/easyhybrid.py" "$@"
