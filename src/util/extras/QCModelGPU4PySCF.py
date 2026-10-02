"""pDynamo QC model backed by GPU4PySCF.

GPU4PySCF is used in-process.  Coordinates and gradients at this boundary are
in atomic units, as required by pDynamo's QCModel contract.
"""

import os
import tempfile

from pCore import NotInstalledError
from pScientific import PeriodicTable, Units
from pScientific.Arrays import Array
from .QCDefinitions import ChargeModel
from .QCModel import QCModel
from .QCModelError import QCModelError


_Scratch = os.path.join(os.getenv("PDYNAMO3_SCRATCH", tempfile.gettempdir()), "GPU4PySCFScratch")


def _GPUFunctionalName(functional):
    """Resolve safe single-name aliases without changing method semantics.

    Dispersion and non-local-correlation names must reach GPU4PySCF intact:
    its SCF layer decodes those suffixes to attach the matching correction.
    In particular, omegaB97X-D means the D2-corrected method, which the
    installed GPU4PySCF version explicitly does not implement. Mapping it to
    the LibXC XC component alone would silently omit D2.
    """
    name = str(functional).strip()
    lower = name.lower().replace("_", "-")
    if lower in ("wb97x-d", "wb97x-d2", "wb97x-d3"):
        raise ValueError(
            "GPU4PySCF does not implement omegaB97X-D2 or the non-BJ omegaB97X-D3 "
            "method. Use the distinct supported WB97X-D3BJ variant, or choose another functional."
        )
    if lower in ("wb97x-3c", "b97-3c", "r2scan-3c", "r2scan3c", "b973c"):
        raise ValueError(
            "{} requires GPU4PySCF's dedicated three-component driver (its own "
            "basis/ECP and GCP/dispersion setup), which this EasyHybrid adapter "
            "does not expose yet.".format(name)
        )
    if "-d3" in lower or "-d4" in lower or lower.endswith("-v"):
        return name
    try:
        from pyscf.dft import libxc
        factors = libxc.parse_xc(name)[1]
    except Exception:
        factors = ()
    if factors:
        identifiers = [factor[0] for factor in factors]
        # These components terminate the native CUDA worker or do not provide
        # usable XC energy/derivative pairs in this backend.
        dangerous_names = ("GGA_X_LB", "GGA_X_LBM", "LDA_XC_TIH",
                           "HYB_GGA_X_SOGGA11_X", "HYB_GGA_X_SOGGA11X",
                           "HYB_MGGA_XC_REVTPSSH")
        dangerous_ids = {libxc.XC_CODES[item] for item in dangerous_names
                         if item in libxc.XC_CODES}
        unsafe_ids = [identifier for identifier in identifiers
                      if identifier in dangerous_ids]
        if unsafe_ids:
            raise ValueError(
                "GPU4PySCF CUDA LibXC evaluation crashes for this functional "
                "(LibXC ID {}). It is blocked to protect the running process.".format(
                    unsafe_ids[0])
            )
        if any(libxc.needs_laplacian(identifier) for identifier in identifiers):
            raise ValueError(
                "GPU4PySCF does not implement meta-GGA functionals that require "
                "the density Laplacian."
            )
    if len(factors) == 1 and float(factors[0][1]) == 1.0:
        identifier = factors[0][0]
        if identifier in (399, 471):
            variant = "omegaB97X-D3" if identifier == 399 else "omegaB97X-D2"
            raise ValueError(
                "GPU4PySCF does not implement the full {} method; its bare LibXC "
                "component would omit the dispersion correction. Use WB97X-D3BJ "
                "or choose another functional.".format(variant)
            )
        candidates = [candidate for (candidate, value) in libxc.XC_CODES.items()
                      if value == identifier and "_XC_" in candidate]
        if candidates:
            return sorted(candidates, key=lambda candidate: (-candidate.count("_"), candidate))[0]
    return name


class QCModelGPU4PySCF(QCModel):
    """GPU accelerated HF/DFT model using the GPU4PySCF package."""

    _attributable = dict(QCModel._attributable)
    _classLabel = "GPU4PySCF QC Model"
    _summarizable = dict(QCModel._summarizable)
    _attributable.update({
        "method": "DFT",
        "basis": "def2-svp",
        "functional": "B3LYP",
        "densityFitting": True,
        "maxCycles": 100,
        "convTolerance": 1.0e-9,
        "scratch": _Scratch,
    })
    _summarizable.update({
        "method": "Method", "basis": "Basis Set", "functional": "XC Functional",
        "densityFitting": "Density Fitting", "scratch": "Scratch Directory",
    })

    def BuildModel(self, target, qcSelection=None):
        state = super(QCModelGPU4PySCF, self).BuildModel(target, qcSelection=qcSelection)
        os.makedirs(self.scratch, exist_ok=True)
        return state

    def Energy(self, target):
        """Calculate a GPU4PySCF energy and, when requested, its gradient."""
        try:
            import cupy as cp
            import numpy as np
            from pyscf import gto
            from gpu4pyscf import dft, scf
        except Exception as exc:
            raise NotInstalledError(
                "GPU4PySCF could not be loaded. Activate EasyHybrid3's pDynamo3 "
                "environment and check CUDA visibility. Original error: {}".format(exc)
            )

        state = getattr(target, self.__class__._stateName)
        coords = target.scratch.qcCoordinates3AU
        atoms = [(PeriodicTable.Symbol(int(z)), tuple(float(coords[i, j]) for j in range(3)))
                 for i, z in enumerate(state.atomicNumbers)]
        spin = int(target.electronicState.multiplicity) - 1
        mol = gto.Mole()
        mol.atom = atoms
        mol.unit = "Bohr"
        mol.basis = self.basis
        mol.charge = int(target.electronicState.charge)
        mol.spin = spin
        mol.verbose = 0
        mol.output = os.path.join(self.scratch, "gpu4pyscf.log")
        try:
            mol.build()
            if self.method.upper() == "HF":
                mf = scf.UHF(mol) if spin else scf.RHF(mol)
            elif self.method.upper() == "DFT":
                mf = dft.UKS(mol) if spin else dft.RKS(mol)
                mf.xc = _GPUFunctionalName(self.functional)
            else:
                raise QCModelError("GPU4PySCF method must be HF or DFT (got {!r}).".format(self.method))

            mf.max_cycle = int(self.maxCycles)
            mf.conv_tol = float(self.convTolerance)
            mf.verbose = 0
            if self.densityFitting:
                mf = mf.density_fit()
            mm_coordinates = getattr(target.scratch, "gpu4pyscfMMCoordinatesBohr", None)
            mm_charges = getattr(target.scratch, "gpu4pyscfMMCharges", None)
            if mm_coordinates is not None and len(mm_charges):
                from gpu4pyscf.qmmm.itrf import mm_charge
                mf = mm_charge(mf, mm_coordinates, mm_charges, unit="Bohr")
            energy = float(mf.kernel())
            if not mf.converged:
                raise QCModelError("GPU4PySCF SCF did not converge after {} cycles.".format(self.maxCycles))
            if target.scratch.doGradients:
                grad_method = mf.Gradients()
                gradients = cp.asnumpy(grad_method.kernel())
                if gradients.shape != (len(state.atomicNumbers), 3):
                    raise QCModelError("GPU4PySCF returned gradients with unexpected shape {}.".format(gradients.shape))
                for i in range(gradients.shape[0]):
                    for j in range(3):
                        target.scratch.qcGradients3AU[i, j] = gradients[i, j]
                if mm_coordinates is not None and len(mm_charges):
                    density = mf.make_rdm1()
                    if density.ndim == 3:
                        density = density[0] + density[1]
                    mm_gradients = cp.asnumpy(grad_method.grad_hcore_mm(density) + grad_method.grad_nuc_mm())
                    target.scratch.gpu4pyscfMMGradientsAU = mm_gradients
            target.scratch.energyTerms["GPU4PySCF QC"] = energy * Units.Energy_Hartrees_To_Kilojoules_Per_Mole

            from pyscf.scf import hf as pyscf_hf
            density = cp.asnumpy(mf.make_rdm1())
            overlap = cp.asnumpy(mf.get_ovlp())
            charges = np.asarray(pyscf_hf.mulliken_pop(mol, density, s=overlap, verbose=0)[1], dtype=float)
            mulliken = Array.WithExtent(len(charges))
            for i, value in enumerate(charges):
                mulliken[i] = float(value)
            target.scratch.gpu4pyscfOutputData = {"Mulliken Charges": mulliken}
        except QCModelError:
            raise
        except Exception as exc:
            raise QCModelError("GPU4PySCF calculation failed: {}".format(exc))

    def AtomicCharges(self, target, chargeModel=ChargeModel.Mulliken):
        data = getattr(target.scratch, "gpu4pyscfOutputData", {})
        return data.get("Mulliken Charges")

    def DipoleMoment(self, target, center=None):
        # GPU4PySCF's current pDynamo adapter does not calculate dipole moments.
        return None

    def SummaryItems(self):
        return super(QCModelGPU4PySCF, self).SummaryItems()
