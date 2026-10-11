# Current implementation status — v0.8.0

| Subsystem | Evidence-based status |
| --- | --- |
| Primitive digital logic and generated DLS | Tested on supported operations; limitations in frontends remain |
| Sequential DLS hierarchy | Tested including per-instance independent register state |
| MCD typed module networks | Tested explicit typed logic graphs; auto complex arbitration wiring incomplete |
| CO transactional CFG | One task in flight, guards and internal memory; tested restricted subset |
| CO concurrent service fabric | NEW, gate-level tested 2..8 clients, parallel ALU/memory domains, bounded buffering and fair arbitration |
| Variable-latency interface | NEW external ready/valid operator; sampled DLS tests, physical IP link and RTL check unverified here |
| Memory-port arbitration | NEW local synchronous single-port bank, invalid address detection; not external SRAM or general multi-port coordination |
| Python/C/C++ source synthesis | Restricted documented static subsets; general HLS not complete |
| GUI | Added resource fabric inspector; runtime not verified locally (missing PySide6) |
| Diagnostics and recovery | Regression-tested core; automatic native logs and bundled diagnostic runner added |
| Structural Verilog export | Generated and syntactically inspected; real Icarus/Yosys execution unavailable locally |
| Yosys/LibreLane/OpenROAD | Adapters exist; native runtime unverified here |
| GDSII preview | Partial read-only geometry preview, not physical signoff |
| Custom TFT PDK, qualified masks and foundry signoff | Not implemented |

**Do not treat `compile` success or a screenshot as proof of physical correctness.** For native proof, execute `RUN_FULL_VALIDATION.bat` on an environment with the required tools and return its ZIP report. See `FULL_VALIDATION_v0.8.0.md`.
