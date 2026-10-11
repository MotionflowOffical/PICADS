# Chip Compiler v0.4.0 release notes

## New working logical capabilities

- Time-shared CO operations now support **pure terminal conditional returns**, both Python `if/else` and expression-level ternaries; comparisons and Boolean NOT can feed selections. Both possible arithmetic paths are scheduled speculatively, and the output selects the computed result using an input predicate sampled at transaction start. This is **not** a general branch/stall scheduler.
- The time-sharing compiler statically expands **bounded literal `range` loops** with assignments; limits are 32 iterations per loop, 64 aggregate, depth 8. Dynamic loop bounds and side effects are explicit diagnostics.
- Scheduling of arithmetic using previous selection/comparison values includes transitive dependencies, avoiding early execution of downstream operators.
- Preserved DLS/Verilog hierarchy now supports **nested pure helper modules**, recursion is rejected with a named call path, and Verilog module definitions are emitted only once in dependency order.
- MCD `requires` supports mandatory reachable function capabilities with `min_instances` static callsite counts. Invalid or unsatisfied requirements fail compilation with independent issue IDs, instead of silently remaining unenforced.
- CO `modules.naming: mcd` optionally binds declared MCD module names to **actual** non-top DLS/RTL child module identifiers. Duplicate/conflicting/invalid identifiers fail explicitly. The top remains named after the callable source function for traceability.
- CO instance limits are now also checked **across preserved module hierarchy**; child module instances are counted separately. This is an inventory of source-level operators, not a transistor or cell count. No unsupported cross-module reuse is silently assumed.

## Mask preview and interface

- A read-only GDSII geometry SVG preview uses real polygon/path/box coordinates with supported SREF/AREF hierarchy transforms (including rotation, reflection and magnification). It is available through `chipcompiler render-mask path.gds` and the physical workspace button `Render GDS Geometry`.
- Partial previews explicitly report omitted TEXT / unsupported elements, shape clipping, and unit uncertainty. `render-mask` returns exit status **2** for a partial preview; unresolvable references and ambiguous top cells produce specific errors, not guesses.
- GUI hierarchy explorer shows actual nested DLS instances and no longer incorrectly describes preserved RTL as flattened.

## Verification evidence

- 229 tests passed; one PySide6 GUI runtime test skipped due to missing PySide6 in the execution environment.
- Clean-extraction packaging and end-to-end logical example runs are performed before release.
- No real Yosys, LibreLane, KLayout or PDK runtime was available here. Physical design and manufacturing signoff remain unverified.

## Important limits

This release is **not a complete HLS compiler, general CO scheduler, general C++ compiler, foundry-qualified DRC/LVS/timing signoff package, or mask data preparation system**. See `docs/IMPLEMENTATION_STATUS.md` and `docs/NEXT_IMPLEMENTATION.md`.
