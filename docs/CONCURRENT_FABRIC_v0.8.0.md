# CO concurrent resource fabric — v0.8.0

## What was implemented

`schedule.mode: concurrent_fabric` builds an executable gate-level DLS component with **two concurrent service domains**, one single-owner shared arithmetic operator, and one shared register-bank memory port. Between 2 and 8 independently requesting clients each have one request slot, one active-ownership bit and one held response slot. Every selection, buffer, register and data path is actual primitive DLS logic and can be exported as structural Verilog.

This is **not** automatic compilation of arbitrary independently executing source functions. It is a reusable, bounded service/control fabric. The current implementation does not automatically discover and connect the generated interface to arbitrary MCD producer functions; the client request/response ports must be connected by the surrounding design. The older transactional CFG compiler remains available and limited to one transaction.

### Example CO

```yaml
schedule:
  mode: concurrent_fabric
fabric:
  clients: 3
  width: 4
  depth: 4
  operator: builtin  # or external
```

Configure `top: SharedFabric` in the MCD file. `descriptor.py` in the example exists only to meet the current project-file interface; its contents are **not** a behavioral reference. The build explicitly records `equivalence: NOT_APPLICABLE`, then runs independent protocol checks and a randomized transaction/memory scoreboard. Fabric name, client count and widths must be legal; unknown directives cause CO errors.

### Client ports

For every client `i`:

| Port | Direction | Meaning |
| --- | --- | --- |
| `request_i` | In, 1 bit | Request valid; inputs sampled only when `request_ready_i` is high |
| `opcode_i` | In, 2 bits | 0 ADD; 1 MUL; 2 READ; 3 WRITE |
| `a_i`, `b_i` | In, WIDTH bits | ALU operands or memory address / write data |
| `request_ready_i` | Out | One request slot is available (not pending, active or awaiting response consumption) |
| `response_ready_i` | In | Consumer may accept held response |
| `response_valid_i` | Out | A response is available until a rising-edge `response_ready_i` handshake |
| `response_data_i`, `response_fault_i` | Out | Data and invalid memory address flag |
| `pending_i`, `active_i` | Out | Debug state, not additional protocol guarantees |
| `request_accepted_i`, `response_accepted_i` | Out | Combinational handshake event observability |
| `operator_grant_i`, `memory_grant_i` | Out | Arbitration grant accepted on current rising edge |

Global inputs: `stall`, `reset`, with an implicit rising-edge `clk`. `reset` is synchronous, active-high, clears the entire controller, all outstanding responses, pointers, and all on-chip memory words. An external operator needs to be reset/flushed in lockstep; the untagged interface cannot distinguish a stale external response received after reset from the response to a new request.

### Arithmetic operator

Both ADD and MUL are supported and results truncate modulo `2**WIDTH`, as specified by the width. The internal implementation is algorithmically lowered into primitive gates; there is no predefined arithmetic cell. `operator: builtin` registers the output of combinational arithmetic and returns it on a later rising edge. This is **not an accurately characterized iterative arithmetic pipeline**.

`operator: external` exposes:

- Inputs: `operator_request_ready`, `operator_response_valid`, `operator_response_data[WIDTH-1:0]`.
- Outputs: `operator_request_valid`, `operator_request_opcode[1:0]`, `operator_request_a[WIDTH-1:0]`, `operator_request_b[WIDTH-1:0]`, `operator_response_ready`, `operator_reset`, `operator_unsolicited_response` (debug violation indicator).

A single request is issued to the external operator only on `request_valid && request_ready && !stall && !reset`. The arbiter latches its selected client's identity and keeps the offered payload stable under ordinary ready backpressure. The operator may take an arbitrary number of cycles to assert `response_valid`. The returned value is captured only on `response_valid && response_ready && !stall && !reset`; the fabric then holds that client's response until consumed. No uncharacterized wait counter pretends to implement external operator latency.

**Important protocol contract:** `stall` synchronously suppresses both external handshake signals. External logic must obey the same stall/reset domain; an external operator that ignores global stall can violate the handshake. The current interface has no transaction tags, timeout, or clock-domain crossing logic.

### Memory coordination and fairness

All clients share a single on-chip synchronous register-bank memory port. A READ or WRITE is selected using a one-hot round-robin pointer, and at most one memory operation is committed on each rising edge. Invalid addresses produce `response_fault=1`; no memory word is modified. WRITE returns zero on success, READ returns the selected current word. The ALU's separate arbitration pointer allows it to be busy while a memory operation commits. Response backpressure keeps completed responses in each client's individual response register.

The local memory has `depth=1..32` words, WIDTH bits per word. This is **not** an external RAM, DRAM, DMA, cache coherence, a multi-port SRAM compiler, or a memory-ordering system for multiple dependent transactions in the same client.

### Verified here vs. remaining

- Directed executable DLS checks: simultaneous pending requests, response backpressure, memory read-after-write, fault, stall, reset and external ready/valid completion.
- Random independent scoreboard: three fixed seeds, 160 cycles per seed, actual grant-based memory-order prediction, delayed external operator responses, one-hot resource checks, and register-freeze verification.
- Mutation check: deliberately wrong output wiring causes deterministic failure with a bounded input replay trace.
- DLS roundtrip and structural Verilog generation: exercised by tests.
- **Not verified locally:** actual Icarus/Verilator execution or Yosys/LibreLane, physical timing or signoff. `RUN_FULL_VALIDATION.bat` performs the available real-tool checks on the user's machine and packages the results.

## Known important gaps

- True general-purpose concurrent HLS compiler that automatically schedules multiple independent source programs and allocates resources across arbitrary hierarchical MCD modules.
- Multiple outstanding requests from the *same client*, tags/reordering, simultaneous multi-port memory operations, external memory wait states, variable-latency resource pools, CDC, asynchronous reset and reset flushing of third-party IP.
- Scheduling optimized against timing, power, area and a characterized custom transistor process; general formal proof and fabrication signoff.
