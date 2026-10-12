# PICADS v0.16.5 — Verification report

## Source of changes
User-supplied PICADS v0.16.4 Windows diagnostics revealed three false GUI test failures and two environment-dependent historical tests.

## Fixed
- GUI editing is now done through input events and QTextCursor operations instead of document reset.
- Test output assertions query the registry and availability structurally.
- Example project test excludes PICADS autosave/snapshot files from input inventory.
- Offline repair CLI test operates on a deliberately empty, isolated dependency root.
- Default runner executes v1 feature contracts; older iteration tests are developer-only opt-in.
- Per-test JUnit XML plus `v1_capability_matrix.json` added to the diagnostic ZIP.
- Matching v0.16.5 filenames used by the Windows launchers.

## Feature scope exercised
Python/C compilation, typed MCD network construction, CO transaction controllers and memories, global shared operators/memory, DLS and Verilog export, exhaustive ALU oracle (1024 cases), mutation detection, invalid-source recovery, native CLI, dependency registration, physical preflight, report packaging, and Windows Qt GUI journeys where available.

## Claims and limitations
Test failures from the previous Windows package are treated as test-design defects on that evidence, **not proof of compiler correctness**. Running the patched Qt actions on Windows is still required. External Icarus, Yosys, LibreLane and PDK-backed physical signoff are not verified by the local tests. Physical preflight is not a fabrication qualification.
