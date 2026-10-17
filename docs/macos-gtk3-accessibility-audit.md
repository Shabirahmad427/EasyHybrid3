# EasyHybrid3 GTK3 Quartz accessibility audit

**Milestone 2 result: PASS for the isolated proof of concept. Milestone 3 result: PARTIAL. Milestone 3.1 startup recovery: PASS in Terminal; AX control integration: PARTIAL.** The earlier statement that production had no live window is superseded by the live Terminal baseline and production AX results below. The GTK3 Quartz application starts normally from Terminal with AX enabled or disabled. A separate bridge logging bug caused an AX-enabled run to crash during widget registration; the invalid Objective-C format argument was fixed. Native AX discovers and activates real EasyHybrid3 buttons and dynamically created dialog controls. AX text reads work; writing text is not yet verified.

## Runtime and machine

Observed on 2026-10-16:

| Component | Observed value |
|---|---|
| macOS | 27.0.1 (build 26A434) |
| Architecture | arm64 |
| Python | 3.12.15 ARM64, `/Users/shabir/software/chem312/bin/python` |
| PyGObject | 3.58.1 |
| GTK | 3.24.52, Quartz backend |
| GLib | 2.90.1 |
| ATK | 2.62.0.1 |
| GTK library | `/opt/homebrew/Cellar/gtk+3/3.24.52_1/lib/libgtk-3.0.dylib` |
| GDK library | `/opt/homebrew/Cellar/gtk+3/3.24.52_1/lib/libgdk-3.0.dylib` |

## Permission validation

`ax-audit.m` calls `AXIsProcessTrustedWithOptions` and prints the client identity and each AX error. When run directly from Terminal, it reported:

```text
CLIENT trusted=yes pid=43154 bundle=<none> name=<none> signed=easyhybrid3-ax-audit
```

The helper successfully queried both System Settings and Finder, including their application roles, window lists, child hierarchies, and supported button actions. For System Settings, the AX window query returned `success(0)` and 145 buttons were counted. This validates that the client had working cross-process AX access before drawing conclusions about GTK. Terminal.app was already enabled under System Settings → Privacy & Security → Accessibility (shown as Device Control and Data Access on this macOS build); no TCC database or permission setting was changed.

The helper is a standalone executable with no bundle identifier. Its code-signing information reports the identifier `easyhybrid3-ax-audit`; the observed trusted context was Terminal. A prior launch from the Codex context reported untrusted and was denied (`osascript is not allowed assistive access`, `-25211`). That was a client-context permission denial, distinct from the target app's `kAXErrorCannotComplete (-25204)` before the AppKit bridge changes below. No special AX permission is needed by EasyHybrid3 just to be inspected; the inspecting client needs trust.

## GTK3 fixture baseline

`prototype/gtk3_probe.py` creates a real GTK3 Quartz window containing a button, entry, checkbox, combo box, and menu item. Before the native bridge, PyGObject reported these ATK objects:

| Widget | ATK role | Interfaces confirmed at runtime |
|---|---|---|
| Window | frame | `AtkComponent` |
| Button | button | `AtkAction`, `AtkComponent` |
| Entry | text | `AtkAction`, `AtkComponent`, `AtkText`, `AtkEditableText` |
| Checkbox | check-box | `AtkAction`, `AtkComponent` |
| Combo box | combo-box | `AtkAction`, `AtkComponent`, `AtkSelection` |
| Menu item | menu-item | `AtkAction`, `AtkComponent`, `AtkSelection` |

The AX client discovered the fixture by the actual PID printed by `pgrep`. Before calling the bridge's AppKit launch hook, CoreGraphics showed the visible native GTK window, but `AXUIElementCreateApplication(pid)` returned `APP_ROLE=AXApplication`, `APP_TITLE=Python`, and `WINDOWS error=cannot-complete(-25204)`. This was not an AX client trust failure: the same run successfully queried Finder and System Settings.

Calling `NSApp finishLaunching` alone changed the result: the external AX client could then enumerate the native GTK window and its three standard window-control buttons, but the GTK button remained absent (`TARGET_BUTTON_FOUND=no`). Therefore the fixture demonstrated two separate requirements: initializing the AppKit application endpoint exposes the native application/window, and an accessibility child adapter is required to expose the GTK child control. The fixture's GTK button had a valid ATK action before this exposure.

## Minimal bridge and external verification

`prototype/gtk3_ax_bridge.mm` is an Objective-C++ Python extension used only by the fixture. It obtains the actual `GdkQuartzNSWindow` and `GdkQuartzView` using GDK Quartz's exported `gdk_quartz_window_get_nswindow()` and `gdk_quartz_window_get_nsview()` functions. It reads the existing button's `AtkAction`, `AtkComponent`, role, name, and state, then publishes an `NSAccessibilityElement` child through the actual `GdkQuartzView` accessibility children. Its AXPress handler queues `atk_action_do_action()` onto the GTK main context; it does not create another window or synthesize coordinates.

Build and run from the repository:

```sh
platform/macos/gtk3_accessibility/prototype/build-bridge.sh
platform/macos/gtk3_accessibility/prototype/run-probe.command
```

The first run command compiles the extension with the installed ARM64 Python/PyGObject and GTK3 Quartz headers and libraries. The fixture printed:

```text
NATIVE_BRIDGE window=... window-class=GdkQuartzNSWindow view=... view-class=GdkQuartzView role=AXButton label=Run accessible button frame={{16.0,841.0},{488.0,34.0}}
```

Run the native AX audit from Terminal, which is the trusted responsible application:

```sh
platform/macos/gtk3_accessibility/tools/run-ax-audit.command
```

The helper compiled with Apple Clang 21.0.0, confirmed `CLIENT trusted=yes`, queried System Settings and Finder successfully, then discovered the fixture by PID. The resulting external hierarchy included:

```text
APP_ROLE=AXApplication APP_TITLE=Python
WINDOWS error=success(0)
NODE role=AXButton title=Run accessible button description=Run accessible button value=<attribute-unsupported:-25205> enabled=1
TARGET position={{16, 841}} size={488, 34}
TARGET_BUTTON_FOUND=yes
AXPRESS error=success(0)
```

The audit then invoked `AXPress` again after the fixture hid and re-showed its window. It found the button again and closed the fixture via the same action:

```text
LIFECYCLE phase=hidden windows-error=success(0) count=0
LIFECYCLE phase=shown windows-error=success(0) count=1
LIFECYCLE button-after-show=found
AXPRESS_CLOSE error=success(0)
AFTER_CLOSE windows-error=cannot-complete(-25204)
CGWINDOW_MATCHES=0
```

The helper process completed normally after close; `cannot-complete` on the post-close query is the expected response from the terminated target. The GTK fixture log independently confirmed the action reached its existing callback:

```text
ACTION button-pressed count=1
LIFECYCLE window-hidden
LIFECYCLE window-shown
ACTION button-pressed count=2
LIFECYCLE window-closed
```

This is external native Accessibility API evidence, not just ATK introspection or successful compilation. The actual desktop bridge was not verified in this milestone; its separate Python-process attachment timeout is not evidence against this direct native AX result.

## Source files added

- `platform/macos/gtk3_accessibility/tools/ax-audit.m` — trusted native AX diagnostic and lifecycle/action test client.
- `platform/macos/gtk3_accessibility/tools/run-ax-audit.command` — builds and runs the native client against the current fixture PID.
- `platform/macos/gtk3_accessibility/prototype/gtk3_probe.py` — isolated GTK3 Quartz fixture and callback logging.
- `platform/macos/gtk3_accessibility/prototype/gtk3_ax_bridge.mm` — minimal ATK-to-NSAccessibility button adapter.
- `platform/macos/gtk3_accessibility/prototype/build-bridge.sh` — reproducible local extension build command.
- `platform/macos/gtk3_accessibility/prototype/run-probe.command` — builds and launches the fixture.
- `platform/macos/gtk3_accessibility/prototype/run-finish-only.command` — comparison run isolating `finishLaunching` from the child adapter.

No production EasyHybrid3 startup, GUI, scientific, project, or simulation files were changed. No system GTK3 library was modified.

## Technical finding and limits

The installed GTK3 Quartz headers publicly expose the native `NSWindow` and `NSView`, so a fixture-local adapter can attach a real accessibility child without a GTK fork. However, source inspection of GTK 3.24.52's Quartz backend shows that GTK creates/uses `NSApplication` but leaves `NSApp finishLaunching` commented out in the startup-completion path. The source comment says enabling it encounters `_createMenuRef called with existing principal MenuRef already associated with menu`. In this fixture, explicitly calling it after GTK window/menu construction exposed the app/window AX endpoint and caused no observed crash or menu error. The finish-only test showed that it did not itself expose the GTK child.

The fixture's AX child adapter is deliberately narrow: one button, one screen, one action; it is not broad widget support. The current implementation depends on the GTK main context being serviced, uses a GTK Quartz/AppKit launch-hook call, and does not establish safety for every EasyHybrid3 menu, multiple windows, arbitrary AX callback threads, or the molecular canvas. Full EasyHybrid3 integration is not authorized by the requested Phase 2 scope and would require a separate, careful AppKit startup/menu compatibility investigation. The desktop bridge has also not yet been verified against this adapter.

## Milestone 2 classification

**PASS — isolated GTK3 Quartz button proof of concept.** The acceptance criterion is met: a trusted external AX client discovered the real fixture GTK button, verified role/label/action and screen frame, invoked it, observed the GTK callback, repeated successfully after hide/show, and survived fixture shutdown. This does not mean production EasyHybrid3 accessibility is implemented or tested.

## Milestone 3 work and verification (2026-10-16)

### Startup inspection

The production entry point remains `easyhybrid.py`. On macOS it disables PyGObject legacy auto-init, imports GTK/GDK 3, and explicitly calls `Gtk.init([])` at line 199. It uses `Gtk.main()` rather than `GtkApplication`. The application constructs `EasyHybridSession` and its molecular viewer, inserts the viewer's GTK menus, creates `MainWindow` from `src/gui/MainWindow.glade`, builds a large GTK menu tree and multiple dialogs, presents the actual main window, then enters the GTK loop. The accessibility hook is scheduled through `GLib.idle_add` after the existing startup callback has created the window and completed optional project loading.

The only observed `finishLaunching` test remains the isolated fixture: it exposed the application/window AX endpoint when called after fixture GTK menus and window creation. GTK Quartz source carries an upstream comment that calling it can collide with the principal MenuRef. EasyHybrid3's production menu bar, viewer menus, key handlers, and window activation could not be checked because the production process aborted earlier at GTK initialization. No claim is made that production menu behavior is safe after the call.

### Reusable module added

- `platform/macos/gtk3_accessibility/bridge.mm` — reusable Objective-C++ Python extension. It obtains the actual GDK Quartz `NSWindow`/`NSView`, adapts existing ATK accessible objects, installs native AX children on the real view, queues ATK actions and editable entry value changes on the GTK context, de-duplicates registrations per GTK widget, and removes the AX child on GTK widget destruction.
- `platform/macos/gtk3_accessibility/bootstrap.py` — platform-guarded optional initializer, Quartz display check, main-window registration, diagnostic logging, disable switch (`EASYHYBRID3_DISABLE_AX=1`), and periodic discovery of new top-level GTK windows/controls.
- `platform/macos/gtk3_accessibility/build.sh` — local ARM64 build against the current Python/PyGObject and GTK3 Quartz ABI. It writes `_gtk3_accessibility.so` beside the module; that generated artifact is not part of the source deliverable.
- `platform/macos/gtk3_accessibility/run-easyhybrid-ax.command` and `tools/run-production-ax-audit.command` — local launch and read-only native audit helpers.
- `easyhybrid.py` — schedules the macOS-only initializer after GTK window/menu construction; Linux code path is unchanged.
- `prototype/gtk3_probe.py` and `prototype/run-probe.command` — fixture adjusted to exercise the reusable module.

The adapter currently maps labels, buttons/tool buttons, check/radio buttons, entries, combo boxes, spin buttons, notebooks, tree views, menu items, and dialogs to native roles. Button/menu actions use `AtkAction`; entry text has a queued writable AX value path backed by `AtkEditableText`. Notebook page relationships, tree rows/selections, combo selection actions, menu-bar integration, focus notifications, and complete role/state/event mapping remain incomplete and unverified. The AX children are currently attached as native view children; complex GTK descendants are not recursively reconstructed as native parent-child containers.

### Commands and results

Build:

```sh
platform/macos/gtk3_accessibility/build.sh
```

Result: compiled successfully with Apple Clang against GTK 3.24.52 Quartz and the installed PyGObject headers. `python3 -m py_compile platform/macos/gtk3_accessibility/bootstrap.py easyhybrid.py` passed. `git diff --check` passed.

Production launch attempts:

```sh
/Users/shabir/software/chem312/bin/python -X faulthandler -u easyhybrid.py
EASYHYBRID3_DISABLE_AX=1 /Users/shabir/software/chem312/bin/python -u easyhybrid.py
```

Both exited with status 134 before the accessibility hook. Python reported the top frame at `easyhybrid.py:199` (`Gtk.init([])`). The macOS crash report's native stack was `gtk_init` → `_gdk_quartz_display_open` → `gdk_quartz_display_class_intern_init` → `TransformProcessType` → `_RegisterApplication` → `abort`. A standalone GTK3 fixture without the new module did run and printed its ATK baseline, confirming the installed runtime can launch a small GTK Quartz program in at least one process context. The audit helper remained trusted and continued to query Finder and System Settings, but no production Python PID was available for an AX hierarchy query.

The reusable extension compiled, but it was not successfully loaded into a running production EasyHybrid3 window. The updated reusable-module fixture could not be used as a fresh process after the production launch attempts began aborting in `Gtk.init`; therefore no new AXPress or entry-edit evidence is claimed for this module. Milestone 2's AXPress evidence applies to the earlier prototype implementation only.

### Milestone 3 classification: PARTIAL

The implementation skeleton and startup hook exist. Production buttons and dynamic dialogs are now verified through native AX, but editable text, menu/shortcut regression, molecular rendering, project loading, and full lifecycle reliability remain incomplete.

## Milestone 3.1 startup and production AX results (2026-10-16)

### Startup baseline and diagnosis

The first `run-startup-baselines.command` invocation stopped after the minimal case because zsh's read-only `status` variable was used by the script. The script was corrected to use `case_status`. The user's subsequent Terminal output and follow-up checks were performed from the same Terminal session, working directory, Python environment, and GTK installation:

| Case | Command/configuration | Observed result |
|---|---|---|
| Minimal GTK3 Quartz | `/Users/shabir/software/chem312/bin/python -u platform/macos/gtk3_accessibility/prototype/gtk3_minimal_startup.py` | `GdkQuartzDisplay`; exit 0 |
| Milestone 2 fixture | `EASYHYBRID3_AX_AUTOCLOSE=1 /Users/shabir/software/chem312/bin/python -u platform/macos/gtk3_accessibility/prototype/gtk3_probe.py` | ATK widgets discovered; auto-close; exit 0 |
| Production, AX disabled | `EASYHYBRID3_DISABLE_AX=1 /Users/shabir/bin/easyhybrid3` | Main `EasyHybrid 3.1.3` window appeared and process remained in `Gtk.main()`; user AX audit returned `cannot-complete (-25204)` because the AX hook was intentionally disabled |
| Production, AX enabled | `platform/macos/gtk3_accessibility/run-easyhybrid-ax.command` run from Terminal | GTK3 app stayed alive, registered its window/widgets, and appeared in native AX |

Runtime: macOS 27.0.1 build 26A434, arm64, Python 3.12.15 ARM64, GTK/GDK Quartz 3.24.52, GLib 2.90.1, ATK 2.62.0.1, PyGObject 3.58.1. GTK and GDK were loaded from `/opt/homebrew/Cellar/gtk+3/3.24.52_1/lib`. The Terminal baseline recorded `DISPLAY=/var/run/com.apple.launchd.x6G4nk6zeF/org.xquartz:0`, repeated AmberTools Python 3.11 entries in `PYTHONPATH`, and no `DYLD_*`, `GDK_*`, or `GTK_*` overrides. The working directory was `/Users/shabir/software/EasyHybrid3`.

Earlier exit-134 reports came from GTK startup launched inside Codex's sandboxed shell. Their stack was `gtk_init` → `_gdk_quartz_display_open` → `TransformProcessType` → `_RegisterApplication` → `abort`. The same minimal app and fixture now complete from Terminal, and the minimal app also completed from an explicitly non-sandboxed diagnostic launch. This isolates the failure to that sandbox launch context rather than an EasyHybrid3 import or AX hook; no `Gtk.init` workaround or production change was needed. The exact internal LaunchServices/AppKit reason for the sandbox-context abort was not present in the captured stack, so a lower-level Apple rejection code remains unknown. The supported, reproducible launch configuration is the user's Terminal session with the matching Python/GTK environment.

The `EASYHYBRID3_DISABLE_AX=1` Terminal instance was inspected while alive. `ps` and LLDB showed Python 3.12 running `easyhybrid.py`, with the crashing/main thread in the normal AppKit event loop → GDK poll function → GLib loop → `gtk_main()` path. The native AX helper could query System Settings and Finder (`trusted=yes`), while the production app returned `cannot-complete (-25204)` with the bridge disabled. CoreGraphics independently showed the real EasyHybrid window. Thus this disabled-run AX error was missing target exposure, not a client permission denial.

### AX-enabled bridge crash and correction

The first AX-enabled production run started GTK, then produced a new report (`Python-2026-10-16-181718.ips`, PID 48137) with `EXC_BREAKPOINT` / `SIGTRAP` on `com.apple.main-thread`. The stack ended in `NSLog` while formatting an argument from `bridge_register_widget`; the log passed a `GtkWidget *` to Objective-C's `%@` object formatter. GTK widgets are GObjects, not Objective-C objects. The bridge log now prints that widget and native `NSWindow` with `%p` and retains `%@` only for Objective-C strings. Rebuilding with `platform/macos/gtk3_accessibility/build.sh` succeeded. The next AX-enabled production run remained alive through AX inspection and multiple dialog actions with no new crash report.

### External native AX evidence

The standalone client compiled by `tools/run-ax-audit.command` reported `CLIENT trusted=yes` and signature identifier `easyhybrid3-ax-audit`. The app was PID 49201 in the successful AX-enabled run. Its application element reported role `AXApplication`, title `Python`; its actual window reported title `EasyHybrid 3.1.3`. Native AX returned a successful window list and 21 controls. Examples included:

```text
NODE role=AXButton title=Geometry Optmization description=Geometry Optmization ... enabled=1
NODE role=AXButton title=Open description=Open ... enabled=1
NODE role=AXButton title=New Project description=New Project ... enabled=1
NODE role=AXMenuItem title=File description=File ... enabled=1
```

The client used `AXUIElementPerformAction(..., kAXPressAction)` on the real **Open** toolbar button and reported `AXPRESS error=success(0)`. The GTK file chooser appeared as an `Open File...` native window; its `Open` and `Cancel` buttons were registered. A second AXPress on **Cancel** returned success, and a following query showed only the main `EasyHybrid 3.1.3` window and 21 controls. This proves the existing GTK button callback ran and the dynamic dialog was exposed and dismissed through native AX, without visual clicking.

The client then pressed **New Project** with AX. The GTK callback opened the production `Import New System` dialog. A subsequent target-only AX query found its actual `Cancel` button and three `AXTextField` nodes, with readable values including `/Users/shabir/software/EasyHybrid3/workspace/new_system_KfNg`, `new_system`, and `KfNg`. The bridge log independently recorded registration of the dynamic dialog's GTK entries and buttons.

AX value write remains unresolved. For the `KfNg` field, the external client reported `AXVALUE_SETTABLE ... settable=yes` and `AXSETVALUE error=success(0)`, but its readback was still `KfNg`; therefore no text modification is claimed. The production process later exited without a corresponding crash report while this setter path was under investigation. The precise exit cause is not established. Do not treat editable text as accepted until the setter is corrected and repeated with callback/readback evidence. No project was saved or written.

### Files changed for this recovery

- `platform/macos/gtk3_accessibility/bridge.mm` — corrected `%@` formatting of GTK/GDK pointers to `%p`.
- `platform/macos/gtk3_accessibility/tools/ax-audit.m` — added selected-label AXPress, target-only, optional activation, and text-value set/readback diagnostics.
- `platform/macos/gtk3_accessibility/tools/run-ax-audit.command` — added options to drive those native AX checks from trusted Terminal.
- `platform/macos/gtk3_accessibility/prototype/gtk3_minimal_startup.py` — minimal GTK3 Quartz startup baseline.
- `platform/macos/gtk3_accessibility/tools/run-startup-baselines.command` — fixed the zsh `status` variable issue; its production case is interactive and remains running until the user closes it.
- `docs/macos-gtk3-accessibility-audit.md` — this evidence and updated milestone status.

No scientific workflow, project-file format, GTK installation, or Linux startup code was changed during Milestone 3.1. The existing `easyhybrid.py` macOS-only hook remains the production entry point for the bridge.

### Milestone 3.1 classification

**Startup recovery: PASS.** Minimal GTK3, the existing fixture, and production EasyHybrid3 all start in the user's Terminal environment. Production startup succeeds with the AX hook enabled and disabled; native AX can discover the enabled production window and invoke a real GTK toolbar action.

**Production accessibility integration: PARTIAL.** Native window/control exposure, a real toolbar AXPress, and dynamic dialog discovery/dismissal pass. Text value readback and setter verification fail; the app's exit after the setter attempt has no crash report and remains unexplained. Menu action behavior, keyboard shortcuts, molecular rendering, project loading, simulation UI, desktop-bridge attachment, and comprehensive shutdown/lifecycle regressions remain unverified. The next technical action is to instrument the `accessibilitySetValue` callback and GTK idle callback, then prove an entry value change and clean cancellation before expanding the integration.

## Milestone 3.3 automated runtime verification (2026-10-16)

### Changes made

- `platform/macos/gtk3_accessibility/bridge.mm`: added traces for AX setter entry, ATK editable-text entry/return, GTK `changed`, and main-context completion. The AX value getter now reads the live `GtkEntry` text. Setter work is queued to GLib's default context when called off the recorded GTK thread and waits up to five seconds for actual entry readback; the AX caller no longer treats dispatch acceptance as proof of the write. The normal GTK entry path uses `AtkEditableText` first and retains the direct GtkEntry fallback, with actual-value verification.
- `platform/macos/gtk3_accessibility/tools/ax-audit.m`: added bounded repeated native AX cycles that press Open, locate/cancel its native file chooser, open New Project, set a `KfNg` field to a unique `AX_TEST_123_N` value, verify AX readback, cancel, and confirm the dialog has disappeared from the app window list.
- `platform/macos/gtk3_accessibility/tools/run-ax-audit.command`: accepts a per-run AX client binary path and dialog-cycle count.
- `platform/macos/gtk3_accessibility/tools/run-milestone-3-3.command`: one Terminal command builds the bridge/client, starts EasyHybrid3 with the existing Python/GTK environment, captures launch and callback logs, records the PID, runs three automated dialog/edit cycles, keeps the production UI available for visual checks, waits for shutdown, and compares before/after Python crash-report inventories. Set `EASYHYBRID3_M33_DISABLED=1` before invoking it to perform the separate AX-disabled startup check. Set `EASYHYBRID3_M33_CYCLES=N` to change the cycle count.

### Build and local checks

- Native bridge build: PASS (`platform/macos/gtk3_accessibility/build.sh`, Apple Clang, GTK3 Quartz 3.24.52 headers/libraries).
- Native AX audit client build: PASS (Apple Clang/AppKit/ApplicationServices/Security frameworks).
- Python syntax compilation: PASS (`python3 -m py_compile platform/macos/gtk3_accessibility/bootstrap.py easyhybrid.py`).
- `git diff --check`: PASS.
- Shell parse check could not be completed: launching `zsh -n` from this Codex sandbox was denied with `nice(5) failed: operation not permitted`; the command did not start the production app. Prior Milestone 3.1 Terminal evidence establishes that GTK Quartz production startup succeeds outside the sandbox.
- Runtime AX edit, dialog repetition, molecular display, menu/shortcut regression, shutdown, and desktop-bridge attachment: NOT RUN in this environment. The runner is prepared to collect runtime evidence in the user's normal Terminal session.

### Single-command Terminal procedure

In Terminal, run:

```sh
cd /Users/shabir/software/EasyHybrid3 && platform/macos/gtk3_accessibility/tools/run-milestone-3-3.command
```

The script prints its timestamped result directory under `/private/tmp/easyhybrid3-m33-*`. `session.log`, `application.log`, `ax-cycles.log`, and `crash-reports.txt` are written there. Grant the trusted AX audit client permission if macOS prompts. The script automatically runs three Open/Cancel and New Project/edit/Cancel cycles, then leaves the real UI open so the user can inspect a loaded project, menus, keyboard shortcuts, and window behavior before closing EasyHybrid3 normally. A separate disabled-startup run is `EASYHYBRID3_M33_DISABLED=1 platform/macos/gtk3_accessibility/tools/run-milestone-3-3.command` from the repository root.

The automated edit is accepted only when each cycle reports `TEXT_EDIT ... expected=AX_TEST_123_N actual=AX_TEST_123_N match=yes` and `DIALOG_TEST_RESULT=PASS`. The bridge log should show setter entry, `set-value-main-context-enter`, `atk-set-text-contents-enter/return`, `gtk-editable-changed`, and `set-value-complete`. The runner compares crash report inventories around the process lifetime; an empty list means no new Python crash report was created during that run. A process exit code alone is not labeled a crash because normal window close and terminal interruption are distinct cases.


## Milestone 3.4 final verification (2026-10-16)

### Setter diagnosis and correction

The earlier `KfNg` result was not a reproducible setter failure: the test client hard-coded a randomly generated tag from an older run and queried before asynchronous registration had finished. The live bridge setter was instrumented through the complete chain. Production traces show AX setter entry, dispatch to the GTK main context, `AtkEditableText` invocation, GTK editable `changed` signals, and actual-value readback, with `thread==gtk-main` and `context-owner=yes`. The client now selects the last text field in the New Project dialog as the Tag field, reads its initial random value, writes a unique test string, and checks AX readback.

The bridge also now removes the GObject weak pointer and frees the setter request on the inline main-thread path, closing a request-lifecycle leak. Unsupported GTK `ToolButton` and `ToggleToolButton` types are skipped during registration because their ATK objects expose no action interface; this removes repeated registration errors without broadening widget coverage.

### Runtime results

The existing `run-milestone-3-3.command` runner was executed in the supported normal macOS environment. Final run directory: `/private/tmp/easyhybrid3-m33-20261016-185348`, app PID 60675.

- Native AX test: **PASS**. Three repeated Open/Cancel and New Project/Edit/Cancel cycles completed. All six dialogs were observed and dismissed through AX, and each closed dialog was absent from the app window list afterward (`AX_CLEANUP ... removed=yes`).
- Text editing: **PASS**. Writes `AX_TEST_123_1`, `_2`, and `_3` each returned `success(0)` and native AX readback matched the actual value.
- App process: the AX close-button action returned `success(0)`. The runner's session log had not yet recorded completion when this audit was updated, so its final process wait/crash inventory summary is **not confirmed**. No new crash report was observed in the run directory at inspection time.
- Main window and menus: **PARTIAL**. The production main window and File menu were visible; menu opening works. A menu-item action and keyboard shortcut were not successfully verified.
- Molecular visualization: **NOT VERIFIED**. The app displayed its initial blank canvas; no project or molecular structure was loaded.
- Desktop bridge: **PASS for basic attachment and dialog use**. The bridge discovered the Python app window, activated Open and New Project, edited the Tag field to `DESKTOP_AX_TEST`, and canceled both dialogs. This is separate evidence from native AX.
- AX-disabled startup: **NOT RUN in this final verification**. Earlier Milestone 3.1 Terminal evidence remains the basis for the disabled-startup result.

### Build and source checks

- Native GTK3 Quartz bridge rebuild: PASS.
- Native AX audit client rebuild: PASS.
- `python3 -m py_compile platform/macos/gtk3_accessibility/bootstrap.py easyhybrid.py`: PASS.
- `zsh -n platform/macos/gtk3_accessibility/tools/run-milestone-3-3.command platform/macos/gtk3_accessibility/tools/run-ax-audit.command`: PASS.
- `git diff --check`: PASS before this documentation update.

### Milestone 3.4 classification

**PARTIAL.** Production GTK3 text editing and repeated dialog AX actions now have direct runtime evidence, and the earlier unexplained AX-enabled exit was not reproduced during these cycles. Clean runner shutdown/crash inventory, molecular rendering with a loaded project, keyboard shortcuts, and full menu interaction remain unverified. No scientific code or GTK version was changed. The run logs are available under `/private/tmp/easyhybrid3-m33-20261016-185348/` (`application.log`, `ax-cycles.log`, and `session.log`).

## Milestone 3.5 final verification (2026-10-16)

### Production function and interaction evidence

- **Molecular visualization: PASS.** From the native File → Open workflow, EasyHybrid loaded the existing supported pDynamo file `examples/pkl/1UAO_OPLS.pkl`. The main window reported `system: Chignolin (1UAO)`, `atoms: 138`, `force field: OPLS`; the visible 3D canvas rendered the molecule with its atoms and bonds. The run used the GTK3 Quartz bridge enabled.
- **Menu action: PASS.** Opening File and activating its Open command via the menu's `o` key opened the production `Open File...` chooser. Cancel returned to the main window with the loaded molecule still displayed.
- **Keyboard/window interaction: PASS for Escape close flow.** Escape invoked the app's existing close handler and displayed the Save/Cancel/Don't Save prompt. Cancel returned to the project; the final focused run used Don't Save to exit without writing the sample file. A mouse click selected the sample row in the native chooser and Open loaded it.
- **Native AX: PASS.** With the rebuilt bridge, the existing runner completed three Open/Cancel and three New Project/edit/Cancel cycles. Each `AX_TEST_123_N` value was read back correctly, and each closed dialog disappeared from the application window list.
- **Desktop bridge: PASS for previously verified coverage.** Milestone 3.4 evidence remains: app-window discovery, Open and New Project activation, tag editing, dialog cancel, and removal from the returned tree.

### Stability findings

The old run `/private/tmp/easyhybrid3-m33-20261016-185348/` did **not** end cleanly: `APP_WAIT_STATUS=139`. Its `application.log` contains `Fatal Python error: Segmentation fault`, with the Python frame in `Gtk.FileChooserDialog.run()` called by `FileChooser.open()` from `MainWindow.open_gtk_load_files()`. The log immediately before it confirms that Chignolin loaded. The runner's crash-report comparison said `CRASH_REPORTS=none`; this is consistent with the fatal traceback being captured in the application log without a separate `.ips` report. The precise native fault and its trigger were not identified, so this is recorded as an unresolved, observed crash rather than attributed to the accessibility bridge.

The focused retest used the rebuilt bridge, repeated the three automated AX cycles, loaded the same Chignolin file, opened and canceled the chooser once more, then exited through the normal close prompt. Run `/private/tmp/easyhybrid3-m33-20261016-190207/` reports `APP_WAIT_STATUS=0`, `CRASH_REPORTS=none`, and no fatal traceback. This did not reproduce the earlier crash, but one clean repetition does not explain or rule out the status-139 event. Another enabled run `/private/tmp/easyhybrid3-m33-20261016-185951/` also passed its AX cycles and exited with status 0/no new report.

### Enabled and disabled startup

- Accessibility enabled: the existing runner launched the production UI, passed all three AX edit/dialog cycles, and completed a normal status-0 shutdown in the focused retest.
- Accessibility disabled: `/private/tmp/easyhybrid3-m33-20261016-190033/` launched PID 61896 with `EASYHYBRID3_DISABLE_AX=1`. A process inspection confirmed Python remained alive in `Gtk.main()` without bridge registration output. CUA could not attach to this intentionally unexposed window, so the background test process was stopped with SIGTERM; the runner recorded status 143 and no crash report. This verifies disabled startup remains alive, but not a graceful close in disabled mode.

### Diagnostic logging and regression checks

`bridge.mm` now gates native AX callback traces and widget-registration logs behind `EASYHYBRID3_AX_DEBUG=1`. The existing production diagnostic runner sets that flag for its enabled test run and clears it for the disabled run; ordinary startup no longer emits the temporary per-widget/setter trace stream. The current AppKit `isAccessibilityAttributeSettable:` override computes the value directly instead of calling the deprecated legacy selector.

- Native bridge build after the logging and deprecation cleanup: PASS (`platform/macos/gtk3_accessibility/build.sh`).
- Final `zsh -n` for both existing runners: PASS.
- Final `python3 -m py_compile platform/macos/gtk3_accessibility/bootstrap.py easyhybrid.py`: PASS.
- Final `git diff --check`: PASS.
- No scientific source files were changed as part of Milestone 3.5. The workspace already contains unrelated edits to scientific modules/tests and `docs/MACOS_NATIVE_RENDERING_FIX.md`; they were left untouched.

### Milestone 3.5 classification

**PARTIAL — production controls and scientific display are verified; full stability is not established.** Molecule rendering, the File menu Open action, Escape close handling, native AX, desktop-bridge interactions, enabled startup, disabled startup, build, and syntax checks have evidence. The earlier status-139 segfault in GTK's file chooser remains unexplained despite a successful focused retest. Disabled-startup shutdown was force-stopped after confirming the app was alive. No commit was created.

## Milestone 3.6 crash and stability verification (2026-10-16)

### Crash investigation

The earlier status-139 log (`/private/tmp/easyhybrid3-m33-20261016-185348/application.log`) records a Python fatal segmentation fault with its visible Python frame in `Gtk.FileChooserDialog.run()`, called from `FileChooser.open()` / `MainWindow.open_gtk_load_files()`. There is no native stack in that log and no matching `.ips` crash report in the runner inventory. This establishes the failing call path, but does not distinguish a GTK Quartz defect from native AX object lifetime, callback reentrancy, or an interaction with the chooser. No code change was made on a speculative diagnosis.

### Repeated enabled-mode dialogs and editing

Using the existing `run-milestone-3-3.command` launcher with 20 cycles, the native AX client completed 20 File → Open → Cancel cycles and 20 New Project → edit tag → Cancel cycles. Every action returned `success(0)`, every edit's AX readback matched its unique `AX_TEST_123_N` value, and all 40 dialog closures reported `AX_CLEANUP ... removed=yes`. `DIALOG_TEST_RESULT=PASS` and `AUTOMATED_AX_RESULT=PASS` are in `/private/tmp/easyhybrid3-m33-20261016-222351/ax-cycles.log`. No crash or deadlock occurred during those automated cycles.

### Project rendering and close outcome

The same enabled-mode process opened `examples/pkl/1UAO_OPLS.pkl`. EasyHybrid reported `Chignolin (1UAO)`, 138 atoms, OPLS, and the screenshot showed the molecular viewport populated with the structure. Clicking the normal window close control opened the application's Save / Cancel / Don't Save prompt; the bridge registered that dialog and all its buttons. Computer Use stopped returning AX state while the prompt was open, and the Terminal runner remained waiting for the application. I interrupted the waiting runner, so this run does **not** establish a normal application exit status or clean shutdown. Its `session.log` has no final `APP_WAIT_STATUS` or crash inventory; the process PID is recorded as 64035. The log contains no Python fatal traceback up to the close prompt.

### Disabled-mode and remaining verification

No Milestone 3.6 AX-disabled dialog stress or graceful-shutdown run was completed. With the bridge disabled, this environment's native AX path cannot discover EasyHybrid controls, so the same native AX automation cannot operate those dialogs. Milestone 3.5's disabled run only established that the app stayed alive in `Gtk.main()` before it was stopped by signal (status 143). Menu Open and Escape close behavior and visual rendering have prior enabled-mode evidence in the Milestone 3.5 section. The desktop bridge retains the Milestone 3.4 interaction evidence; it was not reattached in this run.

Build of the native bridge passed again in Milestone 3.6. Python syntax check and `git diff --check` passed. The runner's `zsh -n` invocation was denied in this shell context (`nice(5) failed: operation not permitted`); its prior syntax pass is documented above. No crash was reproduced in the 20-cycle run, but the status-139 root cause remains **unconfirmed**, and clean shutdown in both accessibility modes has not been verified.

### Milestone 3.6 classification

**PARTIAL — AX editing and repeated enabled dialog lifecycles pass; crash resolution and shutdown stability remain unconfirmed.** No speculative crash fix or scientific-code modification was made.
