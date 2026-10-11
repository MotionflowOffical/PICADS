# Verification evidence — v0.7.0

Verification categories deliberately remain distinct.

1. **Python-level regression:** 308 passing tests, 1 skipped GUI runtime test (PySide6 missing), 0 failures. Covers previous releases and new control-flow, memory, stall/reset, arbitration and fault cases.
2. **Clean project builds:** 16 bundled example projects compile, including transactional controller, scratchpad memory and restricted-C scheduled source. Their behavioral claims are sampled/exhaustive as reported by each `equivalence.json`, not blanket formal equivalence.
3. **Source-to-DLS checks:** Deterministic sampled input vectors and independent AST evaluator; includes changed input values during BUSY, stalls, ready backpressure, memory read/write and out-of-bounds faults. Intentional corrupted generated output is caught with `VERIFY.CFG_MISMATCH`, including an instruction trace.
4. **RTL export:** Structural Verilog is generated for the same primitive nodes; scheduled Icarus testbench generator is exercised. **Real Icarus execution not available**, so no claim of independent RTL simulation passing.
5. **External EDA, GUI and physical design:** iverilog, vvp, Yosys, OpenROAD, LibreLane, Verilator, KLayout and PySide6 are absent in this environment. No physical DRC/LVS/timing or mask signoff claim.

Release ZIP is checked by clean extraction and rerunning the same regression suite before publication. Re-run `python -m pytest -q` and `python -m chipcompiler compile examples/transactional_controller` from the extracted root.
