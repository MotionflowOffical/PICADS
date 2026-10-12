# PICADS v0.12.0 — release notes

- Added opt-in global ADD/MUL source-process sharing with a **single synthesized combinational arithmetic gate network per operator** and separate round-robin service per type.
- Externalized selected arithmetic operands, results and ready/grant signals from transactional source FSMs, flattened into clocked DLS, and topologically sorted the merged logic.
- Added typed 2–8-client source process allocation, mixed operand widths, clear invalid-source/missing-unit/duplicate-client/cycle diagnostics, and trace outputs per client.
- Added `global_schedule.json` with resource clients/physical operator counts and explicit limits.
- Added sampled AST-reference scoreboard, mutation tests, private memory state isolation, reset and fairness checks; added generated but UNVERIFIED SBY properties for grant mutual exclusion and ownership.
- Extended RTL stimulus for clocked source-process modes and automatic Windows diagnostic runner stages for the new design.
- Existing mode `source_processes` without `global_shared_types` preserves v0.11 architecture and behavior.
- External native RTL/formal/EDA execution and manufacturing signoff still require actual installed tools/PDK and are NOT certified by this release.
