"""Full pDynamo nonbonded model with GPU4PySCF point charge embedding."""

from pMolecule.NBModel.NBModelFull import NBModelFull
from pMolecule.NBModel.QCMMLennardJonesModelFull import QCMMLennardJonesModelFull

from util.QCMMElectrostaticModelGPU4PySCF import QCMMElectrostaticModelGPU4PySCF


class NBModelGPU4PySCF(NBModelFull):
    _classLabel = "GPU4PySCF NB Model"

    def QCMMModels(self, qcModel=None, withSymmetry=False):
        return {
            "qcmmElectrostatic": QCMMElectrostaticModelGPU4PySCF,
            "qcmmLennardJones": QCMMLennardJonesModelFull,
        }
