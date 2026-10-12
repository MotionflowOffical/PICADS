# PICADS v0.11.0 release notes

## Added

1. A structural, 32-bit, single-beat AXI4-Lite master with independent AW/W handshakes and buffered delayed B/R completions.
2. An `axi_lite_fabric` CO mode combining the tagged concurrent fabric with that AXI controller. Its front-end retains tag arbitration; the memory backend is now a real AXI4-Lite master port.
3. Independent directed and randomized AXI memory-device verification, mutation tests, generated Verilog and bounded AXI safety harness collateral.
4. A `source_processes` CO mode that compiles multiple named typed source functions to simultaneous, independently clocked transactional FSMs. Source-to-DLS sampling and a parallel execution check are included.
5. Additional example projects, docs and Windows diagnostic-runner stages for both capabilities.

## Preserved

Dependency Settings (**Choose App**, **Choose Folder**, automatic detection and saved paths), previously supported MCD networks, tagged fabric, transactional compiler, simulator, source frontends, GUI source, Yosys/LibreLane adapters and PDK inventory remain in this cumulative source distribution.

## Exclusions

General inter-process global resource sharing, AXI4 bursts, cache coherence, complete formal proof execution, validated desktop GUI runtime, PDK-driven actual chip layout, DRC/LVS/STA/PEX and fabrication signoff remain incomplete. External tools are not installed in this runtime.

## Version and validation

- Package version: `0.11.0`.
- Versioned source is delivered in a flat, SHA-256-verified archive.
- 24 new focused v0.11.0 tests passed, including source-process state isolation and AXI mutation checks. Across disjoint regression groups, 412 tests passed, 0 failed, and one PySide6 smoke test was skipped. All 23 bundled example projects compiled from isolated copies. See the verification report for exact evidence.
- Formal and external RTL checks require running the supplied validation launcher on a machine with the registered native tools; generated collateral must not be labeled proof.
