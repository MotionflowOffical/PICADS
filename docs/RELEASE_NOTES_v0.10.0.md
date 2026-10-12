# PICADS v0.10.0 release notes

## Delivered

1. **GUI Settings external-tool manager:** Choose App, Choose Folder, Clear, Refresh, and Auto Detect installed tools. Supports KiCad and KiCad CLI, KLayout, Yosys, Icarus, LibreLane, OpenROAD, Magic, Netgen, SymbiYosys, Z3, Verilator, GCC/G++, and WSL.
2. **Persistent native-tool resolution:** validated per-user registry, deterministic precedence over system PATH, error reports for stale selections, native subprocess execution through registered paths, and temporary PATH augmentation for tools launched by external wrappers.
3. **Command-line registration and discovery:** `picads dependencies list|auto|set|clear`, with `--folder` selection.
4. **Custom PDK inventory:** manual folder selection and read-only LEF/Liberty/GDS/DRC/LVS candidate scan; never described as manufacturing signoff.
5. **Conditional MCD source binding:** two unsigned operands and a Boolean selector can choose ADD/MUL per accepted request, including ternary and restricted terminal if/else forms. The Boolean selector becomes an actual typed DLS input; unsupported source control flow still fails explicitly.
6. **Validator additions:** honours manually registered dependencies for RTL, formal and synthesis tests; version probes; complete source-selected MCD example; selected PDK inventory; user-run diagnostic ZIP preserved.
7. **Tests:** expanded tests cover successful/invalid registration, precedence, deleted registrations, registered tool execution, inherited child-PATH lookup, autodetection, PDK inventory, conditional MCD binding and safety rejection.

## Still not implemented

Arbitrary concurrent HLS process extraction, general source-to-MCD binding, arbitrarily deep transaction queues, AXI4/AXI4-Lite and burst memory, live formal or RTL checks on this host, process-mapped GDS generation for arbitrary custom materials, and qualified DRC/LVS/STA/PEX/foundry signoff. The GUI remains runtime-unverified here because PySide6 is not installed.
