# PICADS v0.12 — Shared arithmetic across source-defined process controllers

## Purpose

`source_processes` previously instantiated independent, locally time-shared arithmetic hardware in every process. The new opt-in `global_shared_types` declaration compiles each source-defined transactional CFG with external ADD/MUL handshake ports, then constructs **one real bit-gate ADD and/or MUL datapath in the combined top-level DLS**. A round-robin arbiter per operator returns a completion grant and shared result to one requesting process per clock.

This is *not* a fully general source-to-HLS scheduler. It handles the already-supported bounded transactional source subset, multiple independent processes, unsigned ADD/MUL units, and separate private register memories.

## Configuration

`examples/global_shared_processes/architecture.co`:

```yaml
schedule:
  mode: source_processes
  global_shared_types: [ADD, MUL]
  latencies:
    MUL: 2
```

MCD declares 2–8 named clients with `{name, function}` entries. Each child processes one request at a time and has private controller registers. Static source `if` branches, bounded loop expansion, and other locally supported CFG instructions remain available. `global_shared_types` is an explicit opt-in; omitting it retains the v0.11 independent hierarchy.

## Execution and hardware

1. Compile each client function with an externalized ADD/MUL datapath, without generating the corresponding child ALU.
2. Expose each child's operation request, selected operands and global result input. Requests assert only at the final reserved operation stage, outside stalls and reset.
3. Flatten controllers into one DLS (necessary for combinational ready/results crossing module boundaries). Preserve separate register names for each physical process.
4. Generate one global ADD and/or MUL gate-level datapath per declared kind, selecting winning operands and issuing one ready grant per unit per rising clock. The round-robin pointer advances only after accepted grants.
5. Topologically order every merged combinational primitive and reject undefined pins, duplicate drivers and combinational cycles. DLS validation rejects unconnected outputs/next-state logic.
6. Export DLS and structural Verilog. `global_schedule.json` records source clients, shared units, arbitration and limitations.

Per-client `start`, `stall`, `done`, `ready`, `fault` and result interfaces remain. `arb_request_<kind>_<client>` and `arb_grant_<kind>_<client>` are included as observability signals.

## Verification coverage

- Source AST reference independently scores batched transactions, changing live source inputs after acceptance, stalls and arithmetic contention.
- The DLS simulator checks that only one grant per shared type is active on each sampled cycle.
- Tests verify round-robin service order, reset during contention, mixed operator widths, source results, separate private memory registers, serialized DLS, generated structural Verilog, and a deliberately corrupted result wire.
- Generated SymbiYosys collateral checks grant mutual exclusion, owner requests and reset gating under a bounded reset assumption. **Generation is not a proof.** The actual solver runs only on a system with Yosys, SymbiYosys and Z3 installed.
- Optional Icarus testbench checks sampled RTL output traces against DLS using synchronous process starts and stalls; actual native execution is environment-dependent.

## Explicit limits

- ADD and MUL only, unsigned, within the transactional compiler's supported widths.
- One active transaction per source process; no automated reorder buffers or cross-process dependencies.
- Per-operator completion is a single combinational gate network per granted cycle after configurable reservation stages; **not a real multi-cycle pipelined/variable-latency floating-point or integer macro**.
- No cross-process shared memory arbitration, cache, DMA, AXI4 bursts, or automatically generated memory coherence.
- No physical timing characterization or assertion of timing closure; synthesis must map these gates to a real target technology.
- Verification is sampled plus generated bounded safety properties, not universal source equivalence or process-qualified manufacturing signoff.

## Commands

```sh
python -m picads compile examples/global_shared_processes
python -m picads compile examples/source_processes
python -m pytest -q tests/test_iteration12.py
```

The Windows `RUN_FULL_VALIDATION.bat` executes project compilation, sampled DLS tests, generated formal collateral, and available external RTL/SMT runs automatically. Missing tools are reported as UNAVAILABLE, never PASS.

## Gate-count disclosure and optimization limits

The compiler now records a direct gate-count comparison between the global shared circuit and separately compiled source-process gate networks. For the included 4-bit example, the **shared version can have more total primitive gates** than the independent version because arbitration, external-result distribution and operand selection incur overhead. This is not a contradiction: there is one shared ADD and one shared MUL network, but the *total* circuit may be larger. The compiler emits `CO.GLOBAL_GATE_OVERHEAD` when this occurs rather than describing sharing as an area saving. Gate count is not post-synthesis cell area or timing; any area/power tradeoff must be measured after real target-library synthesis.
