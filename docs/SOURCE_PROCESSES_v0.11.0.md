# PICADS v0.11 — parallel source-defined processes

`source_processes` is a deliberately bounded next step toward concurrent synthesis. It compiles **several typed source functions** to separate clocked DLS instances. Every instance uses the proven transactional compiler's guarded control-flow FSM, sampled operands, optional private on-chip RAM, stall control and operation-ready inputs.

## Example

`architecture.co`:

```yaml
schedule:
  mode: source_processes
  latencies:
    MUL: 2
  ready_types: [MUL]
```

`design.mcd`:

```yaml
top: ParallelExample
concurrent_clients:
  - name: lane0
    function: calculate
  - name: lane1
    function: calculate
  - name: lane2
    function: alternate
```

`processes.py`:

```python
def calculate(a: u4, b: u4, choose: bool) -> u8:
    if choose:
        value: u8 = a * b
    else:
        value: u8 = a + b
    return value

def alternate(a: u4, b: u4) -> u8:
    result: u8 = a + b
    result = result + a
    return result
```

Compile: `python -m picads compile examples/source_processes`.

Each process exposes its named transaction ports (`lane0_start`, `lane0_ready`, `lane0_done`, `lane0_result`, `lane0_stall`, `lane0_a`, etc.). `reset` is the common synchronous active-high reset. Input operands are sampled when START is accepted. Multiple lanes can be active simultaneously; repeatedly instantiated copies of the same function have **independent state**.

## Verification

`process_verification.json` records per-child sampled source-to-DLS equivalence and a simultaneous multi-lane state-isolation test. A failing equivalence test blocks RTL export. The parent exports the child modules only once in RTL; each instance retains its own registers.

## Distinctions from general HLS

- Arithmetic and memory in different lanes are **not automatically shared**. Every lane has its own functional units and (when requested) **private** local register-bank memory.
- There is no implicit inter-process message passing, shared memory, data-dependent process spawning, scheduling across mutually dependent source functions, or dynamic queues.
- The accepted language is the transactional compiler's restricted, typed, unsigned Python/C-compatible subset, not arbitrary Python or C++.
- One transaction per lane may execute at once, while separate lanes operate concurrently.
- Memory capacity remains the transactional compiler's bounded register-bank limits.
- This does not yet integrate source-process FSMs as tagged requesters of the global shared-resource fabric; that remains the main concurrent compiler task.
