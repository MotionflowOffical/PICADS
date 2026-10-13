# PICADS r7: separate layout generation and verification

## Why two buttons?

`Generate Physical Layout (GDS)` is a *layout-production action*. It saves the
current source snapshot, compiles DLS, generates Verilog, runs Yosys (and an
optional ABC/AIG sidecar), and runs LibreLane **through** `KLayout.StreamOut`.
It produces a real GDSII from the selected PDK when successful. It does **not**
run LibreLane's later XOR/DRC/LVS/remaining manufacturing-report stages. Some
preliminary synthesis, placement, timing and power-grid checks necessarily run
before stream-out; the button does not skip those.

`Verify Existing Layout (DRC / LVS)` is a *deferred verification action*.
It does not recompile or reroute. It first verifies the saved source snapshot
against the saved DLS, checks SHA-256 hashes of the RTL, configuration and GDS,
and then resumes the **same LibreLane run tag** using `--from KLayout.Render`.
That is the first stage after `KLayout.StreamOut` in the documented Classic
flow at the time of writing. This includes rendering, LEF/antenna metadata,
XOR, DRC, LVS, and the flow's remaining checkers, subject to PDK and flow
configuration. Reusing the existing run is supported by LibreLane's `--from`
and run state mechanism; PICADS r7 does not mark this Windows operation verified
until actually run on the target machine.

The first run writes `build/latest/report.json`, `layout_artifacts.json`,
`physical_handoff.json`, `layout_source_snapshot.py` and optionally
`abc_optimized.aig`; the second writes **separate**
`layout_verification_report.json`, `layout_verification_equivalence.json`,
`layout_verification_evidence.json`, and `layout_verification.log`.
The first report remains untouched on verification. No duplicate GDS is made.

### GUI

Physical / Masks -> **1. Generate Physical Layout (GDS)** or
**2. Verify Existing Layout (DRC / LVS)**. The same controls are in Build / Export,
the main toolbar and the Build menu. The existing one-shot Full Physical Flow is
still available in the Build menu for backward compatibility.

### CLI

```powershell
python -m chipcompiler layout C:\path\to\project
python -m chipcompiler verify_layout C:\path\to\project
```

The second action requires the first action's saved `build/latest` run. Any
subsequent new compilation archives the previous run to `build/history`, so the
buttons must target the same current run.

### How module separation works *today*

The r6 and r7 floorplan diagrams are **GUIDE_ONLY**, *not* cell placement
fences. In particular, transactional CPU examples (Apollo and Tiny8) are
flattened before Yosys mapping. A source-level label such as `ALU` cannot be
attached to placed standard cells after that flattening. The physical border
coordinates, spacing and child regions in CO are validated and visualized,
but **not applied to LibreLane**. When `enforcement: required` is requested,
PICADS deliberately refuses that unsupported request rather than outputting
an apparently compliant GDS. The correct future implementation requires:

1. Emit genuinely separate, synthesis-preserved hierarchical hardware units,
   including shared scheduled datapath logic where appropriate.
2. Maintain a source/DLS -> mapped netlist/ODB cell identity map.
3. Apply the CO regions through OpenROAD placement groups, fences, or hardened
   macros before detailed placement.
4. Verify cell containment, routing, actual module-to-module spacing and PDN
   continuity from the placed OpenDB/DEF results, then record enforcement.

Do not interpret the colored region SVG as a depiction of the GDS. KLayout
cannot display physical module borders that were never put into the layout.

## Named KLayout layers

GDSII stores numeric layer/datatype pairs, not human-readable process-layer
names. PICADS r7's `Open Latest GDS in KLayout` and `Open Other GDS/OASIS`
try to load `sky130A.lyp` from the selected local PDK or the installed WSL
`.ciel` / `.volare` PDK, caching only the viewer palette at
`build/latest/klayout_layers.lyp`. The launched command uses `klayout -l
<palette> <layout.gds>`. If no matching valid palette is found, KLayout opens
without names and a message explains why. Nothing in the GDS is modified.

If the automatic palette discovery fails, load the KLayout layer properties
manually using **File -> Load Layer Properties**. An appropriate `.lyp` is
included with the SKY130 PDK's `libs.tech/klayout` files.

## Scope and validation

PICADS r7 does not implement actual module-aware placement; it does not claim
foundry signoff or verified Windows execution. New behavior is covered by
mocked GDS/LibreLane tests. These tests cannot demonstrate a functioning
resume path on the user's specific LibreLane installation; check its
`layout_verification.log` if it fails.
