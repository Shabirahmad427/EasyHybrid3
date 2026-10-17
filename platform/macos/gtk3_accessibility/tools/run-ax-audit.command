#!/bin/zsh
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO_ROOT"

AX_AUDIT_BIN="${EASYHYBRID3_AX_AUDIT_BIN:-/private/tmp/easyhybrid3-ax-audit}"
if [[ ! -x "$AX_AUDIT_BIN" ]]; then
  clang -fobjc-arc -Wall -Wextra \
    -framework AppKit -framework ApplicationServices -framework Security \
    platform/macos/gtk3_accessibility/tools/ax-audit.m \
    -o "$AX_AUDIT_BIN"
fi

TARGET_PID="${EASYHYBRID3_AX_PID:-$(/usr/bin/pgrep -n -f '[g]tk3_probe.py' || true)}"
TARGET_LABEL="GTK-fixture"
if [[ "${EASYHYBRID3_AX_TARGET:-}" == "production" ]]; then
  TARGET_PID="$(/usr/bin/pgrep -n -f '[e]asyhybrid.py' || true)"
  TARGET_LABEL="EasyHybrid3-production"
fi
if [[ -z "$TARGET_PID" ]]; then
  TARGET_PID="$(/usr/bin/pgrep -n -f '[e]asyhybrid.py' || true)"
  TARGET_LABEL="EasyHybrid3-production"
fi
printf 'AX target PID: %s (%s)\n' "${TARGET_PID:-not-found}" "$TARGET_LABEL"
AX_ARGS=(--prompt --pid "${TARGET_PID:-0}")
if [[ "${EASYHYBRID3_AX_TARGET_ONLY:-0}" == "1" ]]; then
  AX_ARGS+=(--target-only)
fi
if [[ "${EASYHYBRID3_AX_ACTIVATE:-0}" == "1" ]]; then
  AX_ARGS+=(--activate)
fi
if [[ -n "${EASYHYBRID3_AX_DIALOG_CYCLES:-}" ]]; then
  AX_ARGS+=(--dialog-cycles "$EASYHYBRID3_AX_DIALOG_CYCLES")
fi
if [[ -n "${EASYHYBRID3_AX_SET_FROM_VALUE:-}" && -n "${EASYHYBRID3_AX_SET_VALUE:-}" ]]; then
  AX_ARGS+=(--set-from-value "$EASYHYBRID3_AX_SET_FROM_VALUE" --set-value "$EASYHYBRID3_AX_SET_VALUE")
fi
if [[ "${EASYHYBRID3_AX_READONLY:-0}" == "1" ]]; then
  "$AX_AUDIT_BIN" "${AX_ARGS[@]}" \
    2>&1 | /usr/bin/tee /private/tmp/easyhybrid3-ax-audit.log
elif [[ -n "${EASYHYBRID3_AX_PRESS_LABEL:-}" ]]; then
  "$AX_AUDIT_BIN" "${AX_ARGS[@]}" \
    --press-label "$EASYHYBRID3_AX_PRESS_LABEL" \
    2>&1 | /usr/bin/tee /private/tmp/easyhybrid3-ax-audit.log
elif [[ -n "${EASYHYBRID3_AX_SET_FROM_VALUE:-}" && -n "${EASYHYBRID3_AX_SET_VALUE:-}" ]]; then
  "$AX_AUDIT_BIN" "${AX_ARGS[@]}" \
    2>&1 | /usr/bin/tee /private/tmp/easyhybrid3-ax-audit.log
else
  "$AX_AUDIT_BIN" "${AX_ARGS[@]}" --press-first-button \
  2>&1 | /usr/bin/tee /private/tmp/easyhybrid3-ax-audit.log
fi
printf '\nAX audit output saved to /private/tmp/easyhybrid3-ax-audit.log\n'
