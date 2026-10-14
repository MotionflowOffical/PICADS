# PICADS language workflow — practical project authoring

Read [the full language and file guide](PROGRAMMING_LANGUAGES_AND_DESIGN_FILES.md) first. This page is the actionable workflow for creating a PICADS project and deciding when code belongs in Python/C, MCD, CO or Verilog.

## Path A — compile PICADS-typed Python (or restricted C) directly

**Choose this when:** building small combinational or supported clocked hardware, testing an arithmetic component, exploiting the implemented MCD network, or investigating PICADS's own DLS/gate generator.

1. Create a new project with `picads init path/to/my_chip` or write `chip.yaml`, `design.mcd`, `architecture.co` and `circuit.py` manually.
2. Set `chip.yaml: source` to a typed `.py` function or supported `.c/.cpp` scalar function.
3. Bind a real `design.mcd: top` and, if desired, `modules[].function` to that source function.
4. Select a supported `architecture.co` schedule (`spatial` for basic logic, `transactional` only if your code uses its documented restricted language/protocol).
5. Run `picads compile PROJECT`, inspect `build/latest/report.json`, `architecture.json`, `<top>.dls`, and `<top>.v`.
6. Simulate or trace the DLS (with mode-correct ports), then use Yosys/LibreLane as available. Enable the physical backend **only after** configuring PDK/clock/size constraints.

**This path synthesizes:** compiled DLS from the supported source function. It doesn't synthesize arbitrary procedural Python/C applications or their executable runtime.

## Path B — control explicitly modular Verilog macros with CO

**Choose this when:** the chip needs physically separate CPU/memory/ALU/etc. blocks with hard placement and verified DEF/GDS instance hierarchy, and hand-authored synthesizable RTL is available.

1. Keep a valid `chip.yaml`, MCD and supported source `.py/.c` for PICADS's logical compilation. These may serve as a reference/subset; do not falsely call them the physical implementation.
2. Write **synthesizable** Verilog for each hard module and top-level integration in `rtl/`. Give each block a unique module type and named instance.
3. In `architecture.co`, declare `physical_macros.enabled: true`, `enforcement: required`, `top_module`, `top_rtl`, block `module`, `instance`, `rtl`, and hardening dimensions.
4. Specify `placement.mode: compact`, or explicit `manual` positions. Optionally add `region_um` and `stayouts_um`. Live GUI dragging and compact packing share these constraints.
5. Configure `chip.yaml` physical PDK/tool fields. Start **Docker Desktop**; enable Ubuntu WSL integration and confirm `wsl -d Ubuntu --exec docker info` succeeds.
6. Use **Physical / Masks → Edit CO Floorplan (Drag and Drop)** to plan positions. Click **Save Positions to CO**; the editor writes manual coordinates and creates a backup under `.chipcompiler/floorplan_backups/`.
7. Use **Generate Physical Layout** to harden child macro GDS/LEF, assemble and route top-level GDS. Review `co_macro_placement_verified.json` and the actual layout in KLayout.
8. Use **Verify Existing Layout** to run the deferred physical verification. Investigate any DRC, LVS, XOR, power-grid or timing failures; a routed GDS is not proof of manufacture readiness.
9. Separately simulate/formally compare the independent RTL against your intended CPU/function specification; PICADS r9d has **no automatic Python-model-versus-hard-macro-RTL sequential equivalence proof**.

**This path physically builds:** CO-selected Verilog macros and their Verilog top-level integration. Compiled DLS is a **separate** product unless explicitly integrated and proven.

## Which file do I edit for a common change?

| Intent | Edit | Regenerate / reverify |
|---|---|---|
| Change an arithmetic operator in typed source | `circuit.py` or restricted `source.c` | `compile`, simulate, physical if built from it |
| Rename top function | source and `design.mcd: top` | `compile` |
| Change physical ALU/memory functionality | `rtl/*.v` and potentially interface/top RTL | macro hardening, top routing, RTL verification |
| Swap modules or top-level RTL instances | `rtl/top.v` and `architecture.co: physical_macros` | validation, full physical build |
| Change macro locations or allowed zones | `architecture.co` or GUI editor | new layout; check DEF/GDS |
| Change adder algorithm or scheduler | `architecture.co` | compile/equivalence and downstream build |
| Change PDK, clock or power settings | `chip.yaml` | preflight and full physical build; cache policy |
| Change viewer visibility / color only | generated KLayout `.lyp` through viewer | **No** GDS rebuild |
| Change a CPU program for simulation | firmware / simulator inputs, **not** PICADS hardware source unless describing a physical ROM | software/RTL tests; regenerate physical ROM if actually synthesized from changed contents |

## Verifying before moving to the next stage

- For direct compilation: source top exists; MCD binding reports valid; DLS/Verilog generated; independent simulation verified.
- For explicit RTL macros: top RTL actually instantiates CO-named instances; LEFs contain power pins; required instance locations reported in **final** DEF/GDS, not only a planning SVG.
- For chip manufacturability: require actual process-correct DRC, LVS, timing, antenna, PDN/IR drop, generated views and foundry acceptance. PICADS does not self-certify those results.

## Troubleshooting by error

- `PHYSICAL.MACRO_PREFLIGHT` + `docker could not be found`: Docker Desktop engine not running or WSL integration for selected distribution is disabled. Start Docker Desktop; verify WSL integration.
- `CO.FLOORPLAN_ENFORCEMENT_UNSUPPORTED`: requested generic flattened-module fence is unsupported; use the supported explicit RTL macro mechanism instead of disguising a guide as an enforced fence.
- `CO.MACROS_*`: malformed macro declaration, absent source/instance, impossible placement region, missing power LEF, failed hardening or DEF/GDS validation. Inspect the exact code and stage in `report.json`.
- `PSM-0069` or missing power via: real physical PDN connectivity failure; collect `co_macros/pdn_diagnostics.json`, `physical.log`, top DEF and macro LEFs. **Do not** mark it passed by suppressing IR-drop reporting.
- GDS generated but status unverified: run the distinct physical verification workflow; verify the actual generated macro top is loaded in KLayout.

## Command quick reference

```powershell
# Run inside an installed PICADS Python environment
python -m chipcompiler doctor
python -m chipcompiler compile C:\chips\example
python -m chipcompiler physical-preflight C:\chips\example
python -m chipcompiler layout C:\chips\example
python -m chipcompiler verify_layout C:\chips\example
python -m chipcompiler diagnose C:\chips\example
```

Never use the legacy `physical` command as a substitute for the two-stage GUI workflow if you explicitly intend to postpone verification. Keep backups of project sources and treat `build/` as generated state.
