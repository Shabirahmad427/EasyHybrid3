#!/usr/bin/env python
# Export structural data from a pDynamo2 System to a version-neutral JSON
# exchange manifest. Run this with the Python interpreter/environment that
# can load the source pDynamo2 pickle.

from __future__ import print_function

import argparse
import json
import os
import re
import sys
import traceback

from pCore import Unpickle
from pBabel import XYZFile_ToCoordinates3


FORMAT = "easyhybrid-pdynamo-exchange"
FORMAT_VERSION = 1
try:
    _STRING_TYPES = (basestring,)
except NameError:
    _STRING_TYPES = (str,)


def _value(obj, name, default=None):
    try:
        value = getattr(obj, name)
        if callable(value):
            return value()
        return value
    except Exception:
        return default


def _as_int(value, default=None):
    try:
        return int(value)
    except Exception:
        return default


def _atom_record(atom, index, system=None):
    record = {
        "index": index,
        "name": str(_value(atom, "label", "X{}".format(index + 1))),
        "atomic_number": _as_int(_value(atom, "atomicNumber"), 0),
        "formal_charge": _as_int(_value(atom, "formalCharge"), 0),
    }
    # Preserve common sequence/residue annotations where pDynamo2 exposes them.
    for key in ("residueName", "residueNumber", "chainID", "segmentID", "alternateLocation"):
        value = _value(atom, key)
        if value is not None:
            record[key] = str(value)
    sequence_component = _value(atom, "parent")
    if sequence_component is not None:
        residue_label = _value(sequence_component, "label")
        if residue_label:
            try:
                parsed = system.sequence.ParseLabel(residue_label, fields=3)
                record["residueName"] = str(parsed[0])
                record["residueNumber"] = str(parsed[1])
                record["insertionCode"] = str(parsed[2])
            except Exception:
                parts = str(residue_label).split(".", 1)
                record["residueName"] = parts[0]
                record["residueNumber"] = parts[1] if len(parts) > 1 else "1"
        entity = _value(_value(sequence_component, "parent"), "label", "")
        if entity:
            record["entity"] = str(entity)
    return record


def _bond_records(system, model_system=None):
    result = []
    connectivity = _value(system, "connectivity")
    bonds = _value(connectivity, "bonds", []) or []
    nodes = _value(connectivity, "nodes", []) or []
    node_indices = dict((id(node), i) for i, node in enumerate(nodes))
    for bond in bonds:
        a = _value(bond, "node1")
        b = _value(bond, "node2")
        i = node_indices.get(id(a))
        j = node_indices.get(id(b))
        if i is None or j is None:
            # Some pDynamo2 builds expose edge endpoints through nodes.
            pair = _value(bond, "nodes", []) or []
            if len(pair) == 2:
                i, j = node_indices.get(id(pair[0])), node_indices.get(id(pair[1]))
        if i is None or j is None:
            raise RuntimeError("Could not map a connectivity bond to atom indices.")
        bond_type = _value(bond, "type")
        result.append({"atoms": [int(i), int(j)], "type": str(bond_type),
                       "aromatic": bool(_value(bond, "isAromatic", False))})
    if not result and model_system is not None:
        # Older pDynamo2 Systems often keep connectivity in the MM term
        # containers instead of Connectivity._bonds. Preserve those pairs;
        # detailed bond order remains unavailable in this representation.
        model = _value(_value(model_system, "energyModel"), "mmTerms")
        for term in (_value(model, "items", []) or []):
            if _value(term, "label") == "Harmonic Bond":
                indices = term.Get12Indices()
                for offset in range(0, len(indices), 2):
                    result.append({"atoms": [int(indices[offset]), int(indices[offset + 1])],
                                   "type": "Single", "aromatic": False})
                break
    return result


def _coordinates(system_or_coordinates):
    coords = _value(system_or_coordinates, "coordinates3", system_or_coordinates)
    if coords is None:
        raise RuntimeError("The source system has no coordinates.")
    extent = _as_int(_value(coords, "rows"), len(coords))
    rows = []
    for i in range(extent):
        rows.append([float(coords[i, 0]), float(coords[i, 1]), float(coords[i, 2])])
    return rows


def _snapshot_coordinates(path):
    if path.lower().endswith(".xyz"):
        return _coordinates(XYZFile_ToCoordinates3(path))
    return _coordinates(Unpickle(path))


def _write_coordinate_sidecar(path, rows):
    with open(path, "w") as stream:
        for xyz in rows:
            stream.write("{:.16e} {:.16e} {:.16e}\n".format(float(xyz[0]), float(xyz[1]), float(xyz[2])))


def _natural_sort_key(path):
    return [(1, int(part)) if part.isdigit() else (0, part.lower())
            for part in re.split(r"(\d+)", os.path.basename(path))]


def _expand_snapshot_sources(paths, source):
    """Accept individual files or directories containing PKL/XYZ frames."""
    expanded = []
    discovered = set()
    source_real = os.path.realpath(source)
    for path in paths:
        if os.path.isdir(path):
            entries = [os.path.join(path, name) for name in os.listdir(path)
                       if name.lower().endswith((".pkl", ".xyz"))]
            expanded.extend(sorted(entries, key=_natural_sort_key))
            discovered.update(os.path.realpath(item) for item in entries)
        else:
            expanded.append(path)
    result = []
    seen = set()
    for path in expanded:
        real = os.path.realpath(path)
        if real == source_real or real in seen:
            continue
        seen.add(real)
        result.append(path)
    return result, discovered


def _expand_snapshots(paths, source):
    """Compatibility helper returning only the expanded paths."""
    return _expand_snapshot_sources(paths, source)[0]


def _portable(value, depth=0):
    """Convert pDynamo state objects to tagged JSON-compatible values."""
    if depth > 80:
        raise RuntimeError("Model state nesting is unexpectedly deep.")
    if value is None or isinstance(value, (bool, int, float) + _STRING_TYPES):
        return value
    if isinstance(value, (list, tuple)):
        return [_portable(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return dict((str(key), _portable(item, depth + 1))
                    for key, item in value.items()
                    if str(key) not in ("target", "generator", "scratch", "qcAtoms", "qcParameters"))
    if hasattr(value, "tolist"):
        return _portable(value.tolist(), depth + 1)
    getstate = getattr(value, "__getstate__", None)
    if getstate is not None:
        state = getstate()
        return {"__class__": value.__class__.__name__,
                "__module__": value.__class__.__module__,
                "state": _portable(state, depth + 1)}
    raise RuntimeError("Cannot export model value of type {}.{}".format(
        value.__class__.__module__, value.__class__.__name__))


def _model_manifest(system):
    """Export energy model state and the selections stored with the system."""
    energy_model = _value(system, "energyModel")
    if energy_model is None:
        return None
    state = energy_model.__getstate__()
    # QC atom containers and QC parameter caches are derived from the QC model
    # and the selected atom indices. Excluding them avoids exporting machine
    # state that pDynamo3 should regenerate during model construction.
    portable_state = _portable(state)
    qc_selection = []
    qc_boundary_records = []
    qc_atoms = state.get("qcAtoms")
    if qc_atoms is not None:
        qc_selection = [int(i) for i in qc_atoms.QCAtomSelection()]
        qc_state = qc_atoms.__getstate__()
        atom_fields = qc_state.get("atomFields", [])
        try:
            index_field = atom_fields.index("index")
            link_factor_field = atom_fields.index("linkFactor")
        except ValueError:
            raise RuntimeError("The pDynamo2 QC atom table has an unsupported layout.")
        ordinal_by_index = {
            int(row[index_field]): ordinal
            for ordinal, row in enumerate(qc_state.get("atoms", []))
        }
        mm_partners = qc_state.get("mmPartners", {})
        for boundary_atom, qc_partner in qc_atoms.BoundaryAtomQCPartnerPairs():
            ordinal = ordinal_by_index[int(boundary_atom)]
            row = qc_state["atoms"][ordinal]
            partners = mm_partners.get(ordinal, mm_partners.get(str(ordinal), []))
            qc_boundary_records.append({
                "boundary_atom": int(boundary_atom),
                "qc_partner": int(qc_partner),
                "mm_partners": [int(i) for i in partners],
                "link_factor": float(row[link_factor_field]),
            })
    fixed_atoms = []
    hard_constraints = _value(system, "hardConstraints")
    if hard_constraints is not None:
        fixed = _value(hard_constraints, "fixedAtoms")
        if fixed is not None:
            fixed_atoms = [int(i) for i in fixed]
    electronic_state = _value(system, "electronicState")
    return {
        "class": energy_model.__class__.__name__,
        "state": portable_state,
        "qc_selection": qc_selection,
        "qc_boundary_records": qc_boundary_records,
        "fixed_atoms": fixed_atoms,
        "electronic_state": {
            "charge": _as_int(_value(electronic_state, "charge")),
            "multiplicity": _as_int(_value(electronic_state, "multiplicity")),
        } if electronic_state is not None else None,
    }


def export(source, output, snapshots, model_template=None):
    snapshots, discovered_snapshots = _expand_snapshot_sources(snapshots, source)
    system = Unpickle(source)
    model_system = system
    model_source_path = source
    if model_template:
        model_system = Unpickle(model_template)
        model_source_path = model_template
    elif (_value(_value(system, "energyModel"), "qcModel") is None or
          _value(_value(system, "energyModel"), "mmModel") is None):
        # Many pDynamo2 workflows save an unparameterized base system, then
        # save configured system snapshots. Reuse the first PKL snapshot as
        # the model template while retaining base coordinates/topology.
        for path in snapshots:
            if path.lower().endswith(".xyz"):
                continue
            try:
                candidate = Unpickle(path)
                if _value(candidate, "atoms") is None:
                    raise RuntimeError("The pickle does not contain a pDynamo System.")
                model_system = candidate
                model_source_path = path
                break
            except Exception:
                if os.path.realpath(path) not in discovered_snapshots:
                    raise
    if len(model_system.atoms) != len(system.atoms):
        raise RuntimeError("The model template and base system have different atom counts.")
    if model_template:
        for index, (base_atom, model_atom) in enumerate(zip(system.atoms, model_system.atoms)):
            base_number = _as_int(_value(base_atom, "atomicNumber"), 0)
            model_number = _as_int(_value(model_atom, "atomicNumber"), 0)
            if base_number != model_number:
                raise RuntimeError("Model template atom order differs from the base system at atom {} (atomic number {} vs {}).".format(
                    index, base_number, model_number))
    atoms = [_atom_record(atom, i, system=system) for i, atom in enumerate(system.atoms)]
    # When a configured model template is supplied, its coordinates define
    # the actual model frame to import. This is especially important when the
    # base system is an unparameterized topology pickle with stale coordinates.
    coordinates = _coordinates(model_system if model_template else system)
    sidecar_dir = output + ".snapshots"
    if snapshots and not os.path.isdir(sidecar_dir):
        os.makedirs(sidecar_dir)
    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "source": {"file": os.path.basename(source),
                   "label": str(_value(system, "label", "pDynamo2 system")),
                   "pDynamo_class": system.__class__.__name__},
        "atom_count": len(atoms),
        "atoms": atoms,
        "bonds": _bond_records(system, model_system=model_system),
        "coordinates_angstrom": coordinates,
        "model_source": os.path.basename(model_source_path),
        "model_state": _model_manifest(model_system),
        "snapshots": [],
        "limitations": ["Energy model state is preserved as data; only a compatible pDynamo3 importer can rebuild it."],
    }
    skipped = []
    used_sidecar_names = set()
    reserved_frame_names = set()
    for snapshot_path in snapshots:
        snapshot_stem = os.path.splitext(os.path.basename(snapshot_path))[0]
        if re.match(r"^[0-9]{2,}\.[0-9]{2}$", snapshot_stem):
            reserved_frame_names.add(snapshot_stem + ".coords")
    generated_index = 0
    for path in snapshots:
        # The chosen model template is still a trajectory frame. It is only
        # excluded when it is the source/base system itself (handled above).
        try:
            snap_coordinates = _snapshot_coordinates(path)
        except Exception as error:
            if os.path.realpath(path) in discovered_snapshots:
                print("Skipping non-system snapshot {}: {}".format(path, error))
                skipped.append((path, str(error)))
                continue
            raise
        snap_atoms = len(snap_coordinates)
        if snap_atoms != len(atoms):
            error = "Snapshot {} has {} atoms; base system has {}.".format(path, snap_atoms, len(atoms))
            if os.path.realpath(path) in discovered_snapshots:
                print("Skipping incompatible snapshot {}".format(error))
                skipped.append((path, error))
                continue
            raise RuntimeError(error)
        source_name = os.path.splitext(os.path.basename(path))[0]
        source_sidecar = source_name + ".coords"
        if (re.match(r"^[0-9]{2,}\.[0-9]{2}$", source_name) and
                source_sidecar not in used_sidecar_names):
            sidecar_name = source_sidecar
        else:
            while True:
                sidecar_stem = "{:02d}.{:02d}".format(generated_index // 100,
                                                        generated_index % 100)
                generated_index += 1
                sidecar_name = sidecar_stem + ".coords"
                if sidecar_name not in used_sidecar_names and sidecar_name not in reserved_frame_names:
                    break
        used_sidecar_names.add(sidecar_name)
        sidecar_path = os.path.join(sidecar_dir, sidecar_name)
        _write_coordinate_sidecar(sidecar_path, snap_coordinates)
        manifest["snapshots"].append({
            "file": os.path.basename(path),
            "coordinate_file": os.path.relpath(sidecar_path, os.path.dirname(os.path.abspath(output))),
        })
    with open(output, "w") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    model_state = manifest.get("model_state") or {}
    if not model_state.get("state"):
        print("Warning: no energy model was exported; the manifest can be viewed, but it cannot run an energy calculation.", file=sys.stderr)
    if skipped:
        print("Skipped {} incompatible/non-system file(s).".format(len(skipped)), file=sys.stderr)
    print("Wrote {} atoms, {} bonds, {} snapshots ({} skipped) to {}".format(
        len(atoms), len(manifest["bonds"]), len(manifest["snapshots"]), len(skipped), output))


def main():
    parser = argparse.ArgumentParser(description="Export pDynamo2 structure/snapshots to EasyHybrid exchange JSON.")
    parser.add_argument("system_pkl", help="pDynamo2 system pickle")
    parser.add_argument("output_json", help="output exchange JSON")
    parser.add_argument("--model-template", metavar="PKL",
                        help="configured pDynamo2 PKL supplying model settings and starting coordinates")
    parser.add_argument("--snapshot", action="append", default=[], metavar="PKL_OR_XYZ",
                        help="add one coordinate frame; repeat this option for multiple files")
    parser.add_argument("--snapshot-dir", action="append", default=[], metavar="FOLDER",
                        help="add PKL/XYZ frames from a folder; repeat for multiple folders")
    args = parser.parse_args()
    snapshots = args.snapshot + args.snapshot_dir
    try:
        export(args.system_pkl, args.output_json, snapshots, args.model_template)
    except Exception as error:
        print("Export failed: {}".format(error), file=sys.stderr)
        if os.environ.get("EASYHYBRID_EXCHANGE_DEBUG"):
            traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
