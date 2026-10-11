# v0.3.0 Verification Evidence

Executed within the release environment:

- `PYTHONPATH=src python -m pytest -q` — **207 passed, 1 skipped**.
- Hierarchical pure helper architecture — exhaustive logic input verification, 4096 input combinations in the dedicated hierarchy test.
- Spatial pipeline 1, 2, 3, 4, 7, 12 stages — exhaustive source-equivalence of small arithmetic test functions, cycle-aware valid handshake, deliberately unsupported stateful source rejected.
- Restricted shared-operator FSM — deterministic randomized 150-transaction runs for addition, subtraction, multiply combinations, plus mutation and resource-unit tests. These are **sampled**, not formal proof.
- CO and MCD negative configuration tests — causal error provenance and dependent stages BLOCKED.
- Yosys zero-exit missing/incorrect output tests — explicitly fail instead of accepting missing output as success.
- Captured stdout/stderr and timeout tests — full log retains tool failure lines before failing.

Not executed here: PySide6 GUI, Verilog lint with Yosys/Verilator/Icarus, LibreLane physical flow, DRC, LVS, timing and tapeout; because the executables and process kit are unavailable.

Implications: behavioral equivalence for tested input spaces is supported; no claims about physical timing, routing closure, masks or manufacturing.
