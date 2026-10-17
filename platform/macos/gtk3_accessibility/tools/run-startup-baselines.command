#!/bin/zsh
set -u
cd /Users/shabir/software/EasyHybrid3
LOG=/private/tmp/easyhybrid3-startup-baselines.log
exec > >(tee "$LOG") 2>&1
echo "BASELINE timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "BASELINE cwd=$PWD"
echo "BASELINE python=$(/Users/shabir/software/chem312/bin/python -c 'import platform,sys; print(sys.executable, platform.machine(), sys.version.split()[0])')"
echo "BASELINE macOS=$(sw_vers -productVersion) build=$(sw_vers -buildVersion)"
echo "BASELINE gtk=$(pkg-config --modversion gtk+-quartz-3.0) gtk_lib=$(pkg-config --variable=libdir gtk+-quartz-3.0) gdk_lib=$(pkg-config --variable=libdir gdk-3.0)"
env | sort | grep -E '^(DYLD|GDK|GTK|DISPLAY|PYTHON|PATH|VIRTUAL_ENV|CONDA)' || true

run_case() {
  name="$1"
  shift
  echo "===== CASE $name: $* ====="
  "$@"
  case_status=$?
  echo "===== CASE $name EXIT=$case_status ====="
  newest=$(/bin/ls -t "$HOME"/Library/Logs/DiagnosticReports/Python-*.ips 2>/dev/null | head -1 || true)
  echo "===== CASE $name CRASH=$newest ====="
}

run_case minimal /Users/shabir/software/chem312/bin/python -u platform/macos/gtk3_accessibility/prototype/gtk3_minimal_startup.py
EASYHYBRID3_AX_AUTOCLOSE=1 run_case fixture /Users/shabir/software/chem312/bin/python -u platform/macos/gtk3_accessibility/prototype/gtk3_probe.py
EASYHYBRID3_DISABLE_AX=1 run_case easyhybrid-ax-disabled /Users/shabir/bin/easyhybrid3
echo "===== BASELINES COMPLETE ====="
