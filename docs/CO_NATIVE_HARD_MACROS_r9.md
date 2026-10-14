# Native CO Hard-Macro Floorplanning — PICADS 0.16.8 r9

## Scope and architecture

The normal PICADS **Generate Physical Layout** action now recognizes `physical_macros` in `architecture.co`. It hardens the declared Verilog child modules with LibreLane into GDS/LEF/netlist views, computes positions from measured LEF sizes, and places the real macro instances into a top-level LibreLane floorplan. It checks final routed DEF coordinates and requires the final GDS to contain each macro's structure **and an SREF to it**. No external .bat, project-specific Python builder, or manual invocation is needed.

**Boundary:** this is a CO-selected *modular RTL* physical implementation, not automatic decomposition of the *transactional Python/DLS* processor. In particular, Tiny8's `circuit.py` is still compiled for its own DLS/Verilog functional reference. The `rtl/*.v` files selected by CO are separate source code. PICADS does **not** currently prove sequential equivalence between them. Both models can exist in one project but must not be represented as identical without additional verification. A `physical_source_equivalence: UNVERIFIED` stage and manifest marker make the distinction visible.

## Configuration

```yaml
# architecture.co
synthesis:
  abc_aig: true  # independent ABC/AIGER inspection artifacts, not routed cells

physical_macros:
  enabled: true
  enforcement: required
  top_module: tiny8_modular_top
  top_rtl: rtl/tiny8_modular_top.v
  halo_um: 5
  placement:
    mode: compact  # compact (default), row, or manual
  spacing:
    min_um: 20
    preferred_um: 30
    max_um: 75
  blocks:
    - name: ScratchpadMemory
      module: tiny8_memory
      instance: u_memory
      rtl: rtl/tiny8_memory.v
      die_size_um: [180, 180]
      clock_port: clk
    - name: Control
      module: tiny8_control
      instance: u_control
      rtl: rtl/tiny8_control.v
      die_size_um: [200, 180]
      clock_port: clk
    - name: ArithmeticLogic
      module: tiny8_alu
      instance: u_alu
      rtl: rtl/tiny8_alu.v
      die_size_um: [115, 115]
```

`chip.yaml` must also define `physical.enabled: true`, a supported PDK (for this example `sky130A`), a `clock_period_ns`, and a usable LibreLane tool execution backend (`tools.execution: wsl`, `tools.wsl_distribution: Ubuntu` on Windows).

The `top_rtl` file must instantiate each required `module instance(...)` with unique names. All paths must remain within the opened project folder. Only 2–32 top-level blocks with unique module types are supported in this initial native backend. Required blocks are now packed using actual hardened LEF dimensions, with `placement.mode: compact` (automatic deterministic two-dimensional shelf packing by bounding area/perimeter), `row` (previous arrangement), or `manual` (each block must declare `location_um: [x,y]`). The CO minimum clearance and nearest-neighbor maximum gap are validated on the planned rectangles and on placed DEF coordinates. The physical optimizer is heuristic, not globally optimal or net-aware; nesting, generic synthesized standard-cell fences, and non-rectangular regions remain unsupported.

## What the normal buttons do

**Compile / Simulation:** compiles and tests `circuit.py` through the original DLS pipeline. This does not harden macros.

**Generate Physical Layout:** reads the same project's CO, runs LibreLane for each required child macro **through `Magic.WriteLEF`** (which produces GDS, LEF, and synthesized netlist without the subsequent XOR/DRC/LVS signoff stages), builds the parent, and stops the top-level run at `KLayout.StreamOut`. Uses the specified real macro LEF/GDS views and the PDK power network. The first run may be slower than the old flat build because it requires 3 child flows plus the parent; subsequent runs reuse unchanged, successful child macro views from `build/co_macro_cache/`.

**Verify Existing Layout:** first checks the saved source/configuration/LEF/GDS/netlist hashes for each child macro, resumes each saved macro's post-`Magic.WriteLEF` steps starting at `Odb.CheckDesignAntennaProperties` (including KLayout XOR, DRC, and LVS), then resumes the parent's post-layout checks. A failing child check blocks the parent verification and is **not** silently marked PASS. No new RTL synthesis or placement is requested. This fixes an r9 bug where Generate GDS accidentally ran child signoff and therefore stopped on `1 XOR differences found` before assembling the top-level GDS. The Python DLS reference is checked separately and is not confused with the independent modular RTL.

## Evidence / expected outputs

- `build/latest/co_macros/co_macro_plan.json`: requested geometry; **not** success evidence.
- `build/latest/co_macros/co_macro_placement_verified.json`: only created after final GDS hierarchy and routed DEF instance/location checks pass.
- `build/latest/layout_artifacts.json`: final GDS path, hash, `top: tiny8_modular_top`, `source_equivalence: NOT_ESTABLISHED`, and immutable `macro_children` receipts required for deferred child verification.
- `build/latest/co_macros/abc_aig_results.json`: optional independent AIG generation results; not a proof of optimized routed area.
- `build/co_macro_cache/`: reusable large generated hardened module views. This is generated data, not source, and can be deleted with the risk of requiring complete re-hardening.

The generated GDS is **not** a certified mask and passing structural placement checks does not establish DRC, LVS, timing signoff, PDN connectivity or transistor/manufacturing qualification.

## Known limitations and test status

- The backend uses explicitly named RTL modules; PICADS cannot partition arbitrary flattened transactional DLS logic automatically into ALU/Memory/Control regions.
- Each macro contains standard cells. Inter-macro top routing can cross the reserved gaps; visually clear block separation does not require a completely blank channel on every metal layer.
- The cached child views are keyed by their input RTL, generated config and selected PDK root. If the installed PDK or LibreLane tool is upgraded in place, clear `build/co_macro_cache` to force re-hardening.
- The test suite includes a mocked complete CO-to-DEF/GDS run with actual structural checks. It does not demonstrate a physically routed SKY130 device. A first live Linux/WSL run is required to validate the integration and tweak PDK-specific macro hooks if necessary.

**Important:** Deferred `1 XOR differences found` is a Magic-vs-KLayout *GDS geometry comparison* failure, not an ALU logic-equivalence proof or failure. Layout generation can succeed while this issue remains. The underlying discrepancy must still be investigated before a mask is considered verified.

## r9b hierarchical PDN correction

Submacro hardening now explicitly sets `PDN_MULTILAYER: false` and `PDN_ENABLE_PINS: true`; the parent sets `PDN_MULTILAYER: true` and power-strap pitches chosen relative to the smallest macro dimensions. All macro LEF views must expose `VPWR`/`VGND` physical pin geometry. A failed top run writes `co_macros/pdn_diagnostics.json`. Do not claim signoff if the top-level grid is disconnected.

## r9c viewer / dependency updates

Docker Desktop must **already be running** with WSL Integration enabled for the Ubuntu distribution. A `docker` command not found in Ubuntu does not imply PICADS source is invalid. Start Docker Desktop and verify `wsl -d Ubuntu --exec docker info` before rerunning a physical layout.

The KLayout GUI opens GDS with a generated palette containing exactly the actual observed `layer/datatype@1` sources. This prevents empty named PDK entries from misleading the user while the real numeric GDS layers remain visible. Labels and pin/text purposes default to hidden; visibility toggles now reference the real GDS layer purpose. The generated palette is display-only and the source GDS is untouched. Unknown pairs remain clearly marked as unmapped.

A **CO Macro Placement Plan** preview is generated after macro hardening and displayed in the GUI. The preview uses LEF geometry and indicates planned coordinates; it is not a physical signoff claim. The final DEF/GDS module verification still runs. The space outside macro boundaries contains parent-level power/signal routing and may contain support standard cells or textual GDS elements.
