# Chip Compiler v0.8.0 — Procedural Digital Hardware Suite

> A cumulative development release, not a qualified manufacturing flow.

New in v0.8: **concurrent multi-client service scheduling** with independent shared ALU and on-chip memory arbitration, variable external operator response latency, and automatic one-command Windows verification. See [Concurrent Fabric](docs/CONCURRENT_FABRIC_v0.8.0.md) and [Full System Validation](docs/FULL_VALIDATION_v0.8.0.md). Previous v0.7 features include **transactional CO scheduling** (branch-dependent execution, on-chip memory operations, stalls, per-resource ready backpressure, clocked reset), a reusable **round-robin DLS arbiter**, source-to-DLS execution traces, and explicit scheduled RTL testbench generation. The compiler constructs real primitive gate networks and one-hot FSM registers, not behavioral stubs. See [Transactional Scheduler Guide](docs/TRANSACTIONAL_SCHEDULER_v0.7.0.md), [Implementation Status](docs/IMPLEMENTATION_STATUS.md) and [Remaining Work](docs/NEXT_IMPLEMENTATION.md).

All previous cumulative functionality and example projects are preserved. General concurrent high-level synthesis of arbitrary source programs, native EDA runtime validation here, qualified physical masks and manufacturing signoff remain *unfinished*.


A procedural digital-logic compiler with executable gate-level DLS, editable MCD/CO descriptions, behavioral verification, structural Verilog export, a dark PySide6 desktop application, and adapters for existing physical-design software.

**Not complete or fabrication-qualified.** The implemented source language and scheduling are deliberately restricted. The physical EDA flow and desktop GUI could not be runtime-executed in the release environment; reported successes only cover the actually executed tests. Consult [Implementation Status](docs/IMPLEMENTATION_STATUS.md) before relying on an output.

## What's in this release

- Procedural synthesis of arithmetic and Boolean functions into primitive-gate DLS.
- Restricted typed-Python and C/C++-compatible source frontends.
- MCD modules, interfaces, mandatory capabilities, **real typed inter-module networks** and **nested combinational/stateful module hierarchy** with one implicit shared rising-edge clock, and optional hardware naming.
- CO resource sharing, limited true multi-cycle time-sharing with controller and registers, clocked spatial pipelines and static resource limits. Explicit networks require a spatial schedule until cross-module retiming exists.
- Conditional pure datapaths, comparisons and bounded unrolled loops in time-share mode.
- Optional external Icarus RTL-vs-DLS simulation (requires real `iverilog` + `vvp`), clock-enable/synchronous-reset state, and independent source-to-DLS behavioral checks, including per-instance register state; VCD traces with hierarchical registers, structured diagnostics and failure causality. Unsafe conditional/short-circuit state effects are rejected explicitly.
- Dark desktop editor, graph and hierarchical explorers, simulator, build and backup/recovery workspaces.
- Yosys and LibreLane process adapters (need tools and a PDK installed separately), and structural GDSII inspection.
- A **read-only SVG preview of actual GDSII layout geometry**, with explicit clipping/unresolved-reference reporting; **not** mask signoff.

## Install and run (Windows 10/11)

1. Install Python 3.10+; Python 3.12 is recommended.
2. Extract the source ZIP contents directly into a directory; the ZIP contains no wrapper folder.
3. Execute `RUN_FULL_VALIDATION.bat` to automatically install the required Python test/GUI packages (explicitly announced), run available native checks, and create one ZIP for diagnosis. Or execute `SETUP_GUI_WINDOWS.bat` to explicitly install optional Python GUI/testing dependencies.
4. Run `RUN_TESTS.bat`, followed by `RUN_GUI.bat`.
5. The automatic runner does **not** install Yosys, Icarus, LibreLane or a PDK. For external synthesis, install Yosys; for physical design, install LibreLane/OpenROAD and a supported process design kit. These are **not installed automatically**.

Command-line usage (after installing with `python -m pip install -e '.[gui,test]'`):

```bash
python -m chipcompiler doctor
python -m chipcompiler compile examples/conditional_alu
python -m chipcompiler compile examples/hierarchical_modules
python -m chipcompiler compile examples/time_shared_alu
python -m chipcompiler compile examples/conditional_scheduler
python -m chipcompiler compile examples/bounded_loop_scheduler
python -m chipcompiler compile examples/clocked_hierarchy
python -m chipcompiler compile examples/explicit_network
python -m chipcompiler compile examples/nested_named_modules
python -m chipcompiler compile examples/pipelined_arithmetic
python -m chipcompiler compile examples/c_arithmetic
python -m chipcompiler compile examples/transactional_c
python -m chipcompiler compile examples/concurrent_fabricontroller
python -m chipcompiler compile examples/transactional_memory
python -m chipcompiler compile examples/transactional_c
python -m chipcompiler compile examples/concurrent_fabric
python -m chipcompiler simulate examples/time_shared_alu --inputs '{"a":3,"b":4,"c":5}'
python -m chipcompiler build examples/conditional_alu     # requires actual Yosys
python -m chipcompiler physical examples/conditional_alu  # needs PDK and LibreLane
python -m chipcompiler inspect-mask /path/to/real.gds
python -m chipcompiler render-mask /path/to/real.gds --output preview.svg --max-shapes 20000
python -m chipcompiler diagnose examples/conditional_alu
```

On Windows CMD, use double-quoted JSON strings with escaped interior quotes instead of the Unix single-quote example.

The `render-mask` command returns 2 if the preview is incomplete, rather than claiming success. Real mask inspection requires a real GDSII file; DLS alone is not a physical layout.

## Implementation documentation

- [Current capability status](docs/IMPLEMENTATION_STATUS.md)
- [v0.8 concurrent resource scheduler](docs/CONCURRENT_FABRIC_v0.8.0.md)
- [One-click Windows diagnostics](docs/FULL_VALIDATION_v0.8.0.md)
- [v0.8 verification evidence](docs/VERIFICATION_REPORT_v0.8.0.md)
- [v0.7.0 release notes](docs/RELEASE_NOTES_v0.7.0.md)
- [MCD hierarchical network guide](docs/MCD_NETWORK_v0.6.0.md)
- [Optional independent RTL check](docs/RTL_CHECK_v0.7.0.md)
- [CO/MCD scheduling and naming](docs/CO_SCHEDULING_v0.4.0.md)
- [Diagnostic and error provenance](docs/DIAGNOSTICS.md)
- [Verification report](docs/VERIFICATION_REPORT_v0.7.0.md)
- [Next implementation work](docs/NEXT_IMPLEMENTATION.md)
- [Clocked hierarchy and trace semantics](docs/CLOCKED_HIERARCHY_v0.5.0.md)
- [Architecture overview](docs/ARCHITECTURE.md)

## Reliability policy

Builds archive earlier `build/latest` results, preserve per-run evidence, and distinguish source/config errors from dependent `BLOCKED` stages. Missing tools, incompatible instructions, unverified PDK requirements and partial GDS views are **never substituted with unreported synthetic success**. Project snapshots are atomic and restoration creates a pre-restore backup.
