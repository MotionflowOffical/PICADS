# Chip Compiler v0.6.0 — release notes

Cumulative source package including v0.1–v0.5 work.

### Major implemented additions

1. `MCD.network`: an actual typed inter-module hardware composition layer, not just descriptive module declarations. Dependency-sorted child instances support combinational and registered DLS, sliced buses, constants, port checking, exhaustive/sampled source comparison, and hierarchical structural RTL.
2. Optional `network.auto_connect: unique_width`, conservative one-producer matching with explicit warning and a machine-readable connection manifest. Refuses ambiguity and cycles; top-port name matching requires no extra setting.
3. `reg("name", value, init=N, enable=bool_signal, reset=bool_signal)`: clock enable and synchronous reset; reset has precedence. Implemented in procedural gate construction and separately in the source-reference interpreter, so no special non-gate HDL operators are required.
4. Optional independent Icarus Verilog testbench generation/execution with strict log/marker parsing, provenance, dependency failures and counterexamples. This run is **not** marked live-tested in the release environment.
5. Network failure stages are explicitly `FAIL` at `network`; dependent `generate`, `equivalence`, and `export` are `BLOCKED` by the actual issue IDs, not duplicated as separate generator crashes.
6. Physical configuration for hierarchical sequential designs now recognizes the implicit clock from clocked children. Missing DRC/LVS/timing metric fields remain explicitly `UNVERIFIED`.
7. The existing safety mechanisms remain: atomic file snapshots, archived builds, strict tool failure handling, source-to-DLS verification, and detailed diagnostic bundles.

### What did not become complete

- General latency-variable CO scheduling, branch-aware FSM execution, memory transactions, stalls, cross-module arbitration and retiming remain incomplete.
- Full ISO C or C++ (templates/pointers/objects) synthesis is not implemented; only the documented hardware subset works.
- GUI source is present but was not launched under Qt in the release environment.
- Actual Yosys, Icarus, LibreLane/OpenROAD, KLayout signoff and a suitable PDK are not installed here. No chip has been physically routed or foundry-qualified as part of this release.

See `MCD_NETWORK_v0.6.0.md`, `RTL_CHECK_v0.6.0.md`, and the updated implementation-status and verification reports.
