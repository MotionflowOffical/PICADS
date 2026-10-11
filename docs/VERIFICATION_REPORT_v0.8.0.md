# v0.8.0 verification evidence

**Locally executed**: Python pytest suite **332 passed, 1 skipped** (the skipped PySide6 smoke test requires the actual Qt dependency). The v0.7 baseline was **308 passed, 1 skipped**. v0.8 added 24 tests.

Compiler-backed concurrent fabric example: `BuildSession` produced a valid executable DLS, a structural Verilog top, `fabric_protocol.json`, `report.json`, and `events.jsonl`. Build stage statuses were `generate: PASS`, `equivalence: NOT_APPLICABLE`, `protocol_check: PASS`, `export: PASS`. The overall local status is `SUCCESS_WITH_WARNINGS`, because there is no independent source function for this service primitive. The model is NOT marked source-equivalence proven.

Directed protocol checker: 4 builtin scenarios / 5 external ready/valid scenarios; randomized independent memory/transaction scoreboards at fixed seeds **8291, 29471, 19013**, **160 edges per seed**; checks include one-hot resource grants, stale-data corruption, backpressure stability, stall freeze, reset, memory ordering, and source-independent expected results. The tests deliberately replace a generated response with zero and require failure with an input trace. Other negative tests reject malformed CO settings before the generator runs.

The one-command system validator ran here without installing tools and produced `PARTIAL` (as expected): compiler pytest and DLS fabric checks and example builds passed, while **PySide6, Icarus RTL simulator, Yosys, LibreLane/KLayout/qualified PDK physical flow were not executed** due to absent dependencies or no PDK-backed project. Actual native tool verification is available from `RUN_FULL_VALIDATION.bat` on the user's Windows system.

**Unproven:** general concurrent synthesis from arbitrary sources, external RTL equivalence, timing and leakage under a PDK, DRC/LVS and manufacturing-ready masks. A GUI source-code tab is not a GUI runtime test. A structural Verilog file is not proof of ASIC synthesis or successful signoff.
