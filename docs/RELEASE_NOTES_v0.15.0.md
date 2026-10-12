# PICADS v0.15.0 — V1 feature verification candidate

Focus: completing bounded v1.0 testing and the first user-operated chip-development experience instead of adding new optional architecture features.

- New **source-only 4-bit ALU slice** with ADD, four-bit SUB, AND and XOR. Exhaustive 1,024-case independent oracle and deliberate bit-wiring mutation check. No handmade netlist or GDS.
- One-command Windows `RUN_PICADS_AUTOTEST.bat` / `chipcompiler.feature_validation`, including CLI user journeys, deliberate source failures, VCD export, safe recovery, optional native RTL/synthesis and first-chip physical acceptance, and a ZIP with evidence.
- Qt GUI workflow robot via actual widgets and event loop, executed only with PySide6 installed; no fabricated Qt test result.
- GUI correctness fixes: invalidate stale DLS when compiling changed source; avoid retaining editor tabs, simulated state, problems and crash-marker state from a previous project when opening another.
- Physical acceptance guard against a null equivalence status; no unhandled `None.startswith` when logical compile fails.
- Historical tests can run in isolated subprocesses with `--full-regression`; default rapid feature checks do not conflate a timed-out full suite with passing tests.

Limitations: no real Icarus/Yosys/LibreLane, Qt or qualified PDK runtime available in the development container. Actual RTL, physical layout, DRC/LVS and GUI execution remain machine-side evidence requirements. General source-to-GDS for any arbitrary hardware code is not supported.
