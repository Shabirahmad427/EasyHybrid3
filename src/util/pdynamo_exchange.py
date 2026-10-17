"""Read the version-neutral pDynamo2 exchange format.

The exchange format intentionally contains no executable pickle payloads.
Compatible saved model data is rebuilt as native pDynamo3 energy models;
unsupported model classes are rejected during import.
"""

import json
import os

import numpy as np
from pMolecule.MMModel import MMModel as _MMModelBase


EXCHANGE_FORMAT = "easyhybrid-pdynamo-exchange"
EXCHANGE_VERSION = 1


def _skip_active_atom_total_charge_check():
    """Allow pDynamo2's fractional active-MM charge during model building."""
    return None


class ExchangeMMModel(_MMModelBase):
    """MM model carrying portable pDynamo2 parameter state for rebuilding."""

    _attributable = dict(_MMModelBase._attributable)
    _attributable["exchangeStatePayload"] = None

    def BuildModel(self, target, **options):
        super(ExchangeMMModel, self).BuildModel(target, **options)
        state = getattr(target, "mmState", None)
        if state is None:
            raise ValueError("pDynamo3 did not create an MM state for the exchange model.")
        for key, value in (self.exchangeStatePayload or {}).items():
            setattr(state, key, value)
        return state


class ExchangeMNDOLoewdinEvaluator:
    """pDynamo2 MNDO's diagonal-density charge coupling for pDynamo3."""

    def FockMultipoles(self, target, multipoleOrder, multipoles,
                       density=None, withNuclei=True):
        if multipoleOrder != 0:
            raise ValueError("pDynamo2 MNDO Lowdin coupling supports charge monopoles only.")
        qc_state = target.qcState
        if withNuclei:
            qc_state.nuclearCharges.CopyTo(multipoles)
        else:
            multipoles.Set(0.0)
        density_matrix = target.scratch.onePDMP.density if density is None else density
        basis_indices = qc_state.orbitalBases.centerFunctionPointers
        for atom_index in range(len(qc_state.qcAtoms)):
            population = 0.0
            for basis_index in range(int(basis_indices[atom_index]),
                                     int(basis_indices[atom_index + 1])):
                population += density_matrix[basis_index, basis_index]
            multipoles[atom_index] -= population

    def FockMultipoleDerivatives(self, target, multipoleOrder, dXdQ, dXdP):
        if multipoleOrder != 0:
            raise ValueError("pDynamo2 MNDO Lowdin coupling supports charge monopoles only.")
        basis_indices = target.qcState.orbitalBases.centerFunctionPointers
        for atom_index in range(len(target.qcState.qcAtoms)):
            potential = -float(dXdQ[atom_index])
            for basis_index in range(int(basis_indices[atom_index]),
                                     int(basis_indices[atom_index + 1])):
                dXdP[basis_index, basis_index] += potential


class ExchangeBoundaryIdentifier:
    """Return boundary data preserved from a pDynamo2 QC atom container."""

    def __init__(self, boundary_map):
        self.boundary_map = boundary_map

    def __call__(self, selection):
        return self.boundary_map


def load_exchange_system(path):
    """Build a pDynamo3 System from an exchange JSON manifest.

    Returns ``(system, manifest)``. Any absent, inconsistent, or unsupported
    structural data raises ``ValueError`` rather than being silently guessed.
    """
    from pMolecule import Atom, Bond, BondType, Connectivity, ConvertInputConnectivity, RestraintModel, System
    from pCore import Selection, SelfPairList
    from pScientific.Geometry3 import Coordinates3

    with open(path, "r") as stream:
        manifest = json.load(stream)
    if manifest.get("format") != EXCHANGE_FORMAT:
        raise ValueError("This is not an EasyHybrid pDynamo exchange file.")
    if manifest.get("format_version") != EXCHANGE_VERSION:
        raise ValueError("Unsupported exchange format version: {}".format(manifest.get("format_version")))

    atoms = manifest.get("atoms")
    bonds = manifest.get("bonds")
    coordinates = manifest.get("coordinates_angstrom")
    expected = manifest.get("atom_count")
    if not isinstance(atoms, list) or not atoms or expected != len(atoms):
        raise ValueError("The exchange manifest has inconsistent or empty atom data.")
    if not isinstance(coordinates, list) or len(coordinates) != len(atoms):
        raise ValueError("The coordinate count does not match the atom count.")
    for i, xyz in enumerate(coordinates):
        if not isinstance(xyz, list) or len(xyz) != 3:
            raise ValueError("Invalid coordinate record for atom {}.".format(i))
        try:
            [float(v) for v in xyz]
        except (TypeError, ValueError):
            raise ValueError("Non-numeric coordinates for atom {}.".format(i))

    connectivity = Connectivity()
    for i, data in enumerate(atoms):
        if data.get("index") != i:
            raise ValueError("Atom indices must be contiguous and ordered from zero.")
        atomic_number = int(data.get("atomic_number", 0))
        if atomic_number <= 0:
            raise ValueError("Atom {} has no valid atomic number.".format(i))
        connectivity.AddNode(Atom.WithOptions(
            atomicNumber=atomic_number,
            label=str(data.get("name", "X{}".format(i + 1))),
            formalCharge=int(data.get("formal_charge", 0))))

    bond_types = {"single": BondType.Single, "double": BondType.Double, "triple": BondType.Triple}
    for k, data in enumerate(bonds or []):
        pair = data.get("atoms")
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Invalid atom indices for bond {}.".format(k))
        i, j = int(pair[0]), int(pair[1])
        if i < 0 or j < 0 or i >= len(atoms) or j >= len(atoms) or i == j:
            raise ValueError("Bond {} references an invalid atom.".format(k))
        type_name = str(data.get("type", "")).lower()
        bond_type = next((value for name, value in bond_types.items() if name in type_name), None)
        if bond_type is None:
            # Aromatic/undefined bonds remain explicitly undefined. Do not
            # invent a single/double assignment that could alter chemistry.
            bond_type = BondType.Undefined
        connectivity.AddEdge(Bond.WithNodes(
            connectivity.nodes[i], connectivity.nodes[j],
            isAromatic=bool(data.get("aromatic", False)), type=bond_type))

    ConvertInputConnectivity(connectivity, {})
    system = System.FromConnectivity(connectivity=connectivity)
    source = manifest.get("source", {})
    system.label = str(source.get("label") or "Imported pDynamo2 structure")
    system.sequence_from_mol2 = [
        "*:{}.{}:{}".format(
            data.get("residueName", "UNK"),
            data.get("residueNumber", 1),
            data.get("name", "X{}".format(i + 1)))
        for i, data in enumerate(atoms)
    ]
    coords = Coordinates3.WithExtent(len(atoms))
    for i, xyz in enumerate(coordinates):
        coords[i, 0], coords[i, 1], coords[i, 2] = [float(v) for v in xyz]
    system.coordinates3 = coords
    system.e_exchange_manifest = manifest
    snapshots = manifest.get("snapshots", [])
    frames = np.empty((max(1, len(snapshots)), len(atoms), 3), dtype=np.float32)
    first_frame_coordinates = None
    if not snapshots:
        frames[0] = np.asarray(coordinates, dtype=np.float32)
    for frame_index, snapshot in enumerate(snapshots):
        frame = snapshot.get("coordinates_angstrom")
        coordinate_file = snapshot.get("coordinate_file")
        if coordinate_file:
            manifest_dir = os.path.realpath(os.path.dirname(os.path.abspath(path)))
            coordinate_path = os.path.realpath(os.path.join(manifest_dir, coordinate_file))
            if os.path.commonpath([manifest_dir, coordinate_path]) != manifest_dir:
                raise ValueError("Snapshot coordinate path escapes the exchange folder.")
            try:
                frame = np.loadtxt(coordinate_path, dtype=np.float64, ndmin=2)
            except (ValueError, OSError) as error:
                raise ValueError("Invalid coordinate sidecar {}: {}".format(coordinate_file, error))
        frame = np.asarray(frame, dtype=np.float64)
        if frame.shape != (len(atoms), 3) or not np.isfinite(frame).all():
            raise ValueError("Snapshot {} has a coordinate count that differs from the system.".format(snapshot.get("file", "?")))
        if frame_index == 0:
            first_frame_coordinates = frame.copy()
        frames[frame_index] = frame.astype(np.float32)
    if snapshots:
        # The exchange system's coordinates must correspond to the first
        # trajectory frame so an immediate Energy() call evaluates the frame
        # shown on import, rather than a stale base-system coordinate set.
        # Keep full precision for calculations; viewer frames are float32.
        for i in range(len(atoms)):
            system.coordinates3[i, 0], system.coordinates3[i, 1], system.coordinates3[i, 2] = first_frame_coordinates[i]
    system.e_exchange_frames = frames
    model_state = manifest.get("model_state")
    if model_state and model_state.get("state"):
        _restore_energy_models(system, model_state)
        system.e_exchange_requires_energy_model = False
    else:
        system.e_exchange_requires_energy_model = True
        system.e_exchange_model_report = {
            "energy_model": "Missing",
            "message": "This exchange file contains structure and coordinates only. Export again from a configured pDynamo2 system to run calculations.",
        }
    return system, manifest


def _tag_state(record):
    if not isinstance(record, dict) or "__class__" not in record:
        raise ValueError("Malformed serialized pDynamo model object.")
    return record["state"]


def _restore_raw_container(record, module, class_aliases=None):
    """Restore a pDynamo container state into its pDynamo3 counterpart."""
    import importlib
    name = record.get("__class__")
    name = (class_aliases or {}).get(name, name)
    cls = getattr(importlib.import_module(module), name, None)
    if cls is None or not hasattr(cls, "Raw"):
        raise ValueError("pDynamo3 does not provide a raw container for {}.".format(name))
    obj = cls.Raw()
    obj.__setstate__(record.get("state", {}))
    return obj


def _restore_pair_list(record):
    from pCore import SelfPairList
    state = _tag_state(record)
    items = state.get("items", [])
    if len(items) % 2:
        raise ValueError("Serialized pair list has an odd number of indices.")
    return SelfPairList.FromIndexPairs([int(i) for i in items])


def _restore_energy_models(system, model_manifest):
    """Rebuild model bundles for which pDynamo2/pDynamo3 mappings are known."""
    import importlib
    from pCore import DataType, Selection
    from pMolecule.MMModel import (MMModel, MMModelState, HarmonicBondContainer, LJForm,
                                   HarmonicAngleContainer, FourierDihedralContainer,
                                   LJParameterContainer)
    from pMolecule.QCModel import (ElectronicState, QCModelMNDO, DIISSCFConverger,
                                   MullikenMultipoleEvaluator)
    from pMolecule.NBModel import (NBModelCutOff, PairwiseInteractionABFS,
                                   PairwiseInteractionSplineABFS, SplineModel)
    from pMolecule import RestraintModel
    from pMolecule.Restraint import (RestraintEnergyModel, RestraintMultipleDistance,
                                     RestraintDistance, RestraintAngleDotProduct)
    from pScientific.Arrays import Array
    from pScientific.Geometry3 import PairListGenerator

    data = model_manifest.get("state", {})
    mm_model = data.get("mmModel", {})
    qc_model = data.get("qcModel", {})
    nb_model = data.get("nbModel", {})
    source_mm_class = mm_model.get("__class__")
    source_qc_class = qc_model.get("__class__")
    source_nb_class = nb_model.get("__class__")
    supported_mm = source_mm_class in {"MMModelAMBER", "MMModelCHARMM", "MMModelDYFF", "MMModelOPLS"}
    supported_qc = source_qc_class == "QCModelMNDO"
    supported_nb = source_nb_class == "NBModelABFS"
    if not (supported_mm and supported_qc and supported_nb):
        raise ValueError("Unsupported energy model combination: MM={}, QC={}, NB={}. Supported translations: MM in AMBER/CHARMM/DYFF/OPLS, QC=MNDO-family, NB=ABFS.".format(
            source_mm_class, source_qc_class, source_nb_class))

    mm_atoms = _tag_state(data.get("mmAtoms", {}))
    fields = mm_atoms.get("atomFields", [])
    try:
        active_i, type_i, lj_i, charge_i = [fields.index(key) for key in ("isActive", "atomType", "ljType", "charge")]
    except ValueError:
        raise ValueError("The pDynamo2 MM atom table has an unsupported layout.")
    rows = mm_atoms.get("atoms", [])
    if len(rows) != len(system.atoms):
        raise ValueError("The MM atom table count does not match the molecular structure.")
    charges = Array.FromIterable([float(row[charge_i]) for row in rows], dataType=DataType.Real)
    atom_types = list(mm_atoms.get("atomTypes", []))
    atom_type_indices = [int(row[type_i]) for row in rows]
    lj_type_indices = [int(row[lj_i]) for row in rows]
    active_atoms = [i for i, row in enumerate(rows) if bool(row[active_i])]
    if len(active_atoms) == len(rows):
        mm_selection = None
    else:
        mm_selection = Selection.FromIterable(active_atoms)

    term_record = data.get("mmTerms", {})
    term_states = _tag_state(term_record)
    terms = []
    term_payloads = []
    for term in term_states.values():
        term_class = term.get("__class__")
        cls = getattr(importlib.import_module("pMolecule.MMModel"), term_class, None)
        if cls is None or not hasattr(cls, "Raw"):
            raise ValueError("Unsupported pDynamo2 MM term container: {}.".format(term_class))
        obj = cls.Raw()
        obj.__setstate__(term.get("state", {}))
        terms.append(obj)
        term_payloads.append((cls, term.get("state", {})))

    lj = _restore_raw_container(data.get("ljParameters", {}), "pMolecule.MMModel")
    lj14 = _restore_raw_container(data.get("ljParameters14", {}), "pMolecule.MMModel")
    for container in (lj, lj14):
        form = getattr(container, "analyticForm", None)
        if isinstance(form, str):
            container.analyticForm = {"AMBER": LJForm.Amber, "OPLS": LJForm.OPLS,
                                      "TABLE": LJForm.Table}.get(form.upper(), form)
            container.MakeTable()
    exclusions = _restore_pair_list(data.get("exclusions", {}))
    interactions14 = _restore_pair_list(data.get("interactions14", {}))

    mm_state_payload = {
        "charges": charges,
        "atomTypes": atom_types,
        "atomTypeIndices": Array.FromIterable(atom_type_indices, dataType=DataType.Integer),
        "ljTypeIndices": Array.FromIterable(lj_type_indices, dataType=DataType.Integer),
        "mmAtoms": mm_selection,
        "pureMMAtoms": mm_selection,
        "mmTerms": terms,
        "ljParameters": lj,
        "ljParameters14": lj14,
        "exclusions": exclusions,
        "interactions14": interactions14,
    }

    mm_options = _tag_state(mm_model)
    for key in ("label", "fullPath", "path", "parameterSet", "parameterSetPath"):
        mm_options.pop(key, None)
    supported_mm_options = set(MMModel._attributable.keys())
    unsupported_mm_options = set(mm_options) - supported_mm_options
    if unsupported_mm_options:
        raise ValueError("Unsupported settings in {}: {}.".format(source_mm_class,
                                                                    ", ".join(sorted(unsupported_mm_options))))
    mm_options = {key: value for key, value in mm_options.items()
                  if value is None or isinstance(value, (str, int, float, bool))}
    if isinstance(mm_options.get("lennardJonesStyle"), str):
        styles = {"AMBER": LJForm.Amber, "OPLS": LJForm.OPLS, "TABLE": LJForm.Table}
        style = styles.get(mm_options["lennardJonesStyle"].upper())
        if style is None:
            raise ValueError("Unsupported Lennard-Jones style: {}.".format(mm_options["lennardJonesStyle"]))
        mm_options["lennardJonesStyle"] = style
    mm_options["exchangeStatePayload"] = mm_state_payload
    system.DefineMMModel(ExchangeMMModel.WithOptions(**mm_options))
    # pDynamo2 permits fractional active-MM charge in some QM/MM embeddings.
    # Keep pDynamo3's normal check unless the saved charge is fractional.
    active_charge = sum(float(charges[i]) for i in active_atoms)
    if abs(active_charge - round(active_charge)) > 1.0e-6:
        system.mmState.CheckActiveAtomTotalCharge = _skip_active_atom_total_charge_check

    qc_selection = [int(i) for i in model_manifest.get("qc_selection", [])]
    if not qc_selection:
        raise ValueError("Configured QC model has no saved atom selection.")
    boundary_records = model_manifest.get("qc_boundary_records", [])
    if boundary_records:
        # pDynamo2 stores boundary QC atoms as link hydrogens within its QC
        # atom list. pDynamo3 represents the same centers as QC atoms plus
        # automatically generated boundary hydrogens. Exclude the old
        # boundary centers from the pure selection and recreate exactly the
        # source boundary map so it cannot infer extra link atoms from a
        # different MM connectivity interpretation.
        boundary_indices = {int(item["boundary_atom"]) for item in boundary_records}
        pure_selection = sorted(set(qc_selection) - boundary_indices)
        if not pure_selection:
            raise ValueError("The saved QC boundary records remove every pure QC atom.")
        boundary_map = {}
        for item in boundary_records:
            b = int(item["boundary_atom"])
            q = int(item["qc_partner"])
            partners = {int(i) for i in item.get("mm_partners", [])}
            if b in pure_selection or q not in pure_selection or b == q:
                raise ValueError("Inconsistent saved pDynamo2 QC boundary: {}.".format(item))
            boundary_map[b] = [set(), partners, {q}]
        system.mmState.IdentifyBoundaryAtoms = ExchangeBoundaryIdentifier(boundary_map)
        qc_selection = pure_selection

    qc_options = _tag_state(qc_model)
    converger_record = qc_options.pop("converger", None)
    converger_options = _tag_state(converger_record) if converger_record else {}
    # pDynamo2 named these controls differently. Keep the converger's
    # tolerances and translate the iteration/history controls where possible.
    converger_options = {key: value for key, value in converger_options.items()
                         if key in DIISSCFConverger._attributable}
    if converger_record:
        old_converger = _tag_state(converger_record)
        if "maximumSCFCycles" in old_converger:
            converger_options["maximumIterations"] = int(old_converger["maximumSCFCycles"])
        if "history" in old_converger:
            converger_options["maximumHistory"] = int(old_converger["history"])
        if "useRCA" in old_converger:
            converger_options["useODA"] = bool(old_converger["useRCA"])
    converger = DIISSCFConverger.WithOptions(**converger_options)
    hamiltonian = qc_options.pop("mndoModel", "am1")
    charge_model = str(qc_options.pop("qcChargeModel", "MNDO")).strip().lower()
    charge_evaluators = {"mulliken": MullikenMultipoleEvaluator}
    if charge_model in charge_evaluators:
        qc_options["multipoleEvaluator"] = charge_evaluators[charge_model]
    elif charge_model in ("lowdin", "löwdin"):
        qc_options["multipoleEvaluator"] = ExchangeMNDOLoewdinEvaluator()
    elif charge_model not in ("mndo",):
        raise ValueError("Unsupported pDynamo2 QC charge model: {}.".format(charge_model))
    qc_options.pop("label", None)
    qc_options["converger"] = converger
    supported_qc_options = set(QCModelMNDO._attributable.keys())
    untranslated_qc_options = sorted(key for key, value in qc_options.items()
                                     if key not in supported_qc_options and value is not None)
    known_source_controls = {"fermiBroadening", "hasCI", "isSpinRestricted", "keepOrbitalData",
                             "linkAtomRatio", "numberFractionalAlphaHOOs",
                             "numberFractionalAlphaLUOs", "numberFractionalBetaHOOs",
                             "numberFractionalBetaLUOs", "numberFractionalHOOs",
                             "numberFractionalLUOs", "occupancyType", "orbitalBasis"}
    unknown_qc_options = sorted(set(untranslated_qc_options) - known_source_controls)
    if unknown_qc_options:
        raise ValueError("Unsupported settings in {}: {}.".format(source_qc_class,
                                                                    ", ".join(unknown_qc_options)))
    qc_options = {key: value for key, value in qc_options.items()
                  if key in supported_qc_options and
                  (isinstance(value, (str, int, float, bool)) or key == "multipoleEvaluator")}
    qc_options["hamiltonian"] = str(hamiltonian).lower()
    system.DefineQCModel(QCModelMNDO.WithOptions(**qc_options),
                         qcSelection=Selection.FromIterable(qc_selection))
    if boundary_records:
        saved_link_factors = {int(item["boundary_atom"]): float(item["link_factor"])
                              for item in boundary_records}
        system.qcState.baQCPartners = [
            (b, q, saved_link_factors[b]) for (b, q, _ratio) in system.qcState.baQCPartners
        ]
    # The pDynamo2 snapshot already contains its final active term masks.
    # pDynamo3's QC builder deactivates boundary terms again; restore the saved
    # masks after it has built the QC boundary/link-atom state.
    restored_terms = []
    for cls, payload in term_payloads:
        term = cls.Raw()
        term.__setstate__(payload)
        restored_terms.append(term)
    system.mmState.mmTerms = restored_terms
    # Some pDynamo2 topologies contain a selected QM/MM boundary atom whose
    # outside atom has no other MM neighbors. pDynamo3 records an empty partner
    # list for that case, then divides by its length when distributing the
    # boundary charge. Such a boundary contributes no redistributed MM charge.
    system.qcState.baMMPartners = [(b, partners) for (b, partners) in system.qcState.baMMPartners
                                   if len(partners) > 0]
    # The legacy MM atom table can deliberately keep selected boundary atoms
    # active as MM charge sites. QCModel.BuildModel otherwise replaces this
    # saved selection with the pDynamo3 default (all atoms minus pure QC atoms).
    system.mmState.mmAtoms = Selection.FromIterable(active_atoms)
    system.mmState.pureMMAtoms = Selection.FromIterable(
        set(active_atoms) - set(system.qcState.pureQCAtoms) - set(system.qcState.boundaryAtoms))
    nb_options = _tag_state(nb_model)
    # pDynamo3 replaced the pDynamo2 NBModelABFS class with NBModelCutOff and
    # a separately configured ABFS pairwise interaction.
    pairwise_state = _tag_state(nb_options.get("mmmmPairwiseInteraction", {}))
    pairwise = PairwiseInteractionABFS.WithOptions(
        dampingCutOff=float(pairwise_state.get("dampingCutoff", 0.5)),
        innerCutOff=float(pairwise_state.get("innerCutoff", nb_options.get("innerCutoff", 8.0))),
        outerCutOff=float(pairwise_state.get("outerCutoff", nb_options.get("outerCutoff", 12.0))))
    generator = PairListGenerator.WithOptions(cutOff=float(nb_options.get("listCutoff", 16.0)))
    system.DefineNBModel(NBModelCutOff.WithOptions(
        dielectric=float(nb_options.get("dielectric", 1.0)),
        pairwiseInteraction=pairwise, generator=generator,
        checkForInverses=bool(nb_options.get("checkForInverses", True)),
        imageExpandFactor=int(nb_options.get("imageExpandFactor", 0)),
        useCentering=bool(nb_options.get("useCentering", False))))
    # pDynamo2 used Gaussian charge widths for QC/MM and QC/QC electrostatics.
    # pDynamo3 represents those interactions with the spline ABFS pairwise
    # model, while retaining the ordinary ABFS model for MM/MM and LJ terms.
    qcmm_state = _tag_state(nb_options.get("qcmmPairwiseInteraction", {}))
    spline_models = {"DELTA/DELTA": SplineModel.Delta_Delta,
                     "DELTA/GAUSSIAN": SplineModel.Delta_Gaussian,
                     "GAUSSIAN/GAUSSIAN": SplineModel.Gaussian_Gaussian}
    electrostatic_model = spline_models.get(str(qcmm_state.get("electrostaticModel", "Delta/Gaussian")).upper())
    if electrostatic_model is None:
        raise ValueError("Unsupported pDynamo2 QC/MM electrostatic model: {}.".format(
            qcmm_state.get("electrostaticModel")))
    system.qcmmElectrostatic.pairwiseInteraction = PairwiseInteractionSplineABFS.WithOptions(
        dampingCutOff=float(qcmm_state.get("dampingCutoff", 0.0)),
        electrostaticModel=electrostatic_model,
        innerCutOff=float(qcmm_state.get("innerCutoff", 8.0)),
        outerCutOff=float(qcmm_state.get("outerCutoff", 12.0)),
        # pDynamo3's ABFS summary and spline builder treat point density as an
        # integer count. pDynamo2 serializations may store the same setting as
        # either 50 or 50.0.
        pointDensity=int(qcmm_state.get("splinePointDensity", 50)),
        width1=float(qcmm_state.get("width1", 0.0)),
        width2=float(qcmm_state.get("width2", 0.0)))
    system.qcmmElectrostatic.generator = generator
    if str(nb_options.get("qcmmCoupling", "")).strip().upper() == "RC COUPLING":
        # pDynamo2 RC keeps each MM partner's pure-MM charge and adds
        # q(boundary)/nPartners at the boundary-partner midpoint. pDynamo3's
        # default BP representation does this. rdLACharges=True is the
        # distinct R-D scheme (2q at midpoint and -q on the partner).
        system.qcmmElectrostatic.rdLACharges = False
        system.qcmmState.bpCharges = system.qcmmElectrostatic.GetBPCharges(
            system.qcState.baMMPartners, system.mmState.charges)
    system.qcmmLennardJones.pairwiseInteraction = PairwiseInteractionABFS.WithOptions(
        dampingCutOff=float(qcmm_state.get("dampingCutoff", 0.0)),
        innerCutOff=float(qcmm_state.get("innerCutoff", 8.0)),
        outerCutOff=float(qcmm_state.get("outerCutoff", 12.0)))
    system.qcmmLennardJones.generator = generator

    electronic = model_manifest.get("electronic_state") or {}
    system.electronicState = ElectronicState.WithOptions(
        charge=int(electronic.get("charge", 0)),
        multiplicity=int(electronic.get("multiplicity", 1)))

    fixed = [int(i) for i in model_manifest.get("fixed_atoms", [])]
    if fixed:
        free = sorted(set(range(len(system.atoms))) - set(fixed))
        system.freeAtoms = Selection.FromIterable(free)
    # Assigning freeAtoms also deactivates fixed-atom bonded terms in pDynamo3;
    # the pDynamo2 snapshot already saved that final active mask as well.
    restored_terms = []
    for cls, payload in term_payloads:
        term = cls.Raw()
        term.__setstate__(payload)
        restored_terms.append(term)
    system.mmState.mmTerms = restored_terms

    soft = data.get("softConstraints", {})
    if soft:
        restraints = RestraintModel()
        for name, record in soft.items():
            kind = record.get("__class__")
            state = record.get("state", {})
            energy_record = state.get("energyModel", {})
            energy_state = _tag_state(energy_record)
            energy = RestraintEnergyModel.WithOptions(
                highEquilibriumValue=float(energy_state["highEquilibriumValue"]),
                highForceConstant=float(energy_state["highForceConstant"]),
                highPower=int(energy_state["highPower"]),
                lowEquilibriumValue=float(energy_state["lowEquilibriumValue"]),
                lowForceConstant=float(energy_state["lowForceConstant"]),
                lowPower=int(energy_state["lowPower"]),
                period=energy_state.get("period"))
            if kind == "SoftConstraintMultipleDistance":
                restraint = RestraintMultipleDistance.WithOptions(
                    distances=[(int(i), int(j), float(w)) for i, j, w in state["distances"]],
                    energyModel=energy)
            elif kind == "SoftConstraintDistance":
                restraint = RestraintDistance.WithOptions(
                    point1=int(state["point1"]), point2=int(state["point2"]), energyModel=energy)
            elif kind == "SoftConstraintAngleDotProduct":
                restraint = RestraintAngleDotProduct.WithOptions(
                    point1=int(state["point1"]), point2=int(state["point2"]),
                    point3=int(state["point3"]), energyModel=energy)
            else:
                raise ValueError("Unsupported pDynamo2 soft constraint: {}.".format(kind))
            restraints[str(name)] = restraint
        system.DefineRestraintModel(restraints)

    system.e_exchange_requires_energy_model = False
    system.e_exchange_model_report = {
        "pDynamo2": "{} + {} + {}".format(mm_model.get("__class__"),
                                             qc_model.get("__class__"),
                                             nb_model.get("__class__")),
        "pDynamo3": "imported MM state + translated QC/NB models",
        "energy_parity": "Translation support is model-family-specific; compare source and imported energies for each new family.",
        "constraints": len(soft),
        "fixed_atoms": len(fixed),
        "qc_atoms": len(model_manifest.get("qc_selection", [])),
    }
