# Transactional CO scheduler — v0.7.0

## Scope and proof boundary

`mode: transactional` synthesizes a restricted control-flow graph into **gate-level DLS**, shared combinational units, a one-hot FSM, typed data registers, optional register-bank scratchpad memory and a START/READY/DONE/FAULT handshake. The supported code is hardware description, not unrestricted Python or general C/C++ execution.

**This is NOT a complete HLS scheduler**: one transaction is in flight; no independently overlapping transactions, unbounded loops, recursive functions, pointers, DMA/external memory interface, clock domains or timing-constrained resource arbitration across arbitrary MCD modules. See `NEXT_IMPLEMENTATION.md`.

### CO configuration

```yaml
schedule:
  mode: transactional
  latencies:
    ADD: 2
    MUL: 3
    READ: 2
    WRITE: 2
  ready_types: [MUL, READ, WRITE]
allocation:
  max_instances:
    ADD: 1
    MUL: 1
memory:
  depth: 4
  data_width: 8
```

- `latencies`: 1..16 **reservation cycles** for each operation kind. The shared arithmetic network is still combinational. This does NOT implement a physically iterative multiplier with characterized timing.
- `ready_types`: adds `unit_ready_add`, `unit_ready_mul`, etc. Inputs gate completion of the corresponding operation. Outputs such as `unit_active_mul` indicate a pending operation. Requests and operand buses are not an independent external accelerator protocol.
- `memory`: one fixed register bank, depth 1..32, width 1..64. `mem_read(address)` and `mem_write(address, value)` are synthesized through muxes, decoders and actual state bits. Reads/writes are executed only along the selected control path. Invalid addresses raise `fault`, complete the transaction and retain the previous committed output. `fault` is latched until next START or RESET.
- A single shared operator is generated per operation kind used by the design. A resource limit other than 1 is rejected rather than silently ignored. Resource sharing is within this controller, not across arbitrary separately clocked modules.

### Protocol

Input ports: every source parameter, `start`, `stall`, `reset` and any `unit_ready_<kind>`.

Output ports: `result`, `ready`, `done`, `fault`, and any `unit_active_<kind>`.

* `reset`: synchronous, active high, dominates stall, clears all internal data registers and scratchpad, sets `ready=1`, clears `done/fault`.
* `start`: accepted on a rising edge when `ready=1`, `stall=0` and `reset=0`. Original function inputs are captured at that edge and may change while BUSY.
* Selected CFG instructions execute in program order; the nonselected branch is not speculatively executed, including memory operations.
* `stall=1`: freezes all internal registers until deasserted. `done` consequently remains asserted through a stall at the terminal state; the transaction protocol is defined in *unstalled* clocks.
* `unit_ready_X=0`: blocks completion at the final reserved cycle of a corresponding X instruction. The controller retains that state. Values remain internal gate-level signals.
* `done`: asserted after the RETURN or faulting memory edge; `ready=1` at that point. `result` is stable until a subsequent successful RETURN or RESET.
* `fault`: asserted for an out-of-bounds on-chip memory access. Earlier completed memory writes are retained; no transaction rollback is implied.

### Supported source

- Unsigned annotated function parameters and return (`bool`, `u1..u128`).
- Constant unsigned integer expressions; local assignments and annotated local values, return.
- Addition, subtraction, multiplication, bitwise AND/OR/XOR/NOT, unsigned NEG, comparisons, boolean AND/OR and conditional expressions (equal-width pure branches).
- `if`/`else`, early returns, bounded `for i in range(constants)` unrolled up to 32 iterations.
- `mem_read(address)` and standalone `mem_write(address, value)` with declared on-chip memory.
- Operations can be nested; each arithmetic/comparison creates an instruction dependency and state register.

Unsupported syntax/semantics are rejected with a source/CO error: unbounded `while`, functions/helpers in this mode, signed types, arbitrary casts/pointers, dynamic array objects, over-width expressions, ambiguous implicit local retyping, unbounded memory, speculative side effects in short-circuit operands, async transfer protocols. C/C++ support is limited to the existing C-compatible translator that produces this subset.

### Evidence and debugging

- `build/latest/<top>.dls`: actual primitive gate network, state and metadata.
- `build/latest/co_schedule.json`: instruction indices, source lines, result widths, resource bindings, latencies, memory configuration, supported protocol.
- `build/latest/equivalence.json`: independent AST source interpreter versus gate-level DLS simulator, with sampled stalls/ready delays, varying live inputs, scratchpad state and out-of-bounds faults.
- When the generated circuit is corrupted, `VERIFY.CFG_MISMATCH` includes a deterministic source vector and a bounded execution trace of active instruction indices, operation names, clock phases and source lines.
- `build/latest/<top>.v`: structural Verilog for the same gate-level DLS. `verification.external_rtl: true` now generates a scheduled Icarus testbench and **requires actual Icarus execution** before marking RTL checks as passed.
- The test suite is not formal equivalence. Production requires independent Verilog simulation/formal properties and downstream technology-qualified checks.

### Fair arbitration between concurrently requesting clients

`chipcompiler.arbitration.round_robin_arbiter(n, payload_width)` generates DLS and structural Verilog with `request_i`, `payload_i`, `resource_ready`, `stall`, `reset`, `grant_i`, `resource_valid`, `selected_payload`, and `selected_client` ports. Clients must hold request/payload stable under backpressure. It is also available as an MCD.network primitive:

```yaml
network:
  instances:
    - name: bus_arbiter
      primitive: round_robin_arbiter
      clients: 2
      payload_width: 8
      inputs:
        request_0: producer0.request
        request_1: producer1.request
        payload_0: producer0.result
        payload_1: producer1.result
        resource_ready: ready
        stall: stall
        reset: reset
```

The complete MCD network still requires explicit output mappings and an independent behavioral reference matching the intended stateful arbitration semantics. This does not yet synthesize arbitrary cross-module requests and buffers automatically.
