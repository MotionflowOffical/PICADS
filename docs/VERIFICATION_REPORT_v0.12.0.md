# PICADS v0.12.0 — executed verification report

## Completed on this development host

- `PYTHONPATH=src python -m pytest -q --disable-warnings --maxfail=1` — **426 passed, 1 skipped, 0 failed** (29.38 seconds in this environment). The skipped smoke test requires PySide6.
- All **24** bundled example projects compiled successfully from isolated temporary folders; `docs/EXAMPLE_BUILD_RESULTS_v0.12.0.json` records each outcome.
- The `global_shared_processes` example generated executable DLS, a `global_schedule.json` report and structural Verilog. Its 14 sampled source-reference rounds in the build passed; 64 rounds in the separate runner also passed.
- v0.12 targeted tests cover two and three clients, mixed-width addition, local-memory state isolation, round-robin arbitration, reset during contention, deliberate result-wire mutation, DLS serialization, generated RTL testbench and bounded formal collateral.
- **Gate count caveat:** sharing one physical ADD and MUL can increase total primitive gates for small widths due to shared arbitration and cross-process multiplexers. The compiler records both gate counts and emits an explicit `CO.GLOBAL_GATE_OVERHEAD` warning when sharing has higher primitive count.
- The focused `python -m chipcompiler.global_validation` run completed and generated a diagnostic ZIP. `project_build`, `dls_global_scoreboard` and `rtl_collateral` passed. `real_icarus_rtl` and `real_formal_safety_bmc` were UNAVAILABLE, and formal collateral generation was NOT_APPLICABLE as proof. Its overall result was **PARTIAL**.
- The full historical `python -m chipcompiler.system_validation` runner was launched. Its `compiler_pytest` stage passed, but the entire all-in-one run exceeded this host's available execution window; **do not label that full run PASS**. The focused global validator was added to give a reliably completed local path.

## External tools not present here

Actual Icarus Verilog, Verilator, SymbiYosys/Z3, Yosys, OpenROAD, LibreLane and KLayout cannot be executed or signed off on this host. A registered external-tool executable is necessary but not sufficient evidence of a production-ready design.

## Not established

No manufacturing PDK qualification, timing closure, full RTL/formal sequential equivalence, physical mask fabrication, DRC, LVS, STA, antenna, parasitic extraction or foundry signoff has been established.

## User-side automatic tests

Run `RUN_FULL_VALIDATION.bat` to collect broad integration diagnostics and available external tool executions. Run `RUN_GLOBAL_VALIDATION.bat` for a faster v0.12 focused global-resource check; it creates `validation/PICADS_v0.12.0_global_diagnostics.zip`. Report these ZIPs back to the project chat. A PARTIAL status is expected when native EDA tools are absent.
