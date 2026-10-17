"""Opt-in in-process GTK driver for macOS accessibility runtime checks.

Loaded only when EASYHYBRID3_TEST_HOOK points to this file. It drives the
production main-window callbacks and Gtk.FileChooserDialog from GTK's own
main context, without requiring an accessibility client.
"""

import os
import traceback


def run(main_window, Gtk, GLib):
    if os.environ.get("EASYHYBRID3_RUNTIME_TESTS") != "1":
        raise RuntimeError("Runtime tests require explicit launcher opt-in")
    mode = os.environ.get("EASYHYBRID3_TEST_HOOK_MODE", "dialogs")
    cycles = int(os.environ.get("EASYHYBRID3_TEST_HOOK_CYCLES", "20"))
    output = os.environ.get("EASYHYBRID3_TEST_HOOK_LOG", "/private/tmp/easyhybrid3-gtk-test-hook.log")

    def log(message):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")
            stream.flush()

    log(f"HOOK_START mode={mode} cycles={cycles}")

    def close_normally():
        log("NORMAL_CLOSE invoking=MainWindow.on_delete_event")
        try:
            main_window.on_delete_event(main_window.window, None)
            log("NORMAL_CLOSE callback-returned=yes")
        except Exception:
            log("NORMAL_CLOSE exception=" + traceback.format_exc().replace("\n", " | "))
            # Leave the app available for diagnostics; never turn a failed
            # close callback into an apparently successful shutdown.
        return GLib.SOURCE_REMOVE

    if mode == "shutdown":
        main_window.p_session.changed = True
        GLib.timeout_add(50, _answer_shutdown_prompt, Gtk, GLib, log)
        GLib.timeout_add(1500, close_normally)
        return

    passed = True
    for index in range(1, cycles + 1):
        # Invoke EasyHybrid's real menu callback. It constructs the production
        # FileChooserDialog and calls its run(), exactly as File → Open does.
        try:
            log(f"OPEN_CYCLE index={index} action=production-file-menu")
            GLib.timeout_add(20, _cancel_active_file_chooser, Gtk, GLib)
            main_window.on_main_menu_activate(main_window.builder.get_object("menuitem_open"))
            remaining = [w for w in Gtk.Window.list_toplevels()
                         if "Open File..." in (w.get_title() or "")]
            if remaining:
                passed = False
            log(f"OPEN_CYCLE index={index} returned=yes dialog_remaining={bool(remaining)}")
        except Exception:
            passed = False
            log(f"OPEN_CYCLE index={index} exception=" + traceback.format_exc().replace("\n", " | "))

        try:
            log(f"NEW_CYCLE index={index} action=production-new-system")
            main_window.NewSystemWindow.open_window()
            controller = main_window.NewSystemWindow
            dialog = getattr(controller, "window", None)
            if dialog is None or not dialog.get_visible():
                passed = False
                log(f"NEW_CYCLE index={index} dialog=missing")
                continue
            cancel_button = controller.builder.get_object("button_cancel")
            if cancel_button is None:
                passed = False
                log(f"NEW_CYCLE index={index} cancel=missing")
                continue
            cancel_button.clicked()
            remaining = [w for w in Gtk.Window.list_toplevels()
                         if "Import New System" in (w.get_title() or "")]
            if remaining:
                passed = False
            log(f"NEW_CYCLE index={index} returned=yes dialog_remaining={bool(remaining)}")
        except Exception:
            passed = False
            log(f"NEW_CYCLE index={index} exception=" + traceback.format_exc().replace("\n", " | "))

    log(f"DIALOG_TEST_RESULT={'PASS' if passed else 'FAIL'} cycles={cycles}")
    if mode == "dialogs_shutdown":
        main_window.p_session.changed = True
        GLib.timeout_add(50, _answer_shutdown_prompt, Gtk, GLib, log)
        GLib.timeout_add(1500, close_normally)


def _cancel_active_file_chooser(Gtk, GLib):
    for window in Gtk.Window.list_toplevels():
        if isinstance(window, Gtk.FileChooserDialog) and window.get_visible():
            window.response(Gtk.ResponseType.CANCEL)
            return GLib.SOURCE_REMOVE
    return GLib.SOURCE_CONTINUE

def _answer_shutdown_prompt(Gtk, GLib, log):
    for window in Gtk.Window.list_toplevels():
        if isinstance(window, Gtk.MessageDialog) and window.get_visible():
            log("NORMAL_CLOSE prompt=present response=NO")
            window.response(Gtk.ResponseType.NO)
            return GLib.SOURCE_REMOVE
    return GLib.SOURCE_CONTINUE
