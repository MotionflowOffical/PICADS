# PICADS v0.14.0 — scope freeze and first-chip physical handoff

## New / improved

- `docs/FUTURE_FEATURES.md` separates advanced post-v1 plans (full AXI4, DMA, arbitrary concurrency, etc.) from the original planned software requirements.
- `docs/V1_SCOPE_AND_ACCEPTANCE.md` fixes the first-feature-complete definition at a bounded source-to-RTL-to-GDS workflow backed by real external evidence.
- Physical preflight normalizes and validates PDK name/root, clock period, core utilization, placement density, die bounds, SCL selection and timeout.
- `picads physical-preflight PROJECT` and a GUI physical-tab preflight button give actionable configuration diagnostics.
- Actual LibreLane physical flow emits `physical_preflight.json` and `physical_handoff.json`, recording SHA-256 of exact source RTL and flow config and detecting modification during external execution.
- GDS verification detects wrong top cell or empty element streams; hashes GDS, final metrics and available DEF/netlist/LEF/SPEF views.
- New `examples/first_physical_chip` is a small synchronous reference design, and `RUN_V1_ACCEPTANCE.bat` collects real Windows-side RTL/synthesis/layout status into one diagnostic ZIP.
- Existing compiler/scheduler capability remains unchanged except for physical-flow validation and evidence handling; older batch validators are retained.

## Local verification

- 479 Python regression tests passed when test files were run in separate Python/pytest invocations; 1 Qt GUI test skipped.
- All 27 example projects compiled from isolated copies.
- The v1 acceptance runner created an archive with logical compile PASS and honest UNAVAILABLE statuses for local native RTL/synthesis/layout tools.
- Live external tool, GUI runtime, full process DRC/LVS/STA, custom TFT technology mapping and manufacturing signoff were not executed here.

**This version is not a manufacturing-qualified v1.0 release.**
