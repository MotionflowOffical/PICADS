# PICADS v0.15.0 — implementation status

PICADS remains an experimental digital hardware compiler and EDA orchestration environment. Its logical tests cannot certify a custom TFT process or foundry mask manufacturability.

| Subsystem | State | Verification boundary |
|---|---|---|
| Typed Python, restricted C subset | Supported and regression tested | Not general Python/C/C++ hardware compilation |
| DLS, clocked modules, structural Verilog | Tested | External independent RTL runtime not installed here |
| MCD/CO scheduling, tagged fabrics, shared operators/memory | Tested subsets | Not arbitrary concurrent HLS or fully automated PPA optimization |
| Simulation/source/protocol checks | Tests pass | Sampled, not full formal proof |
| GUI Settings and dependency registration | Source implemented | PySide6 GUI runtime not exercised here |
| Synthesis | Yosys adapter and stricter input/output checks | No live local Yosys executable |
| Physical planning and preflight | **New** validated PDK/technology/floorplan/clock configuration | Preflight is not technology qualification |
| Physical handoff | **New** hashed RTL/config provenance; detectable modified inputs | Hashes don't prove correct layout |
| LibreLane placement/routing | Adapter and run-log capture | No local LibreLane/real-PDK execution |
| Final mask evidence | **Extended** parsable GDS, expected top, file hashes, actual final metrics | No manufactured mask or foundry certification |
| One-click v1 first-chip acceptance | **New** automatic test and diagnostic ZIP | PARTIAL here; native EDA missing |
| PDK characterization & fabrication signoff | Unimplemented | Requires qualified process and independent DRC/LVS/STA/RC/power etc |

**v0.15 QA evidence:** the new seven focused `test_iteration15.py` cases pass, including exhaustive independent verification of the new 4-bit ALU slice. The automated CLI user journeys and the first-chip acceptance runner return `PARTIAL` locally (native EDA and PySide6 unavailable). Selected older regression files pass. The complete historical suite has **not** finished in this iteration, so no new all-suite PASS is claimed. For the full historical audit, use `RUN_PICADS_AUTOTEST.bat --full-regression` on a machine that can complete it.

See [V1_SCOPE_AND_ACCEPTANCE.md](V1_SCOPE_AND_ACCEPTANCE.md) for the fixed first-release requirements and [FUTURE_FEATURES.md](FUTURE_FEATURES.md) for the separately deferred enhancements.

## v0.15 additions

- Independent, source-only ALU component, no handmade Verilog or masks. The 1,024 input cases are checked against a separately written oracle.
- CLI user-journey robot + Qt GUI user-journey tests (only when PySide6 is installed) including intentionally induced errors and recovery.
- Qt stale-build safety fix and project-switch state isolation.
- Windows auto-test launcher and one portable diagnostic ZIP; installed Icarus/Yosys/LibreLane are used when available and otherwise marked UNAVAILABLE.
- Real native tool execution, complete DRC/LVS/STA and custom TFT qualification remain unverified/unfinished. See `AUTOMATED_V1_VERIFICATION_v0.15.0.md`.


## PICADS v0.16.0 — Windows-first dependency handling

A native Windows install dialog now downloads only checked optional packages into the project-local `dependencies/` directory. Supported managed archives include Windows OSS CAD Suite and KLayout. The installer records SHA-256 receipts, enforces origin/archive protections, and registers tools for subsequent builds. The native Windows path does **not** install Linux, WSL, Docker, or Linux-only EDA executables.

The LibreLane/OpenROAD physical-flow adapter is **not a natively packaged Windows backend**. To run that standard-cell RTL-to-GDSII flow on Windows, the user still needs the separately configured supported WSL2/Docker backend and a working PDK. This remains required integration work before PICADS v1.0 can claim real Windows-hosted end-to-end ASIC output.
