# PICADS v0.15.0 — source-only chip component

## Intended hardware

One four-bit ALU slice for a hypothetical small digital processor. This is **one component**, not a complete processor or accelerator. It contains no register file, decoder, datapath controller, instruction fetch, power network, or I/O pads. Those are intentionally **not** prebuilt. The point of the test is to determine whether PICADS can turn an ordinary supported source-level logic description into DLS, Verilog and (with a supported external EDA stack) placed/routed silicon layers.

## Files supplied

`examples/alu_slice_component/` contains exactly:

- `circuit.py` — typed behavioral logic; no gates drawn by hand
- `chip.yaml` — source path and verification/physical settings; physical disabled by default
- `design.mcd` — one named logical module and typed ports
- `architecture.co` — spatial scheduling and ripple-adder strategy

There is **no hand-authored Verilog, GDS, LEF, Liberty, placement file, or mask**. DLS and Verilog must be emitted by PICADS. GDS must only originate from an actual successful external physical implementation.

## Logical contract

`alu_slice(a: u4, b: u4, op: u2) -> u5`

| `op` | Function | Observable result |
|---|---|---|
| 0 | `a + b` | 5-bit sum, preserving carry (0..30) |
| 1 | `a - b` | **4-bit wrapping subtraction**, zero-extended to 5 bits |
| 2 | `a & b` | 4-bit AND, zero-extended to 5 bits |
| 3 | `a ^ b` | 4-bit XOR, zero-extended to 5 bits |

The subtraction-width rule is a deliberate part of the test specification. This is *not* a signed ALU and it does not output a separate carry or overflow flag.

`16 × 16 × 4 = 1,024` combinations are compared both by the existing source interpreter and by an independently written test oracle (`tests/test_iteration15.py`). Mutation tests replace output wiring with a hardwired constant to verify that the separate oracle catches the error.

## Test manually through the GUI after the automatic suite

1. Open `examples/alu_slice_component` in PICADS.
2. Click **Generate DLS**. Look at the gate graph, build stages, errors and generated Verilog.
3. Go to **Simulate / Debug**. Enter `{"a":15,"b":1,"op":0}`; observe `result=16`.
4. Enter `{"a":0,"b":1,"op":1}`; observe `result=15`.
5. If you have configured a real Yosys/LibreLane/PDK environment, enable `physical.enabled` for a **copy** of the example and run the physical flow. A generated GDSII is only a preliminary layout artifact, **not a mask accepted for manufacturing**.

Do not modify a project's original working files for the automated suite: it uses temporary copies.

## Automated verification

`RUN_PICADS_AUTOTEST.bat` verifies the CLI, logic, waveform generation, GUI workflows when PySide6 is installed, and native synthesis/layout where available. `--full-regression` adds all legacy Python test files; it can take significantly longer. You can supply `--pdk` and `--pdk-root` to select a process for the native physical acceptance stage.

The independent native RTL comparison is sampled rather than formal proof, and physical signoff requires the qualified rules for the selected PDK.
