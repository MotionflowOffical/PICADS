# PICADS v0.15.0 — release verification report

## Evidence executed in the development container

- `tests/test_iteration15.py`: **7 passed**, including the source-only ALU's full 1,024-entry independent truth table, corrupted output wiring, malformed syntax, invalid name, recovery, and generated RTL testbench checks.
- Selected regression set `tests/test_iteration14.py tests/test_iteration15.py tests/test_pipeline.py tests/test_logic.py`: **171 passed**, zero failures.
- **28/28 bundled example projects** compiled from isolated temporary copies, using the normal BuildSession pipeline. See `EXAMPLE_BUILD_RESULTS_v0.15.0.json`.
- `python -m chipcompiler.feature_validation` (default feature robot): all logical/CLI stages passed and a diagnostic ZIP was created. Overall **PARTIAL**, because GUI PySide6 and native Icarus/Yosys/LibreLane were unavailable here.
- `tests/test_gui_workflow.py`: authored and syntax checked, **not executed** in this container because PySide6 could not be installed. The Windows robot performs the actual Qt user journeys; until that run, GUI automation is UNVERIFIED.
- The historical complete regression suite did **not** finish in this development iteration. Individual older test files and the selected test group passed, but a monolithic invocation exceeded local execution time. Do **not** report the entire expanded suite as passed. On Windows, opt into all historical tests using `RUN_PICADS_AUTOTEST.bat --full-regression`.

## Remaining independent tests

- Native Icarus Verilog testbench execution of the generated ALU RTL and the clocked first-chip RTL.
- Actual Yosys synthesis logs and synthesized netlists.
- LibreLane placement/routing to real GDS for a supported, installed standard-cell PDK.
- Real PySide6 window/action automation on Windows, with artifacts and screenshots.
- Process-specific DRC, LVS, timing, RC, power/IR, antenna and foundry acceptance evidence.

**Manufacturing qualified: NO.** A `.gds` file is not a complete mask set or a foundry signoff.
