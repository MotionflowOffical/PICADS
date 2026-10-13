# Apollo hierarchical floorplan demonstration

This example preserves Apollo's circuit and CO scheduling and adds only a CO `floorplan:` block. It generates `build/latest/module_floorplan.json` and a sharp, scalable `module_floorplan.svg` when compiled.

**NOT A GDS FLOORPLAN:** Apollo's transactional core is still a single physically flattened netlist. Blocks such as ControlFSM and Memory are conceptual regions without mapped standard-cell membership; the compiler does not enforce their physical locations in LibreLane. `UnusedMultiply` is pruned because CO did not allocate a multiplier. The ADD resource is present and can be planned, but is not yet a separately placeable cell cluster.

The configured `[0,0,1500,1200]` region is an illustration canvas; it is **not** a verified SKY130 die-area constraint. To create an actual 1500 × 1200 um die you must separately set `physical.die_area_um` and revalidate routing, pin placement and timing. The Apollo instruction logic is otherwise unchanged.

This variant also opts into `synthesis.abc_aig: true` and PDK-default power/ground rails plus multilayer PDN. The optimized AIGER is produced only in `build`/`physical` mode after a successful Yosys stage and is **not** the PDK-mapped physical netlist. Check `abc_aig.log` for a real run and the final DEF for SPECIALNETS. No live WSL physical verification was performed in the development environment.
