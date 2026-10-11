# Verification evidence — Chip Compiler v0.4.0

## Executed checks in release environment

- `python -m pytest -q` — **229 passed; one PySide6 GUI smoke test skipped**.
- `python -m compileall` — package/test Python source syntax passed.
- Nested preserved hierarchy with deduplicated RTL module declarations and exhaustive 4-bit test cases; name bindings propagated to actual DLS/RTL child instances.
- Time-shared pure terminal `if/else`, ternary selection, derived comparisons and `not`: deterministic transaction sampling with independent behavioral reference.
- Bounded range-loop arithmetic sharing: source/DLS sampled transaction comparisons, with nonliteral loop rejection.
- Mandatory MCD binding failure, impossible requested instance count, invalid schema and recursive child modules: exact machine-readable primary failures; dependent stages blocked.
- Resource counts across repeated child instances: expected global limit refusal instead of silently accepting a per-module local limit.
- GDSII geometry preview: real BOUNDARY polygons, SREF cell references, unknown target errors, explicit shape clipping and partial status, CLI exit status 2 on partial preview.
- Direct example builds: `conditional_scheduler` (sampled), `bounded_loop_scheduler` (sampled), `nested_named_modules` (small combinational exhaustive); all reached source-to-DLS verification and RTL export.
- Clean extraction and regression testing from packaged archive performed for the release.

## Environment and unverified functionality

The runtime diagnostic inventory reported GCC and G++ available, but **Yosys, Icarus, LibreLane, OpenROAD, Magic, Netgen, KLayout and PySide6 unavailable**. Therefore:

- **No GUI widget runtime demonstration** was possible (source syntax/structural checks only).
- **No emitted RTL executed in an independent Verilog simulator or synthesizer here**.
- **No actual routed GDSII was generated in this environment**.
- **No process-specific DRC, LVS, parasitic, timing corner, PDK or mask signoff completed**.

The GDS rendering tests use deliberately constructed small valid GDSII fixtures. This verifies the tested parsing and rendering behavior, not completeness on every real manufacturing layout. A GDS geometry display is *not* electrical or fabrication evidence.

## Interpretation

`PASS_EXHAUSTIVE` is limited to source/DLS test spaces below the configured bound. `PASS_SAMPLED` is not a formal proof. A successful structural mask preview means only that supported geometry was interpreted from the file, possibly partially. Toolchain/PDK signoff cannot be inferred from either.
