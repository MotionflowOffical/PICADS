# v0.6.0 verification report

**Tested:** procedural MCD inter-module composition, automatic safe external-port matching, optional unique-width inference (warnings and ambiguity rejection), dependency topological sorting, slice and width checking, module hierarchy, independent child register state, clock enable and synchronous reset, source-DLS comparisons, simulator protocol inspection, controlled negative-case diagnostics, and existing regression coverage.

**External test limitation:** Icarus Verilog, Yosys, LibreLane, OpenROAD, KLayout, and PySide6 executables were not available in the release environment. RTL testbench orchestration was tested using instrumented simulations of external tool statuses, including mismatches, missing executables and incomplete output; this is **not** a live HDL verification claim. The GUI test is skipped when PySide6 is absent.

**Physical fabrication limitation:** No real foundry-qualified physical design, GDSII mask generation, extracted LVS, complete timing closure, electrical signoff or mask qualification was performed. Absence of metrics yields `UNVERIFIED` checks.

A test count and reproducible commands are appended during release packaging after a clean-extraction verification.

## Release environment results

- Automated tests: **275 passed, 1 skipped** (`pytest -q`). Skipped: PySide6 GUI runtime smoke test (Qt unavailable).
- All 13 bundled example projects compiled with successful exit status; `examples/explicit_network` passed an exhaustive source-to-network DLS comparison over 512 input vectors.
- Real GCC/G++ available and native-C regression coverage passed.
- Real Icarus, Yosys, LibreLane, OpenROAD, KLayout, Magic, Netgen and PySide6: **unavailable**. Package-manager attempt did not complete, so no physical/simulator success is claimed.
- A mock zero-exit external physical run without GDS is rejected as `PHYSICAL.ARTIFACT_INVALID`. A clocked descendant correctly causes `CLOCK_PORT: clk` in generated LibreLane configuration.
- Negative tests confirm diagnostic origins and blocked downstream stages rather than cascaded false errors.

Reproduction: `python -m pytest -q` and `python -m chipcompiler compile examples/explicit_network` from an editable installation or with `PYTHONPATH=src`.
