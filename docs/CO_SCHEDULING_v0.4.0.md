# MCD/CO and executable scheduling — v0.4.0

## MCD functional requirements

```yaml
top: top
modules:
  - name: FastAdder
    function: add
    inputs: {a: 8, b: 8}
    outputs: {result: 9}
requires:
  - {module: FastAdder, min_instances: 2}
```

`requires` validates that bound source functions are present and occur at least the specified number of statically expanded **reachable callsites**. It does *not* insert missing calls or allocate new physical resources. Unknown, unreachable and insufficient capabilities produce separate MCD diagnostics.

## Hierarchical implementation

```yaml
modules:
  hierarchy: preserve
  naming: mcd   # optional; 'function' remains the default
```

Pure nested helpers become actual DLS child modules and RTL instances. The optional naming mode labels non-top hardware with the declared MCD module `name`. Duplicate hardware module names are refused. Stateful children and general cross-module resource arbitration are not supported.

Resource limits are enforced against **all** instantiated source arithmetic operators in preserved hierarchy, so two instances of a child module count twice. No sharing across instances is implied.

## Time-multiplexed datapath

```yaml
schedule:
  mode: time_share
allocation:
  max_instances:
    ADD: 1
    MUL: 1
```

Supported source: pure unsigned fixed-width arithmetic `+ - * & | ^`, local assignments, literal constants, terminal `if/else` returning values, `if-return` followed by `return`, expression ternaries, basic comparisons and `not`, and literal bounded `for i in range(...)` with assignment-only bodies.

A terminal branch is currently implemented by **speculatively computing both pure possibilities** and selecting the result using transaction-captured input/derived condition. It is NOT true path-selective scheduling. Side effects, stateful helpers, arbitrary loops/branches, stalls and overlapping transactions are rejected.

Statically expanded loops permit at most 32 iterations per loop, 64 combined and 8 levels. A variable `range` argument is an error. The bounded expansion respects source-defined fixed-width casts.

The controller samples operands on a START/READY edge, executes the scheduled operations on shared units, commits the result, pulses DONE and returns to READY. All outputs are obtained by running the same generated primitive-gate DLS that is exported as RTL. Time-share verification is transaction-sampled (not formally exhaustive).

## GDS geometry preview

```bash
chipcompiler render-mask design.gds --output preview.svg --top TOP --max-shapes 20000
```

A read-only view of **actual file geometry**. It is a partial viewer, not full design-rule or timing verification. `PARTIAL` status or process exit code 2 means something was deliberately omitted or clipped, and its warning identifies what. Use KLayout/physical-flow tools for complete layout analysis and signoff.
