# GPU4PySCF integration status

EasyHybrid3 now has an experimental GPU4PySCF option in the QC engine selector.
The adapter supports pure-QC and electrostatic QM/MM calculations using
GPU4PySCF's HF or DFT SCF methods, with PySCF-style basis names (for example,
`def2-svp`) and DFT functional identifiers (for example, `B3LYP`). Density
fitting can be enabled in the setup dialog. QM/MM passes the pDynamo MM point
charges and boundary link charges to GPU4PySCF; pDynamo continues to calculate
the MM and Lennard-Jones terms.

The setup entries autocomplete from the installed PySCF registries. The
functional registry includes aliases and low-level LibXC components, so an
autocomplete suggestion is not a promise that GPU4PySCF implements it. Basis
suggestions exclude aliases marked as density-fitting/auxiliary sets. Basis
availability can still depend on the elements and pseudopotentials in a system.
The adapter uses molecular PySCF objects and rejects periodic systems; it does
not implement periodic boundary conditions. The GUI's spin-restricted option
is honored for singlets, and unrestricted calculations use GPU4PySCF's UHF/UKS
classes. Restricted open-shell calculations are rejected because this adapter
does not provide their gradient path.

### Omega functionals and dispersion names

The names are deliberately passed according to their method meaning:

- `WB97X-D` is the ωB97X-D2 method. The installed GPU4PySCF code marks it
  unsupported. EasyHybrid now reports that limitation rather than silently
  mapping its LibXC component and omitting D2.
- `WB97X-D3BJ` is a separate ωB97X-V-based functional with VV10 disabled and
  D3BJ added. The installed PySCF/GPU4PySCF dispersion parser handles this
  spelling; EasyHybrid preserves the suffix so that correction is not lost.
- `WB97M-D3BJ` is handled by the same special-name path. `WB97X-V` and
  `WB97M-V` retain their VV10 non-local correlation.
- `WB97X-D4` and `WB97M-D4` are retained as SCF-level names and are included in
  the installed-version catalog audit. The audit checks XC evaluation and
  dispersion-name parsing; it is not a molecule-level accuracy benchmark for
  every dispersion variant.

This follows the resolution of [PySCF issue #2069](https://github.com/pyscf/pyscf/issues/2069)
and the GPU4PySCF [ωB97M-D3BJ discussion](https://github.com/pyscf/gpu4pyscf/issues/95).
The GPU4PySCF source checkout was at `b934dac` (`master` and `origin/master`),
the commit shown in the supplied October 1, 2026 history; no update was needed.

GPU4PySCF is an optional external package and is not installed by
`requirements.txt`; it must be installed in the same Python environment as
EasyHybrid3, with compatible PySCF, CuPy, CUDA libraries, and NVIDIA driver.
The EasyHybrid3 installer registers the adapter with the selected pDynamo3
installation.

### Installed PySCF catalog audit

`tools/gpu4pyscf_catalog_audit.py` checks every functional name registered by
the installed PySCF LibXC and alias catalogs, plus selected GPU4PySCF method
names. The generated per-name results are in
[`GPU4PySCF_functional_audit.csv`](GPU4PySCF_functional_audit.csv). In this
installation, 422 names/components passed direct CUDA LibXC energy and
derivative evaluation, and 559 passed through GPU4PySCF's CPU PySCF LibXC
fallback. The latter can still use GPU integrals, but XC evaluation itself is
not GPU accelerated. Sixty-five Laplacian-dependent meta-GGAs are rejected by
GPU4PySCF. Five ωB97X-D2/non-BJ-D3 entries are unavailable as full methods,
three 3c methods need GPU4PySCF's dedicated driver, and `WB97X-D3` is marked
unsupported by the installed GPU4PySCF. Eight catalog entries caused isolated
native CUDA LibXC worker crashes; the EasyHybrid adapter blocks their component
IDs before starting SCF.

The basis catalog audit is in
[`GPU4PySCF_basis_audit.csv`](GPU4PySCF_basis_audit.csv). It examined all 365
PySCF basis aliases. 166 loaded for at least one of H, C, O, Fe, Mo, or Au
without exceeding GPU4PySCF's g-function angular-momentum limit; 55 exceed
that limit, 74 are auxiliary/fitting bases and excluded from the orbital basis
autocomplete, and 70 did not load for this six-element sample. These are
catalog and basis-build checks, not per-basis SCF benchmarks or exhaustive
periodic-table/ECP validation. The prior 24 matched CPU/GPU energy-and-gradient
calculations remain the molecule-level comparison set.

## Current limitations and verification

- The pDynamo-facing adapter does not currently provide dipole moments, bond
  orders, atomic spin populations, or periodic calculations. These properties
  are not inferred from the returned Mulliken charges or energies.

- A GPU-backed QM/MM energy and gradient calculation completed for a
  pDynamo alanine-dipeptide example with a four-atom QM selection and OPLS MM
  surroundings (20 embedded MM/link charges). Two more pDynamo examples also
  completed: a water dimer with one water in QM and three MM charges, and
  cyclohexane with a three-atom QM selection, 19 embedded charges, and six
  boundary/link charges. In each case, the analytic gradient on one MM
  coordinate agreed with a central finite difference using a `0.0005 Å`
  displacement:

  | System | Analytic (kJ mol-1 Å-1) | Finite difference | Absolute difference |
  | --- | ---: | ---: | ---: |
  | Alanine dipeptide | -2.0929973 | -2.0927908 | 0.000207 |
  | Water dimer | 2.4848682 | 2.4851875 | 0.000319 |
  | Cyclohexane | 5.8501268 | 5.8501255 | 0.0000014 |

  These are integration checks using HF/STO-3G, not QM/MM accuracy benchmarks.

- CPU PySCF and GPU4PySCF were also run independently with identical
  coordinates, HF/STO-3G density fitting, MM point charges, and link charges.
  Their embedded QM energies agreed to the printed precision (12 decimal
  places). Maximum absolute gradient differences are in Hartree/Bohr:

  | System | Embedded charges | Energy difference (Eh, printed) | QM gradient max difference | MM gradient max difference |
  | --- | ---: | ---: | ---: | ---: |
  | Alanine dipeptide | 20 | 1e-12 | 8.9e-8 | 3.9e-9 |
  | Water dimer | 3 | 3e-12 | 5.9e-7 | 2.7e-8 |
  | Cyclohexane | 19 (6 boundary/link) | 9e-12 | 7.1e-7 | 3.9e-9 |

  The force-field MM terms are the same in both comparisons, so they do not
  affect the backend-to-backend differences. These checks establish agreement
  for these matched HF/STO-3G cases only.
- GPU4PySCF 1.8.1 and PySCF 2.14.0 are installed in the active EasyHybrid/pDynamo3
  Python environment, and the adapter is registered in pDynamo3's QCModel package.
- The official GPU4PySCF water example uses B3LYP/def2-TZVPP and reports
  `-76.46668196729536 Eh`. On its exact geometry, the pDynamo adapter returned
  `-76.466681993767 Eh` on the RTX 4060 Ti (difference `-2.65e-8 Eh`), converged,
  and returned a `(3, 3)` gradient. Energy plus gradient took 4.620 s in this
  single run. [Example source](https://github.com/pyscf/gpu4pyscf/blob/master/examples/dft/00-h2o.py).
- A CPU PySCF/GPU4PySCF matrix was run on the same isolated water geometry,
  without density fitting, at grid level 4. All 24 combinations completed:
  B3LYP, PBE0, M06-L, WB97X-V, WB97X-D3BJ, and WB97M-D3BJ with 6-31G*,
  6-31+G*, 6-31++G**, and 6-311++G(2d,2p). The largest energy difference was
  `3.29e-8 Eh` (WB97X-V/6-311++G(2d,2p)); the largest gradient difference
  was `2.41e-7 Eh/Bohr`. The D3BJ variants matched within `2.3e-12 Eh` in
  energy. These timings are omitted because another process was saturating the
  GPU during the run.
- The installed adapter also completed a pDynamo energy-plus-gradient run for
  WB97X-D3BJ/6-31G*. A corresponding WB97X-D request now raises a clear
  unsupported-D2 error. This checks the adapter route, while the 24-case
  matrix above checks GPU4PySCF directly against CPU PySCF.
- Density fitting can change CPU/GPU agreement by more than the integration
  tolerance for some tested PBE and M06-L/def2 combinations (up to about
  `1e-4 Eh` in the earlier matrix). For def2-SVP, the same CPU/GPU PBE and
  M06-L calculations agreed to about `4e-12 Eh` without density fitting.
  Treat density-fitted meta-GGA results as unverified until this backend
  discrepancy is resolved; the 24-case matrix above intentionally disables it.
- MOPAC 23.2.5 is installed under the shared software tree and selected
  by `PDYNAMO3_MOPACCOMMAND` in the environment activation script. Its QC
  adapter is registered in pDynamo. Using the exact geometry in MOPAC's
  official PM7 water example, the pDynamo adapter returned `-241.37629021`
  kJ/mol versus the archived `-241.37622` kJ/mol (difference
  `-0.00007021 kJ/mol`) and a `(3, 3)` gradient. Energy plus gradient took
  0.0391 s. The archived example reports 0.02 s for its SCF-only run; that is
  not a like-for-like timing comparison. [Input](https://github.com/openmopac/mopac/blob/main/examples/example_scf.mop),
  [archived output](https://github.com/openmopac/mopac/blob/main/examples/example_scf.mop_output).

Both backends are verified through pDynamo's `System` QC-model interface. The
GTK setup dialogs were not exercised during these calculations.
