# CO constraint modes and their physical meaning (v0.16.8r8)

CO is an *architecture, allocation, schedule, and physical-constraint* language. It is not merely a drawing description. Constraints that PICADS cannot implement must fail rather than silently become decorative floorplan rectangles.

## Supported enforcement levels

| CO request | Effect | Verification status |
|---|---|---|
| `floorplan.enforcement: guide` | Compute a candidate hierarchical region plan | Architectural preview; no cell placement |
| `floorplan.enforcement: validate` | Validate planned regions and require a real named DLS instance for each applicable module | Source-to-DLS validation; **not** a final physical fence |
| `floorplan.enforcement: required` | Demand hard mapped-cell region enforcement | **Rejected** until real source/ABC/Yosys cell identities and LibreLane/OpenROAD region support exist |
| Per-module `enforcement` | Override the global guide/validate/required policy | Selective, fail-closed |
| `keepouts[].enforcement: required`, `kind: hard` | Send a rectangle to LibreLane `FP_OBSTRUCTIONS` | Real placement-site exclusion requested; final PNR still needs to succeed |
| `keepouts[].enforcement: guide` | Draw only; not passed to LibreLane | Preview only |

`required: true` on a module is **different** from `enforcement: required`: the former says a logical binding must exist and must not be pruned, while the latter means its cells must physically obey a region.

## Example: enforce empty routing channel, guide module regions

In `chip.yaml`:

```yaml
physical:
  enabled: true
  pdk: sky130A
  die_area_um: [0, 0, 200, 200]
  core_area_um: [10, 10, 190, 190]
```

In `architecture.co`:

```yaml
floorplan:
  enabled: true
  enforcement: guide
  region_um: [10, 10, 190, 190]
  border_um: 5
  min_spacing_um: 8
  preferred_spacing_um: 15
  max_spacing_um: 40
  modules:
    - name: ALU
      weight: 2
      enforcement: guide
    - name: Control
      weight: 1
      enforcement: guide
  keepouts:
    - name: RoutingChannel
      kind: hard
      enforcement: required
      bounds_um: [90, 20, 100, 180]
```

This reserves the `RoutingChannel` area against standard-cell placement with LibreLane's `FP_OBSTRUCTIONS` and shows ALU/Control rectangles as guides. **It does not put ALU cells into one rectangle and Control cells into another**; their logical module names are descriptive only in this example.

`module_floorplan.json` lists all planned rectangles and constraint modes. `config.json` must contain only requested hard keepouts as `FP_OBSTRUCTIONS`. `report.json` labels the requested backend action `SUBMITTED_NOT_VERIFIED`; the status is not a DRC/LVS or cell-membership certificate.

## Hard module fencing: design still to be implemented

True module enforcement requires all of the following, none of which can be inferred from a shape guide:

1. CO allocates *actual* retained hardware for each selected function, ALU or memory and records unique IDs (not merely a functional name).
2. Gate provenance survives optimization, hierarchy processing, technology mapping and buffer insertion. Mixed-output/shared operators need a declared allocation policy.
3. The physical backend receives actual mapped instance sets and creates placement-region/fence constraints at the appropriate floorplan and legalization steps. A macro could instead use a separate hardened LEF/GDS/netlist flow.
4. After placement and routing, verify every constrained cell against its fence, plus real minimum/maximum inter-block spacing and the design's DRC/timing/PDN constraints.
5. Reports distinguish `REQUESTED`, `BACKEND_APPLIED`, `PLACEMENT_VERIFIED` and `UNSATISFIED`; users must not see a false pass.

**Fail-closed behavior**: any CO `required` module fence currently raises `CO.FLOORPLAN_ENFORCEMENT_UNSUPPORTED`. Use `guide` for informational regions. `validate` is stronger on binding and geometry but does not assert physical enforcement.

## Limitations

- `FP_OBSTRUCTIONS` prevents creation of standard-cell placement sites; it does not prohibit all upper-layer signal wires or power straps through that area. It is **not** an electromagnetic isolation moat.
- Only explicit `hard` keepouts can be `required`. Soft placement preferences may be violated by later buffer or clock tree placement and must not be represented as hard constraints.
- Physical dimensions must be consistent with the target PDK core and die geometry. A region that is too large or consumes too much area may make place-and-route fail.
- A fixed `max_spacing_um` across every geometric pair is not yet enforceable for final placed module boundaries; it remains a guide geometry property.
