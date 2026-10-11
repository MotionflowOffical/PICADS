# Chip Compiler v0.5.0 release notes

This iteration adds **real clocked nested hierarchy** without claiming general-purpose scheduling or a completed physical implementation backend.

- Preserved MCD helper modules may own state; the DLS simulator keeps one persistent set of registers for each physical child instance, including nested children.
- All stateful descendants receive an implicit, shared rising-edge clock; intervening pure wrapper modules forward it. Structural Verilog exports the matching port and connections.
- Source-reference verification isolates register names by *call site* rather than sharing same-named registers between distinct helper instances.
- Sequential child hierarchy is checked using deterministic multi-cycle source/DLS samples; sampled results remain labeled `PASS_SAMPLED`, not formal proof.
- Two new explicit source diagnostics prevent incorrect speculative register updates inside conditional branches or short-circuit expressions.
- DLS simulators expose per-instance register snapshots; the GUI source and VCD output now display internal child state.
- The VCD exporter refuses signal-name collisions instead of silently overwriting a port and preserves user-provided combinational input signals called `clk`.
- New self-contained `examples/clocked_hierarchy` uses actual MCD module naming, two clocked child instances and output verification.

## Verification

243 automated tests passed, one PySide6 GUI smoke test skipped. The included example compiles, produces DLS and structural Verilog, and passes sampled equivalence. Qt GUI execution and physical ASIC tool runs are **not** tested here because the dependencies are unavailable. No physical signoff or fabrication-ready masks are claimed.

## Still incomplete

General graph-wide CO scheduling and sharing, arbitrary clocked state control, RAM interfaces, unrestricted C++/Python compilation, GUI runtime acceptance, real Yosys/LibreLane/OpenROAD flow, custom PDK characterization, timing/DRC/LVS/signoff and mask data preparation. See `NEXT_IMPLEMENTATION.md`.
