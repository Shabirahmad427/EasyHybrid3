#!/usr/bin/env python3
"""Audit the installed PySCF functional and basis catalogs for GPU4PySCF.

Run inside the EasyHybrid/pDynamo Python environment on a visible CUDA GPU.
The functional check evaluates the XC energy and first derivative at a small
test density on the GPU. It is a backend capability check, not a SCF accuracy
benchmark. The basis check verifies PySCF element coverage and the GPU4PySCF
orbital angular-momentum limit; it does not run a molecular SCF for every set.
"""

import csv
import os
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict

import cupy
import numpy as np
from pyscf import gto
from pyscf.dft import libxc
from pyscf.gto import basis

from gpu4pyscf.dft.numint import NumInt
from gpu4pyscf.dft import libxc as gpu_libxc
from gpu4pyscf.scf.dispersion import parse_dft


HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs")
FUNCTIONAL_CSV = os.path.join(OUT, "GPU4PySCF_functional_audit.csv")
BASIS_CSV = os.path.join(OUT, "GPU4PySCF_basis_audit.csv")
FUNCTIONAL_FIELDS = ("catalog_index", "catalog", "name", "family", "libxc_ids",
                     "hybrid", "range_separated", "needs_laplacian", "gpu_xc",
                     "status", "detail")


def _csv_writer(path, fields):
    stream = open(path, "w", newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    return stream, writer


def _functional_catalog():
    entries = OrderedDict()
    for name in libxc.XC_CODES:
        entries[("LibXC", name)] = {"catalog": "LibXC", "name": name}
    for name in libxc.XC_ALIAS:
        entries[("PySCF alias", name)] = {"catalog": "PySCF alias", "name": name}
    # These are PySCF/GPU4PySCF SCF-level names rather than LibXC codes.
    for name in ("WB97X-D3BJ", "WB97M-D3BJ", "B97M-D3BJ", "WB97X-D4",
                 "WB97M-D4", "WB97X-3C", "B97-3C", "R2SCAN-3C", "CF22D",
                 "WB97X-D", "WB97X-D3"):
        entries[("GPU4PySCF method", name)] = {
            "catalog": "GPU4PySCF method", "name": name
        }
    return list(entries.values())


def _density(family, points=16):
    if family == "LDA":
        return cupy.full(points, 0.6, dtype=cupy.float64)
    if family == "GGA":
        rho = cupy.zeros((4, points), dtype=cupy.float64)
        rho[0] = 0.6
        rho[1:4] = 0.01
        return rho
    if family == "MGGA":
        rho = cupy.zeros((5, points), dtype=cupy.float64)
        rho[0] = 0.6
        rho[1:4] = 0.01
        rho[4] = 0.15
        return rho
    raise ValueError("Unrecognized XC family {!r}".format(family))


def _finite_tree(value):
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return all(_finite_tree(item) for item in value)
    array = cupy.asarray(value)
    return bool(cupy.isfinite(array).all().get())


def _functional_row(index, entry, ni, gpu_ids, marker_path=None):
    name = entry["name"]
    row = dict(entry, catalog_index=index, family="", libxc_ids="", hybrid="",
               range_separated="", needs_laplacian="", gpu_xc="", status="", detail="")
    low = name.strip().lower().replace("_", "-")
    try:
        if low in ("wb97x-3c", "b97-3c", "r2scan-3c", "r2scan3c", "b973c"):
            row.update(status="requires_dedicated_driver",
                       detail="GPU4PySCF 3c methods need their method-specific basis/ECP and correction path")
            return row
        # GPU4PySCF documents the D2 and non-BJ D3 methods as unsupported.
        # The canonical LibXC IDs alone omit the corresponding correction.
        hyb, factors = libxc.parse_xc(name)
        ids = sorted(set(int(identifier) for identifier, weight in factors))
        family = libxc.xc_type(name)
        needs_lapl = any(libxc.needs_laplacian(identifier) for identifier in ids)
        gpu_ok = all(identifier in gpu_ids for identifier in ids)
        row.update(family=family, libxc_ids=";".join(map(str, ids)),
                   hybrid=bool(libxc.is_hybrid_xc(name)),
                   range_separated=bool(hyb[2]), needs_laplacian=needs_lapl,
                   gpu_xc=gpu_ok)

        if ids in ([471], [399]) or low in ("wb97x-d", "wb97x-d2", "wb97x-d3"):
            row.update(status="unsupported_method",
                       detail="GPU4PySCF does not implement this named dispersion variant")
        elif needs_lapl:
            row.update(status="unsupported_laplacian",
                       detail="GPU4PySCF NumInt rejects meta-GGA functionals requiring density Laplacian")
        else:
            parsed_method = parse_dft(name)
            if "-d3" in low or "-d4" in low:
                if parsed_method[2] is None:
                    raise ValueError("dispersion suffix did not resolve")
            # Keep the worker marker set across both CUDA LibXC initialization
            # and evaluation; either may terminate the native process.
            if marker_path is not None:
                with open(marker_path, "w") as marker:
                    marker.write("{}\t{}\n".format(index, name))
                    marker.flush()
            xc, vxc, _, _ = ni.eval_xc_eff(name, _density(family), deriv=1)
            cupy.cuda.get_current_stream().synchronize()
            if not _finite_tree((xc, vxc)):
                raise ArithmeticError("GPU XC evaluation returned a non-finite value")
            if gpu_ok:
                row.update(status="gpu_xc_pass",
                           detail="CUDA LibXC energy density and first derivative finite")
            else:
                row.update(status="cpu_xc_fallback_pass",
                           detail="GPU4PySCF evaluated one or more XC components through CPU PySCF LibXC")
    except NotImplementedError as error:
        row.update(status="unsupported_by_gpu4pyscf", detail=str(error).replace("\n", " "))
    except Exception as error:
        row.update(status="failed", detail="{}: {}".format(type(error).__name__, str(error).replace("\n", " ")))
    return row


def _functional_worker_main(start, output_path, marker_path):
    out_stream = open(output_path, "w", newline="")
    writer = csv.DictWriter(out_stream, fieldnames=FUNCTIONAL_FIELDS)
    writer.writeheader()
    ni = NumInt()
    gpu_ids = set(int(value) for value in gpu_libxc.XC_IDS)
    entries = _functional_catalog()
    for index in range(start, len(entries)):
        row = _functional_row(index, entries[index], ni, gpu_ids, marker_path=marker_path)
        writer.writerow(row)
        out_stream.flush()
        if os.path.exists(marker_path):
            os.unlink(marker_path)
        if (index + 1) % 100 == 0:
            print("Functional names audited:", index + 1, flush=True)
    out_stream.close()


def audit_functionals():
    entries = _functional_catalog()
    results = {}
    with open(FUNCTIONAL_CSV, "w", newline="") as final_stream:
        final_writer = csv.DictWriter(final_stream, fieldnames=FUNCTIONAL_FIELDS)
        final_writer.writeheader()
        with tempfile.TemporaryDirectory(prefix="gpu4pyscf-functional-audit-") as temp_dir:
            start = 0
            while start < len(entries):
                child_csv = os.path.join(temp_dir, "functional_child.csv")
                marker_path = os.path.join(temp_dir, "active_functional.txt")
                command = [sys.executable, os.path.abspath(__file__), "--functional-worker",
                           str(start), child_csv, marker_path]
                process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True,
                                           env=os.environ.copy())
                for line in process.stdout:
                    print(line, end="", flush=True)
                return_code = process.wait()
                failed_index = None
                crashed_name = None
                if return_code != 0 and os.path.exists(marker_path):
                    with open(marker_path) as marker:
                        index_text, crashed_name = marker.read().strip().split("\t", 1)
                    failed_index = int(index_text)
                completed = []
                if os.path.exists(child_csv):
                    with open(child_csv, newline="") as child_stream:
                        for row in csv.DictReader(child_stream):
                            if failed_index is not None and int(row["catalog_index"]) == failed_index:
                                continue
                            completed.append(row)
                            final_writer.writerow(row)
                            final_stream.flush()
                            results[row["status"]] = results.get(row["status"], 0) + 1
                if return_code == 0:
                    start = len(entries)
                    continue
                if failed_index is None:
                    raise RuntimeError("Functional audit child exited {} without an active-name marker".format(return_code))
                crashed_entry = entries[failed_index]
                failure_row = dict(crashed_entry, catalog_index=failed_index, family="",
                                   libxc_ids="", hybrid="", range_separated="",
                                   needs_laplacian="", gpu_xc="", status="gpu_kernel_crash",
                                   detail="Native CUDA LibXC initialization/evaluation crashed the worker process")
                final_writer.writerow(failure_row)
                final_stream.flush()
                results["gpu_kernel_crash"] = results.get("gpu_kernel_crash", 0) + 1
                print("Isolated GPU functional crash:", crashed_name,
                      "(catalog index", failed_index, ")", flush=True)
                start = failed_index + 1
    return results


def _is_auxiliary(name):
    lower = name.lower()
    return lower.endswith(("fit", "jkfit", "jfit", "cfit", "xfit", "ri")) or lower in (
        "weigend", "weigend+etb", "demon", "ahlrichs")


def audit_basis():
    fields = ("name", "catalog_kind", "elements_loaded", "elements_missing", "max_l",
              "nao_hco", "gpu_orbital_limit", "status", "detail")
    stream, writer = _csv_writer(BASIS_CSV, fields)
    elements = ("H", "C", "O", "Fe", "Mo", "Au")
    basis_names = sorted(basis.ALIAS, key=str.lower)
    llimit = 4  # g functions; see the GPU4PySCF README.
    counts = {}

    for index, name in enumerate(basis_names, 1):
        if _is_auxiliary(name):
            writer.writerow({"name": name, "catalog_kind": "auxiliary/fitting",
                             "elements_loaded": "", "elements_missing": "",
                             "max_l": "", "nao_hco": "", "gpu_orbital_limit": llimit,
                             "status": "not_orbital_basis", "detail": "Excluded from EasyHybrid orbital-basis suggestions"})
            counts["not_orbital_basis"] = counts.get("not_orbital_basis", 0) + 1
            continue

        loaded, missing, max_l, nao_hco = [], [], [], ""
        for element in elements:
            atom = "{} 0 0 0".format(element)
            spin = int(gto.mole.charge(element)) % 2
            try:
                mol = gto.M(atom=atom, basis=name, spin=spin, verbose=0)
                loaded.append(element)
                max_l.append(int(mol._bas[:, gto.ANG_OF].max()))
                if element in ("H", "C", "O"):
                    nao_hco += "{}:{};".format(element, mol.nao_nr())
            except Exception as error:
                missing.append("{}({})".format(element, type(error).__name__))

        highest_l = max(max_l) if max_l else ""
        if not loaded:
            status = "no_test_elements"
            detail = "No basis data loaded for tested elements"
        elif highest_l > llimit:
            status = "above_gpu_orbital_limit"
            detail = "Contains angular momentum l={}, above g (l=4)".format(highest_l)
        else:
            status = "orbital_basis_loads"
            detail = "Basis data loaded; SCF compatibility still requires calculation-level verification"
        writer.writerow({"name": name, "catalog_kind": "orbital candidate",
                         "elements_loaded": ";".join(loaded), "elements_missing": ";".join(missing),
                         "max_l": highest_l, "nao_hco": nao_hco.rstrip(";"),
                         "gpu_orbital_limit": llimit, "status": status, "detail": detail})
        counts[status] = counts.get(status, 0) + 1
        if index % 50 == 0:
            print("Basis aliases audited:", index, flush=True)

    stream.close()
    return counts


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--functional-worker":
        _functional_worker_main(int(sys.argv[2]), sys.argv[3], sys.argv[4])
        sys.exit(0)
    if not cupy.cuda.is_available():
        sys.exit("CUDA device not available")
    print("PySCF functional names:", len(libxc.XC_CODES),
          "aliases:", len(libxc.XC_ALIAS), "GPU CUDA LibXC IDs:", len(gpu_libxc.XC_IDS))
    print("Functional audit:", audit_functionals())
    print("Basis audit:", audit_basis())
    print("Wrote:", os.path.abspath(FUNCTIONAL_CSV))
    print("Wrote:", os.path.abspath(BASIS_CSV))
