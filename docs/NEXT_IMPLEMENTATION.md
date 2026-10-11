# Remaining engineering after v0.7.0

## Priority 1 — General concurrent HLS scheduling (NOT COMPLETE)
The new transactional CFG scheduler supports guarded branches, register-bank memory, bounded loops, stalls, explicit ready signals and per-operation reservation latencies, but allows **one in-flight transaction** and a single unit per used operation kind. Implement a scheduler with multiple in-flight tasks, resource request queues, real initiation intervals, fair arbitration of independently clocked modules, ready/valid backpressure, registered feedback, explicit memory dependencies and controller composition. Tie variable operation latency to actual supported resource interfaces and verified timing, not an artificial wait around combinational gates. Prove cycle-level protocols for all new modes. Support safe width/type flow merging across branches and general static single assignment with source map.

## Priority 2 — Full MCD graph orchestration (NOT COMPLETE)
Currently explicit typed networks are supported; arbitration primitive can be inserted manually. Build automatic allocation and routing of shared units across module boundaries, memory ports, interfaces, independent resets/clocks, buffering, fanout and deadlock detection. MCD.network must remain semantically equivalent to the source reference or report the mismatch.

## Priority 3 — Real native tool runs (NOT VERIFIED HERE)
Install and pin Icarus/Verilator, Yosys, LibreLane/OpenROAD, KLayout, and a known-good standard CMOS PDK on Windows/WSL2. Run the *real* scheduled RTL checks, actual technology mapping, physical placement/route, parasitic extraction, DRC/LVS and postroute timing. Preserve complete native logs and stage causality. UI requires real PySide6 runtime smoke testing on Windows.

## Priority 4 — Frontends and verification (PARTIAL)
Python and C/C++ are restricted statically analyzed subsets, not unrestricted language compilation. Use real Bambu/CIRCT integrations for wider synthesizable C/C++ support; consider external memory protocols and operand casts. Expand sequential formal equivalence beyond deterministic sampled checks, including reset/clock semantics, assertions on ready/done/fault and gate-level functional equivalence.

## Priority 5 — Custom technology and manufacturing (NOT IMPLEMENTED)
Develop a characterized TFT cell library and technology PDK (Liberty/LEF/GDS, RC, DRC/LVS extraction decks, power integrity, masks/polarity). The current GDS preview and artifact checks are not foundry signoff. Enforce explicit reset or proven memory/FF startup behavior for fabrication: Verilog register initializers alone do not establish an ASIC power-on state.

## Priority 6 — IDE runtime and QA (SOURCE EXISTS, UNVERIFIED HERE)
Run PySide6 on target system; verify all workspaces, autosave/restore, graphs, cancellation and responsive background builds. Add one-hot CFG step traces, arbitration signal inspectors and native tool availability diagnostics to the GUI. Avoid pretending a generated waveform or GDS screenshot proves successful fabrication.
