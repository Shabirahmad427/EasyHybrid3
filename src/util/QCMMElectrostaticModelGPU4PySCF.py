"""Point charge embedding adapter for GPU4PySCF and pDynamo3."""

import numpy as np

from pScientific import Units
from pMolecule.NBModel.QCMMElectrostaticModel import QCMMElectrostaticModel


class QCMMElectrostaticModelGPU4PySCF(QCMMElectrostaticModel):
    """Pass pDynamo MM and link charges to GPU4PySCF's QMMM wrapper."""

    _classLabel = "GPU4PySCF QC/MM Electrostatic Model"

    def QCMMPotentials(self, target):
        state = getattr(target, self.__class__._stateName)
        mm_atoms = list(target.mmState.pureMMAtoms)
        mm_charges = target.mmState.charges
        coordinates = target.scratch.Get("coordinates3NB", target.coordinates3)
        charge_values = [float(mm_charges[i]) / self.dielectric for i in mm_atoms]
        point_coordinates = [
            [float(coordinates[i, j]) * Units.Length_Angstroms_To_Bohrs for j in range(3)]
            for i in mm_atoms
        ]

        bp_charges = state.bpCharges
        bp_coordinates = target.scratch.Get("bpCoordinates3", None)
        if bp_charges is not None:
            charge_values.extend(float(q) / self.dielectric for q in bp_charges)
            point_coordinates.extend(
                [[float(bp_coordinates[i, j]) * Units.Length_Angstroms_To_Bohrs for j in range(3)]
                 for i in range(len(bp_charges))]
            )

        target.scratch.gpu4pyscfMMCharges = np.asarray(charge_values, dtype=float)
        target.scratch.gpu4pyscfMMCoordinatesBohr = np.asarray(point_coordinates, dtype=float).reshape((-1, 3))
        target.scratch.gpu4pyscfMMAtoms = mm_atoms

    def QCMMGradients(self, target):
        if not target.scratch.doGradients:
            return
        gradients = getattr(target.scratch, "gpu4pyscfMMGradientsAU", None)
        if gradients is None:
            return
        factor = Units.Length_Angstroms_To_Bohrs * Units.Energy_Hartrees_To_Kilojoules_Per_Mole
        mm_atoms = target.scratch.gpu4pyscfMMAtoms
        n_mm = len(mm_atoms)
        for i, atom in enumerate(mm_atoms):
            for j in range(3):
                target.scratch.gradients3[atom, j] += factor * gradients[i, j]
        bp_gradients = target.scratch.Get("bpGradients3", None)
        for i in range(len(gradients) - n_mm):
            for j in range(3):
                bp_gradients[i, j] += factor * gradients[n_mm + i, j]
