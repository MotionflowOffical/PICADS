# Scheduling and hierarchy language — v0.3.0

## Combinational flattening (default)

An MCD module's `function` optionally binds it to a source function. Unless CO changes hierarchy, helper calls are flattened into the top gate-level DLS.

## Preserved hierarchy

```yaml
modules:
  hierarchy: preserve
```

The generated DLS v2 includes `submodules` and ordered `instances`. Each child has independently compiled primitive gates. Verilog declares child RTL modules and wires port buses into instances. Only combinational children are currently supported, and child-internal helpers are flattened. An incompatible stateful child is an explicit error.

## Spatial pipelining

```yaml
schedule:
  pipeline_stages: 3
```

The generated top has an implicit `clk` clock port in RTL and an `input_valid` input and `valid` output in DLS/RTL. With `N` stages, the input sample is available after N rising edges; initiation interval is one clock. Each stage has actual registers for signals crossing boundaries. Current implementation only pipelines state-free flattened gate graphs. It does *not* reduce physical operator counts.

## Time-multiplexed scheduling

```yaml
schedule:
  mode: time_share
allocation:
  max_instances:
    ADD: 1
    MUL: 1
```

A statically scheduled combinational function is transformed into a **clocked single-transaction engine**:

1. Present source inputs, raise `start` only when `ready` is high.
2. On that rising clock edge, input registers sample the operands and leave the idle state.
3. The generated FSM executes operations on allocated physical arithmetic units over multiple cycles.
4. Intermediate results are saved in explicit registers. A unit may service multiple source operations at different cycles.
5. At the commit edge, `result` updates, `done` pulses and `ready` returns high.

For `E` execution cycles, from the accepting edge through the commit edge (inclusive) there are `E+2` rising edges. Do not assert `start` while busy; those requests are ignored. Throughput is one transaction every `E+2` clocks, not a pipeline. `done` is a one-cycle pulse; `result` retains its last committed value between transactions. Input changing while busy must not affect the accepted transaction.

This mode supports a restricted subset: straight-line pure unsigned arithmetic `+ - * & | ^`, source-local simple assignments, integer literals and signedness-free fixed-width integer input/output. Conditional branches, dynamic indexing, memories, loops, stateful helpers and signed arithmetic are not synthesized by this mode. Unsupported input fails with a precise diagnostic. Source-to-DLS verification is transaction-sampled and is not a formal proof.

## Incompatible options

`hierarchy: preserve` cannot be used with either automatic pipelining or time-share mode yet. Invalid combinations fail at CO validation and do not silently flatten modules.
