# HELIOS-16 — 2003-inspired 130 nm embedded RISC demonstration

**A demonstrator, not a taped-out commercially manufacturable chip.**

- 16-bit, single-issue load/store instruction set; 8 architectural registers (R0 constant zero).
- 16-bit ALU: add, subtract, AND, OR, XOR, shift, compare.
- 128 x 16-bit programmable instruction store, 64 x 16-bit data scratchpad.
- Memory-mapped-style GPIO (8 outputs), UART transmitter (8N1 ~9600 baud at 10 MHz), timer interrupt.
- Program counter, relative branches/jumps, IRQ vector 0x0060 and return from interrupt.
- Built for a nominal **10 MHz** clock / **100 ns** timing constraint using the open SKY130 PDK.
- Six **actual RTL hard-macro blocks** defined in `architecture.co`.
- CO-defined compact/manual placement area, mandatory stay-out and 6 um keepout halo.
- ABC AIG export is enabled (independent study artifact, not technology-mapped netlist).

## Why this resembles a circa-2003 embedded chip

Period-plausible 16-bit RISC control/data path, internal RAM and timer/UART/GPIO peripherals, but simplified
execution pipeline and bus. A real production 130 nm MCU generally used embedded flash/ROM/SRAM macros,
I/O pad cells, tested clock/reset trees, ESD protection, analog support and signoff. Here, program and data
storage are synthesized from standard-cell flip-flops for reproducibility without proprietary memory IP.
This is especially area-inefficient and takes longer to route than a true SRAM macro.

## GUI workflow

1. Open the folder in PICADS r9d+ (no BAT files needed).
2. **Start Docker Desktop** and enable Settings > Resources > WSL Integration > Ubuntu.
3. Edit placement using Physical / Masks → **Edit CO Floorplan (Drag and Drop)**. The cyan region is the
   legal placement area; the red rectangle is a mandatory CO stay-out with an additional halo.
   The editor blocks illegal movement as you drag, rather than only rejecting on release.
4. Save positions to CO, then Generate Physical Layout. Use Verify Existing Layout for DRC/LVS/XOR.
5. Test RTL using an external simulator, e.g. `iverilog -g2012 -s helios16_tb -o sim rtl/*.v && vvp sim`.

`circuit.py` is only a Python reference for a subset of the ALU. **It is not the CPU source**, and PICADS
cannot currently prove equivalence between it and the modular RTL. The CPU resides in `rtl/helios16_*.v`.

## Instruction word

- bits `[15:12]`: opcode
- bits `[11:9]`: destination/source register index
- bits `[8:6]`: first source register
- bits `[5:3]`: second source register (ALU); alternatively `[5:0]` immediate offset
- `1..6`: arithmetic/logic; `7`: MOVI signed imm9; `8`: load; `9`: store; `A`: BEQ; `B`: relative jump;
  `C`: load upper immediate; `D`: interrupts EI/DI/RETI; `E`: I/O write; `F`: halt.

`rtl/helios16_tb.v` includes a sample program adding 5 and 3, outputting 8 to GPIO, and halting.

## Verification disclosure

- The CO parser and structural PICADS project are locally testable.
- Verilog simulation, SKY130 hardening, real DEF/GDS, timing, IR drop, LVS and DRC have **not** been run
  in the packaging environment. The testbench is included for your local simulator.
- The placement area and stay-out are required constraints on macro placement. They do not prevent
  all signal or power routing from crossing a stay-out unless a separate routing obstruction is specified.
