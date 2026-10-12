# PICADS v1.0 — fixed scope and acceptance procedure

## Goal

The first feature-complete PICADS release must demonstrate a **repeatable, correctly diagnosed** source-to-physical-design flow for a **declared supported subset**, not a universal HLS system. Users must be able to generate circuit RTL, check its behavior, synthesize it with real tools, create actual standard-cell layout data from an accepted PDK, and inspect the final GDSII and physical-flow metrics.

### Pass criteria for the first supported reference design

| Stage | Evidence required | Not sufficient |
|---|---|---|
| Typed source/MCD/CO -> DLS | Successful logical compile, DLS and source-verification report | A saved code file |
| DLS -> RTL | Structural Verilog, cross-cycle checks with real RTL simulator | Just writing a `.v` file |
| Synthesis | Yosys exit 0, nonempty synthesized Verilog with expected top, native tool log | Fake tool result or stale file |
| Placement/routing | Nonzero LibreLane exit considered failure; success requires fresh run tag, nonempty parsable GDS and matching top cell | A standalone SVG/GDS preview |
| Physical check evidence | Actual DRC, LVS, setup/hold and relevant timing metrics reported per process/corner, recorded as PASS/FAIL/UNVERIFIED | Missing metrics interpreted as zero violations |
| Mask manufacturing qualification | Foundry-approved extraction/rules and signoff/acceptance reports | Any PICADS compile, layout, or self-check result |
| GUI and Settings | Launch in supported Windows configuration, select/register tools, open project, run compile, inspect physical artifacts | Compiled Qt source without runtime execution |
| Windows diagnostics | One-command, machine-executed acceptance package with stdout/stderr, versions, hashes and counterexamples | A local unit-test PASS representing external tools |

## v0.14 work toward these criteria

- `picads physical-preflight PROJECT` compiles a project and reports physical configuration, target, tool and PDK readiness without executing layout.
- Strict settings normalization for clock period, target PDK, standard-cell library, core utilization, placement density and die area. Invalid values fail before physical execution.
- LibreLane config uses the generated Verilog name, clock and validated floorplanning options.
- Physical handoff manifest hashes both input RTL and flow config. A post-flow hash check detects unexpected modification during execution.
- Final GDS artifacts are parsed, hashed, checked for expected top cell and connected to actual final metrics. Missing final views remain visibly missing.
- A bundled, small, synchronous `examples/first_physical_chip` is the initial end-to-end reference design.
- `RUN_V1_ACCEPTANCE.bat` / `python -m chipcompiler.acceptance` exercises the reference project with the installed external tools and produces one diagnostic ZIP.
- Qt physical tab includes a **Check Physical Prerequisites** action; runtime still needs Windows confirmation.

## Running the reference workflow on Windows

1. Extract the complete PICADS archive. Use `RUN_GUI.bat`; open Settings → External Dependencies and register **Icarus (`iverilog` and `vvp`), Yosys, LibreLane** and optionally KLayout.
2. Configure an actually supported standard-cell PDK in LibreLane. Set `PDK_ROOT` to its containing directory, or choose PDK Folder in Settings (selecting the actual PDK folder lets the acceptance runner infer the parent directory).
3. Launch `RUN_V1_ACCEPTANCE.bat`. By default it tests the bundled first-chip design with PDK name `sky130A`. For other targets, run `RUN_V1_ACCEPTANCE.bat --pdk <name> --pdk-root <folder> --std-cell-library <library>`.
4. The script creates `validation/PICADS_v0.14.0_v1_acceptance.zip`. Upload this file to the conversation. It includes project compile evidence and real native-tool logs where tools were available; it does **not** upload private source projects or PDK binaries.
5. On unsupported/missing toolchains, the result remains **PARTIAL/UNAVAILABLE**, never a fictional completed layout. A physical-layout PASS is not equivalent to manufacturing qualification.

## Known blockers remaining after v0.14

- No Icarus, Yosys, LibreLane, PDK or actual Qt runtime is present in the development environment; the native reference path has not run here.
- The first-chip project is a small typed, clocked source function, not arbitrary concurrency or general C++ hardware synthesis.
- Technology mapping and foundry device-level qualification for custom TFT materials remain missing.
- Real DRC/LVS/STA, physical routing and mask acceptance still require a user-installed and supported target process. The acceptance script intentionally cannot certify masks on its own.

Deferred work belongs in [FUTURE_FEATURES.md](FUTURE_FEATURES.md). That document should not be used to redefine the acceptance criteria above.
