# MCD module networks (v0.6)

## What this implements

`MCD.network` is an **optional, real hardware implementation** of the named behavioral source `top`. The source top is the independent reference: its gates are not used by the network implementation. Individual `network.instances` are compiled into executable gate-level child DLS modules, wired with bit-exact named buses, topologically ordered, saved, simulated, checked against the behavioral source, and exported as hierarchical structural Verilog. Clocked children have per-instance state and share one implicit rising-edge clock.

```
top: calculate
modules:
  - {name: Adder, function: add}
  - {name: Multiplier, function: mul}
network:
  instances:
    - {name: sum, function: add}
    - {name: product, function: mul}
    - name: selector
      function: choose_result
      inputs:
        sum_value: sum.result
        product: product.result
  outputs:
    result: selector.result
```

`sum.a` and `sum.b` can connect automatically to top inputs `a` and `b`, because their names match exactly. `network.inputs` is not used; top inputs/outputs are derived from the type-checked source `top` function. The network must explicitly map *all* top outputs, preventing silent missing pins.

If `network.auto_connect: unique_width` is specified, each otherwise-unconnected child input is matched with a **single** compatible output bus by matching the required width. If several candidate output ports have the same width, the compiler rejects that connection with `MCD.NETWORK.AMBIGUOUS_AUTO`. These inferred connections are **warning-level design decisions**, recorded with origin and destination in `network_connections.json`; bit-width matching is not a proof of intended functionality. Source-versus-DLS checking is still mandatory. `auto_connect: top_only` is the default.

Legal references include `a`, `top.a`, `sum.result`, `sum.result[3:0]`, `sum.result[0]`. Literal bus sources must specify both width and value, e.g. `{const: 0, width: 4}`. Width extension/truncation, multi-driver resolution, and operand arbitration are **not** silently inferred. Names are case-sensitive. Combinational instance-dependency cycles are rejected. An inferred connection that forms a cycle is rejected too. The compiler supports at most 128 instances in this pass.

Unknown network fields, unknown instance fields, unknown ports/functions, width errors, disconnected inputs, invalid slices, invalid constants, and missing outputs generate MCD-origin diagnostics. Independent errors in one network are collected together as far as possible; downstream generation/equivalence is marked `BLOCKED` if the network fails. `network.connections` in DLS metadata records all successful connections. `architecture.json` includes network instance dependencies and statically expanded requirement counts.

`CO.modules.naming: mcd` and `hierarchy: preserve` can still assign names to generated child definitions. An explicit MCD network itself preserves instance hierarchy regardless of default module hierarchy. Time-sharing and automatic pipelining across an explicit MCD network are rejected as `MCD.NETWORK_SCHEDULE_CONFLICT` because retiming/binding across instances is not implemented.

## Limits

- No multi-clock interfaces, bus transactions, asynchronous reset, or memory protocol generation.
- No automatic inter-module arbitration. Same-width port inference is optional; it does **not** discover semantics or select the physically optimal architecture.
- No general resource-sharing or physical-routing optimization across explicit instance boundaries.
- No partial width resize except explicit contiguous bus slicing. No concatenation or dynamic-indexed wiring.
- The synthesis and physical EDA toolchain remains separate and requires installation, verified libraries, and a suitable PDK.

See `examples/explicit_network` for a self-contained tested arithmetic project and `tests/test_iteration6.py` for negative and sequential cases.
