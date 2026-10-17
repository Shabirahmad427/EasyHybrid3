#!/bin/zsh
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ "$#" -ne 2 ]]; then
  print -u2 "Usage: $0 CURRENT_FIELD_VALUE NEW_FIELD_VALUE"
  print -u2 "Open Import New System in EasyHybrid3 first, then pass a unique current value."
  exit 2
fi

CURRENT_VALUE="$1"
NEW_VALUE="$2"
TARGET_PID="$(/usr/bin/pgrep -n -f '[e]asyhybrid.py' || true)"
if [[ -z "$TARGET_PID" ]]; then
  print -u2 "EasyHybrid3 is not running. Start it with run-easyhybrid-ax.command in Terminal."
  exit 1
fi

printf 'Auditing entry edit in EasyHybrid3 PID %s\n' "$TARGET_PID"
EASYHYBRID3_AX_TARGET=production \
EASYHYBRID3_AX_TARGET_ONLY=1 \
EASYHYBRID3_AX_SET_FROM_VALUE="$CURRENT_VALUE" \
EASYHYBRID3_AX_SET_VALUE="$NEW_VALUE" \
EASYHYBRID3_AX_READONLY=1 \
EASYHYBRID3_AX_PID="$TARGET_PID" \
platform/macos/gtk3_accessibility/tools/run-ax-audit.command

printf '\nBridge callback trace (if available):\n'
/usr/bin/grep -E 'set-value|gtk-editable-changed|atk-editable' \
  /private/tmp/easyhybrid3-production-ax.log || true
