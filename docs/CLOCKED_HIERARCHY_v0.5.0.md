# Clocked hierarchy implementation — v0.5.0

## Contract

The procedural source may include helpers using `reg("name", expression, init=<constant>)` and can preserve their hierarchy with:

```yaml
modules:
  hierarchy: preserve
  naming: mcd
```

A DLS module's `requires_clock()` is true if the module **or any descendant** contains registers. Structural Verilog exposes one implicit rising-edge `clk` port on each such module, forwarding it to each child requiring a clock. Pure modules do not acquire an unnecessary clock unless they wrap a stateful descendant.

Each child instance owns a separate `DLSSimulator`, not a newly initialized instance per evaluation. On `step(inputs, clock=False)`, every child is evaluated using current state but no register is advanced. On `step(inputs, clock=True)`, children and the top advance together using their pre-edge combinational values. Returned values are pre-edge outputs (inspect the post-edge state with another `clock=False` evaluation). The source-reference evaluator now keys register identity by hierarchical call-site, rather than only by the register's textual name.

`sim.register_snapshot()` returns a mapping such as `top/u_000000/r_q -> 7` and `top/u_000001/r_q -> 2`. The GUI simulation result includes these paths; VCD exports child registers under `state_top__u_...__r_...` signal names, while root registers retain their previous `reg_<name>` names.

## Correctness guardrails

Pure `if/else` lowering evaluates both result networks and selects one. That is not equivalent to conditionally invoking a stateful module. Until clock enables and dynamic guarded schedules are supported, registers under conditional branches are rejected. Similarly, stateful calls in later short-circuit Boolean operands are refused, because gate-level Boolean lowering does not preserve Python's evaluation side effects.

A source input named `clk` on a clocked hierarchy is rejected. It cannot shadow the generated implicit clock. An ordinary combinational input named `clk` remains supported; VCD instead uses `chipcompiler_cycle_clock` for the virtual sampling tick.

## Out of scope

- Multiple clock domains, asynchronous reset, arbitrary clock enables and stalls
- Procedural register updates under dynamic branches
- Stateful cross-module resource sharing and arbitration
- Sequential formal equivalence for all reachable states
- Real Verilog execution, Yosys synthesis or physical timing in this build environment
- Manufacturing masks and PDK signoff

Run `python -m chipcompiler compile examples/clocked_hierarchy` after package installation, or `PYTHONPATH=src python -m chipcompiler compile examples/clocked_hierarchy` from the unpacked source on Unix.
