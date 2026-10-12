# PICADS v0.13.0 — Release verification

## Development environment results

- **Python regression suite:** 453 passed, 0 failed, 1 skipped (the PySide6 GUI runtime smoke test). Executed in one complete run, with no test suite timeout.
- **Examples:** 26 / 26 bundled examples compiled successfully from isolated copies with build folders excluded. Project statuses were SUCCESS or SUCCESS_WITH_WARNINGS; see `EXAMPLE_BUILD_RESULTS_v0.13.0.json`.
- **Focused global validator:** compiled the earlier shared ADD/MUL example, the new automatic mixed ADD/SUB/LT example, and the new shared-memory example. The DLS scoreboards passed. Diagnostic runner produced an archive with overall **PARTIAL** because native Icarus, SymbiYosys/Yosys and Z3 were unavailable, and generated collateral was not executed by those tools.
- **Global shared-memory isolated source checks:** independent AST-source behavior and side effects checked with two clients; additionally validated competing port requests against a separate cycle-level memory scoreboard. Includes invalid address faults, reset, per-client stalls, and a mutation that corrupts memory data returned to a process.
- **Global binary datapaths:** all twelve supported ADD/SUB/MUL/AND/OR/XOR/EQ/NE/LT/LE/GT/GE operators underwent compiler + source-equivalence checks. Automatic selection and negative settings tests passed.
- **Formal checks:** Safety-property Verilog and `.sby` collateral were generated for resource-grant exclusivity/ownership. **Generated does not mean proved.** No native SMT execution happened in this environment.

## Independent validation limitations

- `PASS_SAMPLED` is not a universal functional equivalence proof.
- For globally shared memory, isolated AST checks plus simultaneous memory-port scoreboard do **not** establish arbitrary concurrent source-program serializability, data-race freedom or linearizability. Build stage uses `PASS_PROTOCOL_AND_ISOLATED_SAMPLED` and carries `concurrent_atomic_source_equivalence=NOT_PROVEN`.
- No live PySide6 runtime test occurred here.
- No native Icarus, Verilator, Yosys, SymbiYosys, Z3, OpenROAD, LibreLane, KLayout, Magic, Netgen or KiCad executable was available here. Absence must be represented as **UNAVAILABLE** in native test records, not PASS.
- No PDK-backed layout, DRC, LVS, timing closure, parasitic extraction, antenna, IR/EM, or mask signoff result is claimed.

The release includes `RUN_GLOBAL_VALIDATION.bat` and `RUN_FULL_VALIDATION.bat` to execute applicable checks against tools the user registers in Settings and write portable diagnostic ZIP reports. User-run native PASS reports are necessary before upgrading any native verification status.
