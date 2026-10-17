#!/usr/bin/env python3
"""Minimal GTK 3 Quartz fixture for native accessibility experiments."""

import gi
import os
import sys

gi.disable_legacy_autoinit()
gi.require_version("Gtk", "3.0")
gi.require_version("Atk", "1.0")
from gi.repository import Atk, GLib, Gtk


def report_accessible(label, widget):
    accessible = widget.get_accessible()
    interfaces = {
        "action": isinstance(accessible, Atk.Action),
        "component": isinstance(accessible, Atk.Component),
        "text": isinstance(accessible, Atk.Text),
        "editable_text": isinstance(accessible, Atk.EditableText),
        "value": isinstance(accessible, Atk.Value),
        "selection": isinstance(accessible, Atk.Selection),
    }
    print(
        f"ATK {label}: class={type(accessible).__name__} "
        f"role={accessible.get_role().value_nick} "
        f"name={accessible.get_name()!r} interfaces={interfaces}",
        flush=True,
    )


def main():
    Gtk.init([])

    window = Gtk.Window(title="EasyHybrid3 GTK3 AX prototype")
    window.set_default_size(520, 360)
    window.connect("destroy", Gtk.main_quit)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=16)
    window.add(box)

    button = Gtk.Button(label="Run accessible button")
    button.set_name("probe-button")
    button.get_accessible().set_name("Run accessible button")
    press_count = {"value": 0}

    def on_button_clicked(*_args):
        press_count["value"] += 1
        print(f"ACTION button-pressed count={press_count['value']}", flush=True)
        if os.environ.get("EASYHYBRID3_AX_LIFECYCLE_TEST") == "1" and press_count["value"] == 2:
            print("LIFECYCLE window-closed", flush=True)
            window.destroy()
        elif press_count["value"] == 1 and os.environ.get("EASYHYBRID3_AX_LIFECYCLE_TEST") == "1":
            def hide_window():
                print("LIFECYCLE window-hidden", flush=True)
                window.hide()
                return GLib.SOURCE_REMOVE

            def show_window():
                print("LIFECYCLE window-shown", flush=True)
                window.show_all()
                window.present()
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(100, hide_window)
            GLib.timeout_add(1200, show_window)

    button.connect("clicked", on_button_clicked)
    box.pack_start(button, False, False, 0)

    entry = Gtk.Entry()
    entry.set_text("initial entry value")
    entry.set_name("probe-entry")
    entry.get_accessible().set_name("Probe text entry")
    box.pack_start(entry, False, False, 0)

    check = Gtk.CheckButton(label="Enable option")
    check.set_name("probe-check")
    box.pack_start(check, False, False, 0)

    combo = Gtk.ComboBoxText()
    combo.set_name("probe-combo")
    combo.append_text("Alpha")
    combo.append_text("Beta")
    combo.set_active(0)
    box.pack_start(combo, False, False, 0)

    menu_bar = Gtk.MenuBar()
    menu = Gtk.Menu()
    menu_item = Gtk.MenuItem(label="Probe menu item")
    menu_item.connect("activate", lambda *_: print("ACTION menu-activated", flush=True))
    menu.append(menu_item)
    top_item = Gtk.MenuItem(label="Probe menu")
    top_item.set_submenu(menu)
    menu_bar.append(top_item)
    box.pack_start(menu_bar, False, False, 0)

    for label, widget in (
        ("window", window),
        ("button", button),
        ("entry", entry),
        ("checkbox", check),
        ("combo", combo),
        ("menu-item", menu_item),
    ):
        report_accessible(label, widget)

    window.show_all()
    window.present()
    if (os.environ.get("EASYHYBRID3_AX_BRIDGE") == "1"
            or os.environ.get("EASYHYBRID3_AX_FINISH_LAUNCHING") == "1"):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
        sys.path.insert(0, os.path.join(repo_root, "platform", "macos"))
        from gtk3_accessibility import _gtk3_accessibility as gtk3_ax_bridge

        if os.environ.get("EASYHYBRID3_AX_FINISH_LAUNCHING") == "1":
            gtk3_ax_bridge.finish_launching()
        if os.environ.get("EASYHYBRID3_AX_BRIDGE") == "1":
            # The submenu item is unrealized until its popup is shown; the
            # native adapter correctly requires a realized GTK toplevel.
            for widget in (button, entry, check, combo):
                gtk3_ax_bridge.register_widget(widget)
    if os.environ.get("EASYHYBRID3_AX_AUTOCLOSE") == "1":
        GLib.timeout_add_seconds(3, lambda: (window.destroy(), GLib.SOURCE_REMOVE)[1])
    GLib.idle_add(lambda: (window.queue_draw(), GLib.SOURCE_REMOVE)[1])
    print("GTK3 probe ready; close the window to exit.", flush=True)
    Gtk.main()


if __name__ == "__main__":
    main()
