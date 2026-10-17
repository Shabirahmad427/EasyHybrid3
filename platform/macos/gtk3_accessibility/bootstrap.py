"""Optional native macOS bridge for GTK3 Quartz accessibility."""

import logging
import os
import sys
import weakref

_log = logging.getLogger("easyhybrid3.accessibility")
_bridge = None
_initialized = False
_seen_toplevels = weakref.WeakSet()


def initialize(main_window, diagnostic=False):
    """Initialize native exposure for a realized EasyHybrid GTK window.

    Set EASYHYBRID3_DISABLE_AX=1 to disable it or
    EASYHYBRID3_AX_DIAGNOSTIC=1 to log registration details.
    """
    global _bridge, _initialized
    if _initialized:
        return False
    _initialized = True
    if sys.platform != "darwin" or os.environ.get("EASYHYBRID3_DISABLE_AX") == "1":
        return False

    try:
        from gi.repository import Gdk, GLib, Gtk

        display = Gdk.Display.get_default()
        if Gtk.get_major_version() != 3 or display is None:
            return False
        display_name = display.get_name().lower()
        display_type = type(display).__name__.lower()
        if ("quartz" not in display_name and "quartz" not in display_type
                and not os.environ.get("GDK_BACKEND", "").lower().startswith("quartz")):
            _log.info("Accessibility bridge disabled: active GDK display is not Quartz (%s)", display_name)
            return False

        from . import _gtk3_accessibility as native

        _bridge = native
        # GTK's Quartz backend leaves AppKit finishLaunching disabled. Defer
        # this until EasyHybrid's menus exist and its real window is shown.
        native.finish_launching()
        _register_tree(main_window, diagnostic=diagnostic or os.environ.get("EASYHYBRID3_AX_DIAGNOSTIC") == "1")
        GLib.timeout_add_seconds(1, _register_new_toplevels)
        _log.info("GTK3 Quartz native accessibility bridge initialized")
        return True
    except Exception:
        _log.exception("GTK3 Quartz accessibility bridge initialization failed")
        return False


def _register_tree(root, diagnostic=False):
    if _bridge is None or root is None:
        return
    supported = ("Button", "ToggleButton", "Entry", "Label", "ComboBox",
                 "SpinButton", "Notebook", "TreeView", "MenuItem", "Dialog")
    stack = [root]
    registered = 0
    while stack:
        widget = stack.pop()
        type_name = type(widget).__name__
        # GTK3 ToolButton variants on Quartz may expose no ATK action. They
        # are not eligible for this bridge's existing action contract; do not
        # repeatedly attempt registration and flood the production log.
        unsupported_tool_button = type_name in ("ToolButton", "ToggleToolButton")
        if not unsupported_tool_button and any(name in type_name for name in supported):
            try:
                if widget.get_realized() and widget.get_visible():
                    _bridge.register_widget(widget)
                    registered += 1
            except Exception:
                if diagnostic:
                    _log.exception("Could not register GTK widget %s", type_name)
        try:
            stack.extend(widget.get_children())
        except Exception:
            pass
    if diagnostic:
        _log.info("Registered %d visible GTK widgets under %s", registered, type(root).__name__)


def _register_new_toplevels():
    """Discover dialogs and dynamically created controls without app edits."""
    if _bridge is None:
        return False
    try:
        from gi.repository import Gtk
        for window in Gtk.Window.list_toplevels():
            if window in _seen_toplevels:
                # Repeat scanning existing windows to include dynamically
                # inserted tree rows and controls; native registration dedupes.
                _register_tree(window)
                continue
            _seen_toplevels.add(window)
            _register_tree(window)
    except Exception:
        _log.exception("Could not update GTK accessibility hierarchy")
    return True
