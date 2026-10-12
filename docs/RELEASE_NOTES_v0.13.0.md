# PICADS 0.13.0 release notes

### Implemented

- Twelve selectable shared binary operator types: ADD, SUB, MUL, AND, OR, XOR, EQ, NE, LT, LE, GT, GE.
- Conservative `global_shared_types: auto` selection across source-defined process instances.
- Opt-in single-port shared register bank (`global_shared_memory: true`) with round-robin read/write arbitration, explicit grants, reset, stalls, invalid-address fault semantics and register-bank visibility.
- Source-process global arithmetic and shared memory combined in one structural Verilog/DLS design.
- Independent isolated AST-reference comparisons and concurrent cycle-accurate shared memory scoreboard; sampled protocol and result mutation tests.
- Generated formal safety properties for memory-port ownership and grant exclusivity.
- New examples (`global_auto_operators`, `global_shared_memory`), updated GUI inspection, and extended full/focused one-command validators.

### Not implemented / not proven

- Arbitrary concurrent HLS, fully automatic cross-process dependencies, transactional source queues larger than one, variable-latency global physical units, AXI4 bursts, physical PDK closure, DRC/LVS/STA signoff, or successful actual mask manufacturing.
- Runtime GUI, external RTL, SMT proof and physical-flow execution were not available in the build environment.

### Migration

Cumulative source ZIP; pre-existing explicit ADD/MUL configurations remain supported. Default process mode does **not** activate sharing unless declared in CO.
