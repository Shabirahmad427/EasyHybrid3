#!/bin/zsh
set -u

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
PYTHON="${EASYHYBRID3_PYTHON:-python3.12}"
RUN_DIR="/private/tmp/easyhybrid3-m33-$(/bin/date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
cd "$ROOT" || exit 2

exec > >(tee -a "$RUN_DIR/session.log") 2>&1
print "EasyHybrid3 Milestone 3.3 runtime verification"
print "RUN_DIR=$RUN_DIR"
print "STARTED=$(date '+%Y-%m-%dT%H:%M:%S%z')"
print "HOST=$(/usr/bin/sw_vers -productVersion) ARCH=$(uname -m)"
print "PYTHON=$PYTHON"
print "DISPLAY=${DISPLAY:-<unset>}"
print "PYTHONPATH=${PYTHONPATH:-<unset>}"

# Optional test-only hook runs inside the actual EasyHybrid process after its
# production window and callbacks exist. The app imports this hook only when
# EASYHYBRID3_TEST_HOOK names a module file.
TEST_HOOK="${EASYHYBRID3_TEST_HOOK:-}"
if [[ -n "$TEST_HOOK" ]]; then
  export EASYHYBRID3_RUNTIME_TESTS=1
  export EASYHYBRID3_TEST_HOOK="$TEST_HOOK"
  print "TEST_HOOK=$TEST_HOOK"
fi

CRASH_DIR="$HOME/Library/Logs/DiagnosticReports"
/usr/bin/find "$CRASH_DIR" -maxdepth 1 -type f -iname '*python*' -print 2>/dev/null | /usr/bin/sort > "$RUN_DIR/crash-reports-before.txt"

platform/macos/gtk3_accessibility/build.sh || exit 10
clang -fobjc-arc -Wall -Wextra -framework AppKit -framework ApplicationServices \
  -framework Security platform/macos/gtk3_accessibility/tools/ax-audit.m \
  -o "$RUN_DIR/easyhybrid3-ax-audit" || exit 11

if [[ "${EASYHYBRID3_M33_DISABLED:-0}" == "1" ]]; then
  export EASYHYBRID3_DISABLE_AX=1
  unset EASYHYBRID3_AX_DEBUG
  print "ACCESSIBILITY=disabled"
else
  unset EASYHYBRID3_DISABLE_AX
  export EASYHYBRID3_AX_DIAGNOSTIC=1
  export EASYHYBRID3_AX_DEBUG=1
  print "ACCESSIBILITY=enabled"
fi

if [[ -n "$TEST_HOOK" ]]; then
  export EASYHYBRID3_TEST_HOOK_MODE="${EASYHYBRID3_TEST_HOOK_MODE:-dialogs}"
  export EASYHYBRID3_TEST_HOOK_CYCLES="${EASYHYBRID3_TEST_HOOK_CYCLES:-20}"
  export EASYHYBRID3_TEST_HOOK_LOG="${EASYHYBRID3_TEST_HOOK_LOG:-$RUN_DIR/gtk-test-hook.log}"
fi

print "Launching production app; close the app window or press Ctrl-C here to end this run."
"$PYTHON" -X faulthandler -u easyhybrid.py >"$RUN_DIR/application.log" 2>&1 &
APP_PID=$!
print "APP_PID=$APP_PID"
print "$APP_PID" > "$RUN_DIR/app.pid"

for attempt in {1..120}; do
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    print "APP_EXITED_BEFORE_READY=yes"
    break
  fi
  if /usr/bin/grep -q "event=finish-launching\|accessibility registered" "$RUN_DIR/application.log" 2>/dev/null; then
    break
  fi
  if [[ -n "$TEST_HOOK" ]] && /usr/bin/grep -q "HOOK_START" "${EASYHYBRID3_TEST_HOOK_LOG:-$RUN_DIR/gtk-test-hook.log}" 2>/dev/null; then
    break
  fi
  sleep 1
done
print "READY_CHECK $(date '+%Y-%m-%dT%H:%M:%S%z')"
/bin/cat "$RUN_DIR/application.log"

if kill -0 "$APP_PID" 2>/dev/null && [[ "${EASYHYBRID3_M33_DISABLED:-0}" != "1" && -z "$TEST_HOOK" ]]; then
  CYCLES="${EASYHYBRID3_M33_CYCLES:-3}"
  print "Running native AX dialog/edit cycles: $CYCLES"
  EASYHYBRID3_AX_TARGET=production EASYHYBRID3_AX_PID="$APP_PID" \
    EASYHYBRID3_AX_AUDIT_BIN="$RUN_DIR/easyhybrid3-ax-audit" \
    EASYHYBRID3_AX_TARGET_ONLY=1 \
    EASYHYBRID3_AX_DIALOG_CYCLES="$CYCLES" EASYHYBRID3_AX_READONLY=1 \
    "$ROOT/platform/macos/gtk3_accessibility/tools/run-ax-audit.command" \
    2>&1 | tee "$RUN_DIR/ax-cycles.log"
  if /usr/bin/grep -q "DIALOG_TEST_RESULT=PASS" "$RUN_DIR/ax-cycles.log"; then
    print "AUTOMATED_AX_RESULT=PASS"
  else
    print "AUTOMATED_AX_RESULT=FAIL"
  fi
fi

print "Application remains available for visual project, menu, shortcut and window checks."
print "Press Ctrl-C here to request normal Terminal interrupt, or close EasyHybrid3 normally."
wait "$APP_PID"
APP_STATUS=$?
print "APP_TERMINATED=$(date '+%Y-%m-%dT%H:%M:%S%z')"
print "APP_WAIT_STATUS=$APP_STATUS"
/bin/cat "$RUN_DIR/application.log"

print "Crash reports created during run:"
/usr/bin/find "$CRASH_DIR" -maxdepth 1 -type f -iname '*python*' -print 2>/dev/null | /usr/bin/sort > "$RUN_DIR/crash-reports-after.txt"
/usr/bin/comm -13 "$RUN_DIR/crash-reports-before.txt" "$RUN_DIR/crash-reports-after.txt" | tee "$RUN_DIR/crash-reports.txt"
if [[ -s "$RUN_DIR/crash-reports.txt" ]]; then
  print "CRASH_REPORTS=NEW_REPORTS_FOUND"
else
  print "CRASH_REPORTS=none"
fi
print "Final process state:"
/bin/ps -p "$APP_PID" -o pid=,stat=,command= || true
print "RESULT_DIR=$RUN_DIR"
if [[ -n "$TEST_HOOK" ]]; then
  /bin/cat "$EASYHYBRID3_TEST_HOOK_LOG"
  if [[ ! -s "$EASYHYBRID3_TEST_HOOK_LOG" ]] || /usr/bin/grep -q 'exception=\|DIALOG_TEST_RESULT=FAIL' "$EASYHYBRID3_TEST_HOOK_LOG"; then
    exit 12
  fi
fi
exit "$APP_STATUS"
