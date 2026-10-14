# Chip Compiler languages and actual semantics

> **Current authoring guide:** For a PICADS-wide explanation of Python, restricted C/C++, MCD, CO, Verilog macros, DLS, generated physical files, and how to choose among them, read [Programming languages and design-file contract](PROGRAMMING_LANGUAGES_AND_DESIGN_FILES.md) and [Practical authoring workflow](PICADS_LANGUAGE_AUTHORING_WORKFLOW.md). This older page retains historical subset details; r9d adds a separate CO-selected RTL macro path.


`chip.yaml` selects the source and optional module (`.mcd`) / architecture (`.co`) YAML files. The generated `.dls` file is a versioned JSON description of **actual primitive gates and state**, not opaque math operators.

## Editable MCD (Module and Chip Description)

```yaml
top: calculate
modules:
  - name: arithmetic
    function: calculate        # optional: bind to a real, typed function
    purpose: Conditional arithmetic
```

A declared `function:` is required to exist in the behavioral source. Reachable non-top source helpers are also independently generated and verified as candidate modules. Unbound descriptive names are explicitly reported as descriptive-only. All physical connections in the top-level Verilog remain flattened; this is **not yet** hierarchical physical module routing.

## CO (Chip Orchestration) actually implemented

```yaml
architecture:
  adder: auto                 # auto, prefix, ripple
allocation:
  sharing: force             # off, auto, force
  max_instances:
    ADD: 1
    MUL: 1
```

`sharing` moves a selection MUX before one combinational ADD/SUB/MUL/AND/OR/XOR operator when both alternatives are compatible pure binary expressions with simple inputs and identical operand types. `auto` avoids sharing small ADD/SUB operations when not expected to improve area. `max_instances` counts recognized source-level operators after supported sharing; an impossible limit is an ERROR. Advanced multi-cycle scheduling and arbitrary graph-wide routing are unsupported; unknown configuration keys are not secretly executed.

## Python source subset

`u1..u4096`, `s1..s4096`, and `bool`; constants; typed `def` with typed inputs and return; simple assignments; `if` / ternary; bounded `for range(...)`; helper functions; bitwise/arithmetics; constant shifts; comparisons; `reg('name', signal, init=...)` for synchronous stored state.

Addition widens by one bit; multiplication width is the sum of operands; subtraction wraps to max operand width. Final return width is explicitly applied. These are hardware bitvector rules, not arbitrary Python semantics. Unsupported imports, dynamic shifts, dynamic allocation, objects and system calls fail explicitly.

## C / C++-compatible subset

Accepted filenames: `.c`, `.cpp`, `.cc`, `.cxx`. `pycparser` analyzes fixed-width, pure-function scalar C syntax. C++ features beyond C-compatible syntax are **not** accepted; unsupported constructs emit `C.*` errors. Supports `uint8_t`, `uint16_t`, `uint32_t`, `uint64_t`, corresponding `int*_t`, `bool`, selected conventional integer declarations; local initialized scalar variables, simple assignments, comparisons, arithmetic and bitwise operators, conditions, pure calls and literal-bounded `for` loops. Only `stdint.h` and `stdbool.h` includes are recognized. No pointers, arrays, globals, casts, dynamic memory, `while`, data structures, preprocessor macros or classes.

Normalization is saved to `build/latest/normalized_source.py`, with best-effort source-statement location mapping back to the original file. **Arithmetic uses Chip Compiler's bitvector semantics, not ISO C's integer promotions or undefined behavior rules.** `verification.native_c: true` enables an independent GCC/G++ comparison with the original source for bounded vectors, if available.

## DLS

A serialized `.dls` includes named input buses; output wire mappings; primitive AND/OR/XOR/NAND/NOR/XNOR/NOT/BUF/MUX gates in execution order; register banks with next-state wires and initialization; origin and architecture metadata. DLS simulation and structural Verilog consume the same graph.

## Physical exports

`compile` produces DLS + `.v` + equivalence/architecture data. `build` attempts Yosys. `physical` attempts LibreLane only when explicitly configured; it reports recognized real GDS and metrics, and explicitly leaves independent mask signoff unverified.


## v0.5 sequential hierarchy

With `modules.hierarchy: preserve`, pure helper calls can instantiate nested modules containing `reg("name", next_value, init=0)`. Every instance maintains **independent** register storage. The top module and all intervening wrappers expose one **implicit rising-edge `clk`** Verilog port if any descendant requires a clock. `clk` must not also be used as a source data input.

This is single-clock synchronous hierarchy, not full RTL: no explicit asynchronous reset, independent child clocks, clock enables, memories, or automatically gated conditional registers. Registers observe pre-edge input values; the DLS interpreter advances state on `step(..., clock=True)` and returns pre-edge outputs. `step(..., clock=False)` observes state without clocking it. The source-reference interpreter uses physical call-site scopes so same-named registers in two child instances do not alias.

Conditional branches containing stateful effects are rejected as `SOURCE.CONDITIONAL_STATE`, and short-circuit Boolean operands containing stateful calls are rejected as `SOURCE.SHORTCIRCUIT_STATE`. Combinational condition selection feeding an unconditional register is supported.

## v0.6 additional implemented constructs

The source register primitive now supports `reg("q", value, init=0, enable=enable_bit, reset=reset_bit)`. Reset is **synchronous** and has precedence over the enable signal. Each named register is instantiated only once per module; independent hierarchical module instances retain independent state. The source-reference interpreter implements the same temporal contract separately from gate-level DLS. Unknown/duplicate register declarations receive SOURCE-origin diagnostics.

`MCD.network` is an optional actual hierarchical implementation of the source top rather than a descriptive list. See [MCD network documentation](MCD_NETWORK_v0.6.0.md). Its opt-in `auto_connect: unique_width` heuristic requires unique candidate producers and produces a warning when used. CO scheduling across explicit networks remains unsupported and is rejected.

Optional real RTL sampled execution checking (`verification.external_rtl: true`) is described in [RTL check](RTL_CHECK_v0.6.0.md). Only one implicit synchronous clock is currently modeled.
