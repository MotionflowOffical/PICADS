# CO hierarchical module planning (v0.16.8r6)

PICADS generates an automatically spaced **architectural region guide** for functional modules. This is **not** equivalent to OpenROAD enforcing placement of standard-cell instances. A GDS may remain flattened, especially for transactional schedulers such as Apollo. The report intentionally uses `GUIDE_ONLY` / `GUIDE_ONLY_NOT_ENFORCED`, and refuses `enforcement: required` until a technology-mapped module-to-cell binding and verified OpenROAD integration exist.

## CO syntax

```yaml
# architecture.co
modules:
  hierarchy: preserve  # only where this compiler mode supports it
floorplan:
  enabled: true
  enforcement: guide
  region_um: [0, 0, 500, 300] # explicit coordinates, or use physical.die_area_um
  border_um: 10
  min_spacing_um: 8
  preferred_spacing_um: 16
  max_spacing_um: 35
  modules:
    - name: ArithmeticSubsystem
      weight: 3
      modules:
        - name: FirstLeaf
          instance: top/middle_0  # replace with a real path from module_floorplan.json
        - name: SecondLeaf
          source_function: middle
    - name: Control
      weight: 1
```

The planner only binds declared DLS instances to actual pre-synthesis instances and checks source functions and CO scheduled resource usage. Unused optional selectors are pruned; unused `required: true` selectors fail. The planner creates `build/latest/module_floorplan.json` and a scalable `module_floorplan.svg` with containment/border/spacing checks. The GUI Build / Physical panel can show the SVG.

**Future enforced placement:** PICADS must retain source provenance through Yosys/ABC technology mapping, map each live cell to exactly one module group, integrate region constraints at the correct OpenROAD phase, and measure actual placed cell bounds and minimum/maximum separations. The current code does none of that. Static rectangles cannot be presented as already placed GDS modules.

## v0.16.8r8 selective CO enforcement

See [CO selective physical constraints](CO_SELECTIVE_PHYSICAL_CONSTRAINTS.md) for per-module `enforcement`, source-binding validation, and LibreLane-backed physical keepouts. Real mapped-cell module fences are **not** supported and fail explicitly if required.
