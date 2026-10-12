# PICADS v0.9.0 — verification evidence and qualification limits

Release testing is performed with pytest and the in-process executable DLS simulator, including pure arithmetic scoreboards, memory-device BFM, structural DLS round-trips, generated RTL testbench generation, deliberately corrupted signal mutations, project CO/MCD validation and end-to-end example builds.

A clean release test report is generated during packaging. The local machine does not have native Icarus Verilog, Yosys, SymbiYosys/Z3, LibreLane/OpenROAD, KLayout or PySide6. Their executable behavior cannot be declared successful on this machine; the included Windows validator records actual tool availability and outputs per-stage evidence.

The generated formal harness checks *only safety invariants at bounded depth* if and when externally executed. It is not an unbounded formal proof. DLS-vs-exported-RTL tests are sampled; they cannot establish layout-vs-RTL equivalence or physical timing.

Fabrication requires a qualified process design kit, layer mappings and minimum widths/spacings, DRC/LVS/PEX, antenna and power integrity, timing and library corner checks, foundry constraints, mask-preparation rules and independent signoff. None is certified by PICADS v0.9.0.
