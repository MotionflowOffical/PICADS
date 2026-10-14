# Automatic child-macro and top-level die sizing

PICADS has two independent space-efficiency controls.

**1. Child dimensions:** Fixed mode takes `die_size_um: [w,h]` and passes that explicit die/core area to LibreLane. Auto mode takes `die_size_um: auto` and omits those fixed limits. LibreLane sizes the die after technology synthesis, based on `FP_CORE_UTIL` and `FP_ASPECT_RATIO`. The resulting hardened LEF `SIZE` is authoritative; prebuild GUI `preview_size_um` is illustrative only.

**2. Top-level packing:** Once all child LEFs exist, the compact placer searches deterministic horizontal/vertical shelves and block orders to minimize overall die bounding area, without crossing CO region bounds, intersecting exclusion zones or violating clearance. Placement region is a *constraint*, not an enforced die size. The top config receives the computed top-level DIE_AREA and CORE_AREA. Thus the region may be much larger than the manufactured die.

Example CO:

```yaml
physical_macros:
  enabled: true
  enforcement: required
  top_module: ...
  top_rtl: rtl/top.v
  auto_core_utilization: 45
  placement:
    mode: compact
    region_um: [30, 30, 1250, 1100]
  spacing:
    min_um: 15
    preferred_um: 45
    pdn_min_um: 45
    max_um: 90
  blocks:
    - name: ProgramMemory
      module: program_memory
      instance: u_program
      rtl: rtl/program.v
      die_size_um: auto
      preview_size_um: [320, 280]  # Optional, GUI estimate ONLY
```

A 45% target means *target standard-cell occupancy inside the child core*, not 45% macro-to-die coverage, not a manufacturing yield or a signoff guarantee. Routing, clock trees and power grids may require lower density. After GDS generation inspect the `child_sizing` report for hardened dimensions; the percentage of outer die occupied by macro bounding rectangles is a distinct measurement. ``FP_CORE_UTIL`` is a synthesis-derived target; actual placed/routed cell utilization must be verified independently.

All manual positions and CO hard geometry stay authoritative; a too-small die, illegal placement, routing congestion or a failed PDN is an error, not silently excused by a compact-area score. The old 60 µm multi-macro conservative gap remains the fallback when `pdn_min_um` is absent. The ASTER-8 test project explicitly sets its 45 µm minimum for area exploration; this has not yet been proven to pass PDN.
