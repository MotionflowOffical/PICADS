# Chip Compiler v0.8.0 — Concurrent resource fabric

- Added `CO.schedule.mode: concurrent_fabric` for 2..8 independent requesters, one buffered transaction per client, with separate arithmetic and memory arbitration domains.
- Added gate-level one-hot fair arbitration, round-robin pointer state, stable external ready/valid request payload under ordinary backpressure, variable-delay external responses, and a single-port on-chip memory bank.
- Added client-specific held responses, independent reset/stall handling, invalid-address faults, and debug event output pins.
- Added a bounded directed DLS protocol verifier, independent randomized scoreboard over 3 seeds, failure replay evidence, and deliberate-corruption tests.
- Added Icarus RTL-vs-DLS sample vector generation for this protocol, plus full automatic Windows integration validator with a ZIP bundle of actual logs and explicit unavailable statuses.
- Added a GUI Concurrent Fabric inspector displaying state from executable DLS, not synthetic visuals (Qt runtime still untested locally).
- All 308 v0.7 regression tests remain passing; v0.8 adds 24 new tests. 332 passed, 1 Qt smoke skipped in this environment.
- Full general concurrent HLS, automated connection to arbitrary MCD producers, real EDA runs, physical masks and foundry signoff remain unfinished.
