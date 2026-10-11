# Implementation status — v0.7.0

| Subsystem | Demonstrated status |
|---|---|
| Procedural primitive logic construction | Tested, restricted subset |
| Executable DLS / register simulation | Tested, including nested clocked hierarchy |
| MCD hardware networks | Typed explicit networks tested; partial automatic unique-width inference |
| CO transactional CFG scheduler | Working restricted one-transaction FSM with real gate-level logic |
| Branch-dependent execution | Tested (unselected branches do not execute memory operations) |
| Resource allocation | One shared physical gate network per operation kind, inside transactional controller |
| Operation latency/backpressure | Tested logical reservation and `unit_ready`, NOT physically characterized variable-latency unit |
| Memory | One on-chip register-bank, synchronous guarded operations, explicit invalid-address fault |
| Global stall/reset | Tested synchronous active-high reset and state-freezing stall |
| Cross-module arbitration | Reusable round-robin DLS primitive with MCD explicit network binding; no automatic allocation/queueing |
| Python frontend | Restricted statically-analyzed hardware subset |
| C/C++ frontend | Restricted C-compatible subset; tested C transactional example |
| GUI | Source exists, PySide6 runtime **not tested here** |
| DLS structural Verilog generation | Tested output, but no independent RTL execution here |
| External scheduled RTL harness | Implemented/testbench generated; Icarus uninstalled |
| Yosys/LibreLane adapters | Existing adapters and diagnostics, live tool execution untested |
| GDSII inspection | Existing structural parser/preview for supported layout shapes |
| Real physical chip/mask generation | **NOT DEMONSTRATED** |
| Qualified DRC/LVS/timing/power & foundry signoff | **NOT IMPLEMENTED / NOT VERIFIED** |

The new work is **not** a complete unconstrained general high-level synthesis tool. See `NEXT_IMPLEMENTATION.md`.
