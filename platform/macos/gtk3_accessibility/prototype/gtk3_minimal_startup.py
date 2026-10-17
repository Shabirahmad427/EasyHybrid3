#!/usr/bin/env python3
"""Short-lived minimal GTK3 Quartz startup baseline; no AX bridge imports."""
import os
import platform
import sys

import gi
gi.disable_legacy_autoinit()
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gdk, Gtk

Gtk.init([])
print(f"BASELINE python={sys.executable} arch={platform.machine()} version={platform.python_version()}", flush=True)
print(f"BASELINE gtk={Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()} display={type(Gdk.Display.get_default()).__name__ if Gdk.Display.get_default() else None} DISPLAY={os.environ.get('DISPLAY')}", flush=True)
window = Gtk.Window(title="GTK3 startup baseline")
window.add(Gtk.Button(label="GTK3 Quartz is running"))
window.connect("destroy", Gtk.main_quit)
window.show_all()
GLib.timeout_add_seconds(3, lambda: (window.destroy(), GLib.SOURCE_REMOVE)[1])
Gtk.main()
print("BASELINE clean-exit=0", flush=True)
