# PICADS v0.9.0 — Tagged scheduling and external memory contracts

## Architecture and scope

`src/chipcompiler/tagged.py` implements a synthesizable tagged adapter around the existing clocked `concurrent_fabric` shared-resource core. Each of the N external clients owns S independent virtual transaction slots. The core sees N × S ordinary hardware clients and performs independent round-robin arbitration for the ALU and memory domains. The wrapper retains an explicit register for slot occupancy, client-owned tags, output selection, and response round-robin state. The complete wrapper is executable DLS and exportable structural Verilog.

Configuration limits: N=2..8, S=1..4, N×S≤8, data width=1..16, tag width=1..16, memory depth=1..32. One request may be accepted per physical client per cycle; each client can have S requests outstanding. The physical ALU and memory interfaces each accept one outstanding downstream transaction at a time. Concurrent ALU and memory requests may proceed independently. These bounds are implementation limits, not fundamental architectural requirements.

### Client interface

Inputs: `request_i`, `request_tag_i`, `opcode_i` (except source-bound mode), `a_i`, `b_i`, `response_ready_i`. Outputs: `request_ready_i`, `request_accepted_i`, `duplicate_tag_i`, `outstanding_i`, `response_valid_i`, `response_tag_i`, `response_data_i`, `response_fault_i`, `response_accepted_i`. Global inputs: `reset`, `stall`.

Opcodes: 0 ADD, 1 MUL, 2 READ, 3 WRITE. Arithmetic outputs are truncated modulo 2^width. Memory address uses operand `a`; write data uses `b`. Built-in memory read returns stored data, write acknowledges with zero, invalid addresses report fault. External memory returns data and fault directly from the memory device.

Request handshake occurs on `request_i && request_ready_i` at a rising edge; the accepted tag is reserved until its final output response is consumed. A second outstanding request with the same tag **for the same client** is rejected. Different clients can reuse the same tag. The wrapper selects a completed response via a sticky, registered lock. Once `response_valid_i` is asserted it holds `response_tag_i`, `response_data_i`, and `response_fault_i` until `response_ready_i` handshakes. Response order can differ from submission order, so consumers must use tags.

Reset is synchronous, clears controller state and the built-in memory/register bank; external devices must honor their matching reset signals. Stall freezes internal state and suppresses request/response handshakes. Neither mechanism substitutes for hardware characterization.

## Automatic MCD client binding

Set `schedule.mode: bound_fabric`; provide an MCD `concurrent_clients` mapping with one entry per client. PICADS parses each mapped function and validates its exact two-input `uN -> uN` signature, a single stateless return and either `a+b` or `a*b`. For each client, the service's two-bit opcode bus is **physically tied** to that function's inferred operator, and the generator exposes the tagged handshake/bus interface. There are no handwritten opcodes in the bound module.

**Excluded:** source state, conditionals, loops, source memory operations, multiple instructions in the function, arbitrary concurrent kernels, automatic global resource scheduling across separate source processes, and distributed caches. Such code is rejected, not silently approximated. `bound_fabric` supports the same shared ALU but does not promise source-to-DLS whole-program equivalence; its source binding is validated structurally and its runtime is checked by independent transaction scoreboards.

## External memory ready/valid contract

Select `fabric.memory_backend: external`. The shared core emits:

- `memory_request_valid`, `memory_request_write`, `memory_request_address`, `memory_request_data`.
- Inputs: `memory_request_ready`, `memory_response_valid`, `memory_response_data`, `memory_response_fault`.
- `memory_response_ready`, `memory_busy`, `memory_reset`, `memory_unsolicited_response` debug outputs.

The memory port locks a selected offer until request-ready handshakes, then retains an owner and active flag until a later response-valid/response-ready handshake. Only one downstream memory request may be outstanding. The response is delivered to the originating virtual slot and then tagged for the originating external client. A different client may issue an ALU operation at the same time. The memory device is authoritative for actual storage and address faults. PICADS does **not** shadow external memory data.

The protocol is not AXI4, AXI-Lite, TileLink, Wishbone, cache-coherent memory, multi-beat burst transfer, transaction-ID multiplexing on the memory bus, or an asynchronous CDC bridge. There is no guarantee of progress if the external device never returns a response. Memory-port physical timing remains uncharacterized.

## Independent checks and formal collateral

- `tagged_verify.py`: independent arithmetic-by-(client,tag) scoreboard with random request stream, duplicate-tag attempts, stalls, resets, external variable ALU delays, and response-hold checks. Reports reproducible trace on failure.
- `memory_verify.py`: independently simulated variable-latency external memory device exercising write/read/fault, backpressure, response holding, competing clients and owner routing.
- `rtl_check.py`: optional Icarus Verilog testbench compares exported RTL to executable DLS for the same stimulus. This is sampled RTL-vs-DLS verification, **not formal proof**.
- `formal.py`: creates `safety.sby` and an SV harness for SymbiYosys+Yosys+Z3 bounded safety properties: request/response handshake consistency, duplicate-tag blocking, payload hold under output backpressure, and stall occupancy stability. Generation is marked `GENERATED_UNVERIFIED`; actual SBY execution is marked PASS only if tools run successfully.

Formal harness assertions are **bounded** to configured depth and only cover the listed properties and reset assumptions; no liveness, memory-value equivalence, unbounded correctness, physical timing, RTL-to-netlist mapping correctness or manufacturing signoff is claimed.

## One-command machine verification

On Windows, run `RUN_FULL_VALIDATION.bat`. The output ZIP contains stage statuses, regression logs, source-bound example build evidence, core/queued fabric protocol check results, optional Icarus results, optional SymbiYosys evidence, Yosys probe and physical-flow evidence if a real PDK project is explicitly provided. Missing tools must remain `UNAVAILABLE`.

For a real physical project, pass `--physical-project <project-directory>` to the batch file. The runner copies the source project to a temporary location. It does not alter the original source or declare foundry signoff passed.
