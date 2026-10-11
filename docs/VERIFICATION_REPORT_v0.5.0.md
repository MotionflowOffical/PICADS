# v0.5.0 verification report

- Full automated test suite: **243 passed, 1 skipped**.
- The skipped test requires PySide6, unavailable in this environment.
- A clocked hierarchical project (`examples/clocked_hierarchy`) compiled with `SUCCESS_WITH_WARNINGS`, including `equivalence: PASS_SAMPLED`. The warning is `VERIFY.SAMPLING`; this is expected for stateful verification.
- Tests cover: two independent stateful child instances, nested clock propagation through combinational wrappers, DLS serialization and reload, MCD-mapped child instance names and ports, source-state namespace isolation, nonclocked observations, hierarchical register traces, VCD collision refusal, virtual-clock/input name conflict avoidance, conditional-state rejection, and short-circuit-state rejection.
- Legacy regression tests remain in the suite and are rerun on clean extraction before release.

**Not verified:** PySide6 runtime, Verilog simulation by an external simulator, Yosys technology mapping, LibreLane placement/routing, GDSII generation by real tools, DRC/LVS, electrical timing, foundry signoff and custom TFT PDK behavior.

Test counts indicate tests executed, not the percentage of the product that is complete.
