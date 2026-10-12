# PICADS v0.13 — Extended shared hardware resources

## Scope and guarantees

This release adds **real gate-level shared SUB/AND/OR/XOR/EQ/NE/LT/LE/GT/GE** datapaths to the prior ADD/MUL global arbiter; each selected operator is implemented once and independently arbitrated round-robin across source-process controllers. One source-process transaction per client remains the limit. Logic is unsigned and bit-vector width aware; it is not a pipeline timing or clock-closure result.

`global_shared_types: auto` examines the functions named in MCD `concurrent_clients`, including repeated instances of the same function, and selects an operator if at least two client instances use it. It does not infer unbounded processes, estimate physical area, or guarantee gate-count savings. When no operator is used by two clients, compilation stops with `CO.GLOBAL_AUTO_EMPTY` instead of constructing meaningless extra hardware.

### Example CO: automatic operator selection

```yaml
schedule:
  mode: source_processes
  global_shared_types: auto
```

### Example CO: explicitly shared register-bank memory

```yaml
schedule:
  mode: source_processes
  global_shared_memory: true
memory:
  depth: 4
  data_width: 8
```

Memory settings allow `depth: 1..32` and `data_width: 1..64`. A single globally shared register bank is constructed with a single round-robin read/write service port. Separate controller FSMs emit `unit_request_mem`, `unit_mem_write`, `unit_mem_addr`, and `unit_mem_data`, and receive a service grant plus read data. Illegal addresses advance to the source process' FAULT state without writing RAM. Global stall suppresses that process' request. Reset clears the shared RAM and arbitration pointer synchronously. Each client can have only one active source transaction; memory accesses from distinct clients are serialized per grant.

Memory can be combined with explicit globally shared arithmetic operators:

```yaml
schedule:
  mode: source_processes
  global_shared_types: [ADD, SUB]
  global_shared_memory: true
memory:
  depth: 8
  data_width: 8
```

This is a **single-port register-bank SRAM model, not a dedicated foundry SRAM macro, AXI master or cache-coherent memory**. The generated implementation uses flip-flop state and large muxes. On-chip memory size is deliberately bounded.

## Diagnostics and verification

- `global_schedule.json` lists the selected operator types and `shared_physical_units` (including `MEMORY` when selected), client ownership and gate-count comparison against independent local implementations.
- `arb_request_<type>_<client>` and `arb_grant_<type>_<client>` expose resource arbitration. `arb_mem_addr_*`, `arb_mem_wdata_*`, `arb_mem_rdata_*`, `arb_mem_write_*` expose memory-port transactions.
- `process_verification.json` for shared memory explicitly reports the isolated AST-source verification plus independent concurrent memory-port scoreboard, not arbitrary interleaving equivalence. **Concurrent atomic/serializable source semantics are NOT PROVEN.**
- The DLS verifier tests contention, reset, stalls, invalid addresses, cross-process read-after-write, and deliberately mutated hardware outputs. Native RTL equivalence remains dependent on Icarus.
- `prepare_global_shared_formal` generates bounded grant mutual-exclusion and ownership properties for *all* selected operators and for the shared memory port. Collateral is labeled `GENERATED_UNVERIFIED` until SymbiYosys/Yosys/Z3 execute successfully on the user's machine. Fairness/liveness, deadlock-freedom under arbitrary backpressure, atomicity and full source-level equivalence are not proven.
- The GUI's Concurrent Fabric inspector now displays resource grants and source FSM register snapshots for global-source designs, but PySide6 runtime remains unverified in the development environment.

## Known limitations

1. Arbitrary Python/C++ behavior, dynamic loops and unbounded control flow are unsupported by the source frontend.
2. No automatic cross-process source memory dependency inference, mutexes, fences or coherent caches.
3. Single shared register-memory access per logical cycle; no dual-port RAM, burst transactions, DMA or AXI4 full protocol binding for these source processes.
4. Only one active transaction per source-defined process; tagged fabric mode separately supports bounded multi-slot requests but is not yet a general compiler lowering target.
5. No characterized physical operator or RAM latency. Real timing/area/power and post-route behavior depend on Yosys and a real PDK.
6. Missing native toolchain, qualified PDK and foundry signoff mean **fabrication-ready masks cannot be claimed**.

## Tests / commands

```sh
python -m pytest -q tests/test_iteration13.py
python -m picads compile examples/global_auto_operators
python -m picads compile examples/global_shared_memory
python -m chipcompiler.global_validation --output validation/PICADS_v0.13.0_global_diagnostics
```

On Windows, `RUN_GLOBAL_VALIDATION.bat` invokes the focused validator. `RUN_FULL_VALIDATION.bat` additionally attempts GUI, real EDA, RTL and formal tests, records exact dependency status and makes a diagnostic ZIP that can be uploaded for analysis.
