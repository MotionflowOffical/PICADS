# PICADS v0.11.0 — executed verification report

## Local regression

Executed the complete collected test suite in bounded, disjoint groups (the single combined run exceeded this container's execution timeout; the same tests passed when divided by test files):

| Command group | Result |
| --- | --- |
| `pytest tests/test_logic.py tests/test_pipeline.py tests/test_iteration2.py ... tests/test_iteration7.py` | 308 passed |
| `pytest tests/test_iteration8.py tests/test_iteration9.py` | 64 passed |
| `pytest tests/test_iteration10.py tests/test_iteration11.py tests/test_gui_smoke.py` | 40 passed, 1 skipped (PySide6 unavailable) |
| **Total across disjoint groups** | **412 passed, 0 failed, 1 skipped** |

24 passing tests in `tests/test_iteration11.py` exercise AXI configuration, directed/randomized independent slave, tagged composition, read/write strobe/data mutations, parallel source-state and private RAM isolation, MCD configuration failures, generated formal harness and the diagnostic runner.

All **23 bundled example projects** compiled successfully from isolated temporary copies, including `axi_lite_fabric` and `source_processes`.

## Automatically generated evidence

- `fabric_protocol.json` for AXI includes directed handshake scenarios and three deterministic independent randomized AXI slave runs.
- `process_verification.json` records sampled reference comparisons for each compiled process plus a concurrent multi-instance execution check.
- Generated DLS round-tripped through JSON serialization and exported structural Verilog in targeted tests.
- The system validator creates one ZIP containing test reports, tool status, native logs and proof collateral. It does not label unavailable tools PASS.

## Explicitly not tested here

- Actual Qt/PySide6 desktop runtime (not installed on this host).
- Icarus/Verilator native RTL simulator execution (unavailable).
- Actual Yosys, SymbiYosys/Z3, OpenROAD, LibreLane, KLayout, DRC, LVS and STA execution (unavailable here).
- Any qualified custom PDK, physical GDS/photomask generation, extraction, reliability, timing or foundry manufacturing signoff.

Digital protocol tests and bounded safety **collateral** are not proof of AXI compliance, nor of a manufacturable custom TFT semiconductor process.
