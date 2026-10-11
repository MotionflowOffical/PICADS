# Chip Compiler v0.3.0 — Implementation report

Release type: **source implementation, not a production-qualified tapeout application**.

## Implemented during this iteration

1. **Hierarchical executable DLS**, serialized as format v2. When CO enables `modules.hierarchy: preserve`, pure helper calls instantiate independently generated and validated submodule DLS instances. Parent DLS execution invokes each instance at the correct event position; Verilog export emits real named child modules and instances. Existing v1 files remain readable. Nested calls *inside* child implementations are flattened. Stateful children are rejected with a specific unsupported-contract error.
2. **Register-based multi-stage pipelining** through `schedule.pipeline_stages: 1..32`, with actual register cut points, a `clk` port, `input_valid` input, and `valid` output. The checker tests cycle-correct source correspondence after N rising edges. This is a spatial pipeline with initiation interval one, **not** time-sharing.
3. **Restricted sequential time-multiplexed scheduling**, `schedule.mode: time_share`. A straight-line unsigned arithmetic source can be scheduled over clock cycles onto one or more reused gate-level operators. Generated DLS contains sampled inputs, operator output registers, one-hot execution controller, idle/start/commit/done registers, and a `START/READY/DONE` handshake. Source ↔ DLS checking runs transaction samples and modifies inputs during execution. Does not support conditional branches, signed arithmetic, memories, stalling, nested helper calls or overlapping transactions.
4. **MCD explicit port checking**: optional inputs/outputs declarations must exactly match the bound source function. Conflicts yield `MCD.PORT_MISMATCH` with declared and actual interfaces.
5. **CO validation**: invalid schedule modes, conflicting pipeline/hierarchy combinations, unrecognized scheduling settings, or unsupported features fail explicitly rather than silently falling back.
6. **GUI graph code extended** to render actual helper instances and annotate scheduled designs. GUI runtime remains unverified because PySide6 is unavailable.
7. **CLI protocol-aware simulation**: `simulate` performs the required clock edges for a single time-shared transaction or one pipelined sample, avoiding misleading idle-cycle output.
8. **Artifact-aware Yosys checks**: zero process exit without a nonempty expected synthesized netlist, or with a wrong top module, is an error and blocks dependent stages.
9. **Live external-tool logging**: Yosys/LibreLane console streams are saved during tool execution; noteworthy native errors/warnings also appear as structured diagnostic events. Timeouts preserve partial logs.
10. **New examples and regression tests** for module instance execution, source corruption, multi-cycle latency, time-shared hardware, explicit resource limits, MCD mismatches, missing synthesis artifacts, live logs and timeout behavior.

## Verified here

- 207 automated tests pass; 1 PySide6 GUI smoke test skipped (dependency absent).
- Three new example project configurations compile, generate DLS and structural Verilog, and pass their applicable source-to-DLS checks.
- Failed-module mutation produces a real behavioral mismatch rather than an unchanged high-level answer.
- The execution environment has GCC/Clang but lacks PySide6, Yosys, LibreLane, OpenROAD, KLayout and an installed PDK.
- Attempted installation of PySide6 was blocked by external DNS/network resolution, so no GUI launch claim is possible.

## Still not finished

- General HLS for arbitrary Python/C/C++ including control-dependent loops, pointers, complex memory, exceptions, templates or language-level side effects.
- General time-shared FSM scheduling with branch-dependent execution, memories, pipelines, stalls, arbitration, multiple clocks or arbitrary CO routing.
- Multi-level preserved hierarchy including stateful child module interfaces, inout protocols and clock-domain crossings.
- Global placement of operators across MCD modules and optimal architecture search over alternative physical implementations.
- True live rendered GDS layout inside the GUI (metadata inspector and external KLayout handoff only).
- Runtime GUI verification on Windows/WSL2.
- Actual Yosys synthesis, actual LibreLane placement/routing, actual generated GDSII and extracted netlist verification with a real process.
- Qualified DRC/LVS/timing/power/antenna signoff and lithography-specific custom TFT PDK/mask preparation.

These missing features require further implementation and, for physical manufacturing, external process libraries and a suitable tool installation. Passing internal tests is not a substitute for them.
