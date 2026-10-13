# ABC-optimized AIG and power/ground distribution (v0.16.8r6)

## ABC-optimized AIGER

Opt into a separate optimized AIGER export from `architecture.co`:

```yaml
synthesis:
  abc_aig: true
```

This runs a separate Yosys synthesis pass followed by `dffunmap`, ABC generic AND mapping, `aigmap`, and `write_aiger` **after** PICADS has successfully produced `synthesized.v`:

```
read_verilog top.v; hierarchy -check -top top;
synth -top top -flatten -noabc; dffunmap; abc -g AND;
aigmap; write_aiger -zinit -symbols abc_optimized.aig
```

Outputs in `build/latest/`:

- `abc_optimized.aig` — ABC-optimized, flattened AIGER artifact; check its `aig`/`aag` header.
- `abc_aig_stats.json` — inputs, outputs, latches, AND node counts, and file size.
- `abc_aig.log` — complete ABC/Yosys tool output.

The request is **fail-closed**: if Yosys cannot export a real AIG, PICADS marks the stage failed instead of creating a placeholder. This is an independent optimization/analysis artifact, not proof of area savings or formal equivalence. The regular LibreLane flow still uses original structural RTL and runs PDK-specific Yosys/ABC technology mapping itself. Comparing AIG AND count to GDS cell count directly is invalid. The new stage is currently implemented for standard `build` and `physical` modes, not all specialized fabric runners.

## Power and ground grid

LibreLane Classic already generates a standard-cell PDN in its OpenROAD steps. PICADS now **explicitly enables** power rails and global connections, and defaults to PDK-managed multilayer straps and power connections for macros. You do not need to draw an enormous ground rectangle over the design, which could short routing layers or violate DRC.

```yaml
# chip.yaml
physical:
  enabled: true
  pdk: sky130A
  clock_period_ns: 100
  power_grid:
    rail: true                # required: cannot be false
    global_connections: true  # required: cannot be false
    multilayer: true
    connect_macros: true
    core_ring: false          # optional core ring; enable only when validated
    # Only override geometry when required by YOUR PDK:
    # vertical_pitch_um: 30
    # horizontal_pitch_um: 30
    # vertical_width_um: 2
    # horizontal_width_um: 2
```

PICADS maps these to LibreLane's `PDN_ENABLE_RAILS`, `PDN_ENABLE_GLOBAL_CONNECTIONS`, `PDN_MULTILAYER`, `PDN_CONNECT_MACROS_TO_GRID`, `PDN_CORE_RING`, and optional `PDN_[VH]PITCH/WIDTH` variables. Unknown keys, invalid values, and disabled rails are rejected during physical preflight. By default PICADS **does not override** PDK stripe widths/pitches.

Preflight's `pdn_configuration: PASS` proves only valid requested settings. After an actual physical run, the `physical_evidence.json` check `pdn_specialnets` examines the final routed DEF's `SPECIALNETS` section. Finding at least two nets is basic structural evidence of distinct power nets, **not** proof of VDD/GND connectivity, EM/IR, current capacity, rail continuity, or foundry signoff. Check actual LibreLane PDN logs, powered netlist, connectivity checks, DRC/LVS, IR drop and signoff reports for fabrication.

For SKY130, a common convention is `VPWR` and `VGND`, but no net name is hardcoded as universal for arbitrary PDKs. The physical PDK determines actual rails and layout layers. Custom ZnO/CuO/PVC thin-film process rules require separate qualified technology files before physical output is considered meaningful.

## Floorplanning limits

Use `floorplan` to plan nested functional regions. Actual cell placement remains unconstrained until there is verified instance-to-cell binding and a corresponding OpenROAD placement hook. In particular Apollo is currently compiled with flattened transactional control, so a visual rectangle labeled “ALU” cannot correctly group the actual placed ALU gates without changing its compiler architecture.

## Windows verification

After overlaying the patch, rerun an existing reference project. Verify `build/latest/config.json` contains PDN fields. For an AIG project in `build`/`physical` mode with WSL tools working, verify `abc_aig` is `PASS` and `abc_optimized.aig` is nonempty. For a completed physical build, verify `physical_evidence.json` and inspect the final DEF, GDS, LibreLane routing/timing reports. This release was tested through Python/mocked tools; **no live Windows/LibreLane run was executed in the authoring environment**.
