# pDynamo2 to EasyHybrid3 exchange bridge

The bridge has two steps because pDynamo2 PKLs are Python 2 pickles and cannot
be loaded directly in the pDynamo3 process:

1. Run `tools/pdynamo2_exchange_export.py` with the pDynamo2 environment. It
   exports atom identity, connectivity, coordinates, saved model state, QM and
   fixed-atom selections, restraints, and optional PKL/XYZ snapshots to JSON
   plus coordinate sidecars.
2. In EasyHybrid3, choose **pDynamo2 exchange (*.json)** and select that JSON.
   The importer reconstructs supported models and presents the sidecar frames
   as a trajectory.

Pass a snapshot directory to process a large PKL/XYZ batch in natural filename
order. The base PKL is excluded automatically if it is also in that directory.
The exporter chooses the first readable PKL snapshot in the directory as the
model template when the base system has no energy model. That PKL is still
included as a trajectory frame; selecting a model template does not drop it
from the batch. Files with unreadable data or the wrong atom count are skipped
with a per-file message and included in the final skipped-file count. A source
without a configured energy model can still be viewed, but the importer marks
it as structure-only and it cannot run calculations.

When `--model-template` is supplied, its coordinates are used for the imported
system's starting frame. The template and base topology must have the same
atom count and atomic-number order. Snapshot coordinates then become the
trajectory frames without duplicating the starting frame.

```bash
source /home/shabir/software/pdynamo2.sh
python tools/pdynamo2_exchange_export.py system.pkl exchange.json \
  --model-template pontos_pkl/00.00.pkl \
  --snapshot-dir pontos_pkl --snapshot-dir pontos_xyz
```

If the base file has no energy model, the exporter uses the first readable
PKL in the snapshot folders as the model template. To select one explicitly,
add `--model-template configured_system.pkl`. Individual frames can be added
with `--snapshot frame.pkl`; repeat the option as needed.

For PKL snapshots, each file must have the same atom count and atom order as
the base system. XYZ files are checked for atom count and rely on matching atom
order. Sidecars keep large batches out of the JSON document. The importer
stores trajectory coordinates as float32 arrays to avoid Python-list memory
overhead when loading hundreds or thousands of frames.

Coordinate sidecars always use numbered names such as `00.00.coords`. Existing
`NN.NN` frame names are preserved; other or duplicate names receive the next
available frame number. The JSON manifest retains each original input filename.

To build an importable MEP-only manifest from a whitespace-separated table
with `X Y energy window` columns, run:

```bash
python tools/extract_mep_exchange.py \
  /path/to/GH39_exchange.json \
  /path/to/MEP_1D_abs.dat \
  /path/to/GH39_MEP_abs.json
```

The output keeps the MEP table's point order and energy values, selects the
matching `NN.NN` frames, and references the existing sidecars without copying
them. The MEP coordinates and energies are also stored as `mep_path.points` in
the output JSON.

## Model support

Structure, atom order, bonds, coordinates, and trajectories are exchanged
independently of the energy model. An unfamiliar model can therefore be opened
for inspection, while energy calculations require a model translation. The
GH39 energy translation has been validated for pDynamo2 AMBER MM, MNDO-family
QC, and ABFS nonbonded models, including saved parameters, selections,
fixed atoms, electronic state, and supported restraints. The MM parameter
reader also accepts common AMBER, CHARMM, DYFF, and OPLS model-state labels;
only AMBER has been numerically checked so far. Unsupported QC/NB components
and restraint types produce an explicit error instead of silently substituting
settings. Each new family should be compared with its pDynamo2 energy before
being treated as validated.

For MNDO-family systems, the importer translates pDynamo2 `Lowdin` charge coupling with its own
diagonal-density charge and Fock expressions. It also maps pDynamo2 `RC
Coupling` to midpoint boundary-partner charges; pDynamo3's `rdLACharges=True`
is a different redistributed-charge scheme and is left disabled. The exporter
preserves the original QC boundary atoms, their MM and QC partners, and saved
link ratios, so pDynamo3 recreates the boundary saved by the source system.
Re-export older exchange files so they include these boundary records.

On the supplied GH39 `00.00.pkl` frame, the round-trip gave
-60,592.132986206 in pDynamo2 and -60,592.132986181 in pDynamo3, a difference
of 2.6e-8 energy units. The source coordinates were reproduced exactly. A
gradient comparison for this system gave an RMS difference of 9.0e-7; energy
agreement should be checked for each newly translated model family.
