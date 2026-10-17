"""Settings dialog for the in-process GPU4PySCF backend."""

import os
import tempfile

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class SetupGPU4PySCFWindow:
    def __init__(self, main, setup_qc_model_window):
        self.main_session = main
        self.home = main.home
        self.setup_qc_model_window = setup_qc_model_window
        self.Visible = False
        self.window = None
        scratch_root = os.environ.get("PDYNAMO3_SCRATCH", tempfile.gettempdir())
        self.parameters = {
            "method": "DFT", "functional": "B3LYP", "basis": "def2-svp",
            "density_fitting": True,
            "max_cycles": 100, "conv_tolerance": 1.0e-9,
            "scratch": os.path.join(scratch_root, "GPU4PySCFScratch"),
        }

    def open_window(self, vismol_object=None):
        if self.Visible:
            self.window.present()
            return
        self.window = Gtk.Window(title="GPU4PySCF Setup")
        self.window.set_transient_for(self.setup_qc_model_window.window)
        self.window.set_modal(False)
        self.window.set_border_width(12)
        self.window.set_default_size(460, 240)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.window.add(box)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        box.pack_start(grid, True, True, 0)
        self.method = Gtk.ComboBoxText()
        for item in ("DFT", "HF"):
            self.method.append_text(item)
        self.method.set_active(0 if self.parameters["method"] == "DFT" else 1)
        self.functional = Gtk.Entry(text=self.parameters["functional"])
        self.basis = Gtk.Entry(text=self.parameters["basis"])
        self._AddPySCFSuggestions(self.functional, "functionals")
        self._AddPySCFSuggestions(self.basis, "basis")
        self.density_fitting = Gtk.CheckButton(label="Use density fitting (recommended)")
        self.density_fitting.set_active(self.parameters["density_fitting"])
        self.max_cycles = Gtk.SpinButton.new_with_range(1, 1000, 1)
        self.max_cycles.set_value(self.parameters["max_cycles"])
        self.scratch = Gtk.Entry(text=self.parameters["scratch"])

        for row, (label, widget) in enumerate((
            ("Method", self.method), ("XC functional", self.functional),
            ("Basis set", self.basis), ("Maximum SCF cycles", self.max_cycles),
            ("Scratch directory", self.scratch),
        )):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        grid.attach(self.density_fitting, 1, 5, 1, 1)

        note = Gtk.Label(label=(
            "HF/DFT; suggestions come from the installed PySCF functional and basis catalogs. "
            "CUDA coverage varies; some XC components fall back to CPU PySCF. Electrostatic "
            "QM/MM embedding is supported. ωB97X-D2 and ωB97X-D3 are unavailable here; "
            "ωB97X-D3BJ is a separate supported variant. Double hybrids and some meta-GGAs "
            "are unavailable, including Laplacian meta-GGAs and three-component methods "
            "that need their own basis/ECP setup. Known CUDA XC crash cases are blocked. "
            "Requires a visible, supported NVIDIA CUDA device."
        ), xalign=0)
        note.set_line_wrap(True)
        box.pack_start(note, False, False, 2)
        buttons = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        buttons.set_layout(Gtk.ButtonBoxStyle.END)
        box.pack_end(buttons, False, False, 0)
        cancel = Gtk.Button(label="Cancel")
        apply = Gtk.Button(label="Apply")
        cancel.connect("clicked", self.close_window)
        apply.connect("clicked", self.on_button_ok)
        buttons.add(cancel)
        buttons.add(apply)
        self.window.connect("delete-event", self._on_delete)
        self.window.show_all()
        self.Visible = True

    @staticmethod
    def _AddPySCFSuggestions(entry, catalog):
        """Autocomplete from the PySCF catalogs available in this environment."""
        try:
            if catalog == "functionals":
                from pyscf.dft import libxc
                names = set(libxc.XC_CODES)
                names.update(("B3LYP", "PBE", "PBE0", "CAM-B3LYP", "WB97", "WB97X",
                              "WB97X-D", "WB97X-V", "WB97M-V", "WB97X-D3BJ",
                              "WB97M-D3BJ", "B97M-V", "B97M-D3BJ", "WB97X-D4",
                              "WB97M-D4", "M06", "M06-L", "M06-2X", "M06-HF",
                              "M11-L", "MN15", "MN15-L", "B97-D", "HSE06",
                              "B3LYP-D3BJ", "PBE-D3BJ", "PBE0-D3BJ"))
            else:
                from pyscf.gto import basis
                auxiliary_suffixes = ("fit", "jkfit", "jfit", "cfit", "xfit", "ri")
                names = {name for name in basis.ALIAS
                         if not name.lower().endswith(auxiliary_suffixes)
                         and name.lower() not in ("weigend", "weigend+etb", "demon", "ahlrichs")}
                names.update(("STO-3G", "6-31G", "6-31G*", "6-31G**", "6-31+G", "6-31+G*",
                              "6-31+G**", "6-31++G", "6-31++G*", "6-31++G**", "6-311G",
                              "6-311G*", "6-311G**", "def2-SVP", "def2-TZVP", "def2-TZVPP",
                              "cc-pVDZ", "cc-pVTZ", "aug-cc-pVDZ", "aug-cc-pVTZ"))
        except Exception:
            # Keep free-text entry usable if the optional PySCF registry is
            # unavailable or cannot be imported in this environment.
            return

        model = Gtk.ListStore(str)
        for name in sorted(names, key=lambda value: value.lower()):
            model.append((name,))
        completion = Gtk.EntryCompletion()
        completion.set_model(model)
        completion.set_text_column(0)
        completion.set_inline_completion(True)
        completion.set_minimum_key_length(2)
        entry.set_completion(completion)

    def on_button_ok(self, button):
        self.parameters.update({
            "method": self.method.get_active_text(),
            "functional": self.functional.get_text().strip(),
            "basis": self.basis.get_text().strip(),
            "density_fitting": self.density_fitting.get_active(),
            "max_cycles": self.max_cycles.get_value_as_int(),
            "scratch": self.scratch.get_text().strip(),
        })
        self.close_window(button)

    def _on_delete(self, window, event):
        self.close_window(window)
        return True

    def close_window(self, button=None, data=None):
        if self.window is not None:
            self.window.destroy()
        self.window = None
        self.Visible = False
