# PICADS v0.16.5 — Windows v1.0 feature verification

This is a **functional acceptance test**, not the historical iteration-by-iteration test suite.
It runs on temporary project copies and **does not modify your chip projects or installed dependencies**.

## Run the automatic feature test

1. Close other instances of PICADS (to avoid competing native tools), then open the PICADS source folder.
2. Double-click **`RUN_PICADS_AUTOTEST.bat`** (equivalent: `RUN_TESTS.bat`).
3. If Python's GUI/test modules are missing, allow the setup prompt to install them. No native EDA tools or PDK are installed by this script.
4. When finished, upload **only** `validation/PICADS_v0.16.5_automated_diagnostics.zip`.

**One ZIP contains everything needed:** `summary.json`, `evidence/v1_capability_matrix.json`, individual test results in JUnit XML, real CLI logs, Qt automation results/screenshots where available, a generated ALU's Verilog/DLS/VCD, compiler error/recovery evidence, registered tool availability, native Icarus/Yosys results and the v1.0 physical-layout acceptance evidence when supported.

A `PARTIAL` result is expected without LibreLane and a valid PDK. A `FAIL` result should be investigated even when the physical backend is unavailable. The test distinguishes missing tools from failing ones.

## What is automatically checked?

- Opening/importing supported Python and C project examples and generating real DLS + Verilog.
- MCD network composition and hierarchy; CO transactional controllers, local memory, and shared operators/memory.
- 1,024 independently calculated ALU truth-table cases.
- Simulation, waveform export, source errors, invalid signals and recovery without stale RTL.
- Safe dependency registration and clearing in isolated settings; physical-flow preflight must reject missing prerequisites.
- GUI source editing via real keyboard events, save/build, graph visualization, simulator, error recovery, dependency Settings and project switching **when Qt is installed**.
- Actual Icarus RTL tests and Yosys synthesis when registered; physical placement/routing/signoff attempted only when LibreLane and a PDK are configured.
- Archive completeness and SHA-256 manifest verification.

`--full-regression` is **only an optional developer maintenance mode**. It is not part of normal v1.0 feature verification. The dedicated `RUN_V1_ACCEPTANCE.bat` remains available for a separate physical-flow re-test.

## Interpreting results

- `PASS_EXECUTED_CHECKS` — the executed checks passed, **not** a statement that physical signoff is qualified.
- `PARTIAL` — an optional/required external component was unavailable or you explicitly skipped a stage.
- `FAIL` — a required executed check failed or crashed; send the ZIP.

The test runner does not modify the manual Apollo or sensor-processing projects.
