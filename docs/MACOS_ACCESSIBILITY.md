# macOS GTK3 accessibility bridge

EasyHybrid3 stays on GTK3 on every platform. GTK3's Quartz backend does not
expose widgets to macOS Accessibility (VoiceOver, desktop automation), so an
optional native bridge in `platform/macos/gtk3_accessibility/` publishes the
GTK widgets (buttons, entries, menus, tabs, tables, combo boxes, dialogs) to
AppKit. It is loaded only on macOS with the GDK Quartz backend; Linux and
Windows never import it.

## Requirements (Apple Silicon)

- Homebrew: `gtk+3`, `at-spi2-core` (ATK), `glib`, `pygobject3`, `pkg-config`,
  Xcode Command Line Tools.
- Python 3.12 (arm64) with PyGObject (`gi`) importable and GTK 3.0 / Atk 1.0
  typelibs available.
- The module links Homebrew libraries by absolute `/opt/homebrew/opt/...`
  path; it is not self-contained. Build it on the machine that runs
  EasyHybrid3 (it is a build artifact and is git-ignored).

## Build

    EASYHYBRID3_PYTHON=/path/to/python3.12 platform/macos/gtk3_accessibility/build.sh

`EASYHYBRID3_PYTHON` must be the interpreter that runs EasyHybrid3 and that can
`import gi` (default: `python3.12` on `PATH`). The script checks for arm64,
Python 3.12 and GTK/Atk typelibs, and writes `_gtk3_accessibility.so`.

## Run

Start EasyHybrid3 normally (`python easyhybrid.py`). Accessibility initializes
automatically after the main window is shown. If the `.so` is missing, startup
continues without accessibility. macOS must grant the *client* tool
(VoiceOver, your automation app) Accessibility permission.

## Diagnostics and switches

| Variable | Effect |
|---|---|
| `EASYHYBRID3_DISABLE_AX=1` | Disable the bridge. |
| `EASYHYBRID3_AX_DIAGNOSTIC=1` | Log widget registration summaries. |
| `EASYHYBRID3_AX_DEBUG=1` | Verbose native trace on stderr (set-value, press). |

`tools/run-ax-audit.command` dumps the AX tree of a running instance
(`EASYHYBRID3_AX_PID`, `EASYHYBRID3_AX_TARGET=production`,
`EASYHYBRID3_AX_TARGET_ONLY=1`).

## Test-only hook

`tools/runtime_test_hook.py` runs only when both
`EASYHYBRID3_RUNTIME_TESTS=1` is set (done by `tools/run-milestone-3-3.command`)
and `EASYHYBRID3_TEST_HOOK` resolves to that exact file. Setting
`EASYHYBRID3_TEST_HOOK` alone does nothing.

## Troubleshooting

- *No AX tree*: check the `.so` exists, `EASYHYBRID3_DISABLE_AX` is unset,
  and run with `EASYHYBRID3_AX_DIAGNOSTIC=1` plus logging at INFO.
- *Build fails on `import gi`*: pass the venv interpreter via
  `EASYHYBRID3_PYTHON`.
- *Abort in `_RegisterApplication` at `Gtk.init`*: seen only when launched from
  a restricted/sandboxed process; launch from Terminal.
- *Native crash*: see below; capture the stack with
  `tools/capture-quartz-abort.lldb` or the report in
  `~/Library/Logs/DiagnosticReports/`.

## Known limitations / residual risk

- The historical GTK file chooser crash is not root-caused. It did not recur in
  20 production File→Open cycles, but remains a residual risk.
- Many icon-only buttons have no accessible name (GTK/Glade labels).
- ToolButtons are not registered (no ATK action on Quartz).
- Not a self-contained bundle: depends on Homebrew GTK3.
- AX events arriving off the main thread are queued to the main queue; this
  path was not exercised under a real VoiceOver session.
