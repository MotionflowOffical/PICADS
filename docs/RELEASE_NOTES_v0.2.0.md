# Chip Compiler v0.2.0 — implementation continuation

Compared with v0.1.0:

- Added a **restricted AST-based C / C-compatible C++ frontend** with unsupported-syntax failures and C source-line mappings. Saves `normalized_source.py` for troubleshooting.
- Added **opt-in native C/C++ execution checks** using GCC/G++ and recorded counterexamples where the original source differs from executable DLS. This is bounded testing, not proof.
- Added procedural **conditional operator sharing** and enforceable CO `allocation.max_instances` limits. An impossible allocation fails with `CO.RESOURCE_LIMIT` instead of silently duplicating hardware.
- Added **function/module dependency reports** and independently compiled helper module DLS/RTL candidates. The physical top is still flattened; arbitrary MCD/CO routing is not complete.
- Added **waveform trace export** (logical VCD), GUI trace history and optional internal-gate tracing.
- Improved the **LibreLane adapter** with unique run directories, GDS existence/structure checks, selected metric ingestion and `UNVERIFIED` status where signoff evidence is missing.
- Added a read-only **GDSII stream inspector** (cell, layer and element inventory). It does not do DRC/LVS or render mask polygons; KLayout integration remains necessary.
- Added explicit **WSL2 dispatch** for optional EDA subprocesses, untested on a Windows host in this release environment.
- Added GUI autosave controls, settings persistence, module hierarchy listing, trace export and mask inspection. PySide6 was unavailable to launch here.
- Reworked **build artifacts** to archive `build/latest` on each rerun so previous results cannot masquerade as the new build.
- Extended regression coverage from **138 tests** in v0.1.0 to **171 passing tests** in v0.2.0, with 1 Qt smoke test skipped locally because PySide6 is absent.

## Scope still incomplete

General clock-cycle scheduling, arbitrary MCD/CO physical module allocation and module-to-module routing, broad C++ language support, native GUI runtime verification, installed Yosys/LibreLane end-to-end testing, and qualified manufacturing-mask signoff remain incomplete. The exact next-step engineering checklist is in `docs/NEXT_IMPLEMENTATION.md`.
