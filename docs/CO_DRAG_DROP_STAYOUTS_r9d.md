# PICADS r9d: CO physical placement zones and live drag constraints

This release adds a native drag-and-drop modal under **Physical / Masks** →
**Edit CO Floorplan (Drag and Drop)**. It edits *real* `physical_macros`
instances, not architectural plan-only module drawings or final GDS geometry.

## Constraining movement through CO

The physical macro section supports an optional placement region and any number
of stay-out rectangles, in absolute physical micrometres:

```yaml
physical_macros:
  enabled: true
  enforcement: required
  placement:
    mode: compact
    region_um: [30, 30, 1180, 980]
    stayouts_um:
      - [545, 485, 610, 570]
  halo_um: 6
```

- `region_um` is the **allowed** macro placement area. The complete macro
  rectangle must remain within the cyan boundary.
- `stayouts_um` are **forbidden** macro placement rectangles. The red area
  includes the mandatory `halo_um` clearance around each obstacle.
- Previously declared CO `floorplan.keepouts` with `kind: hard` and
  `enforcement: required` also block the macro editor. Guide-only or soft
  keepouts are not misrepresented as mandatory placement constraints.
- Other macros and the CO minimum/maximum spacing requirements also restrict
  movement. Dragging is restricted while moving, not only on release.
- `mode: compact` automatically packs valid macro positions, while `mode:
  manual` binds explicit `location_um` values in each block.
- With no explicit placement region, the editor uses its provisional workspace
  with the existing 30 um edge limit. For a deterministic physical limit, set
  `region_um` in CO.

All restrictions also apply to the saved CO coordinates and the native macro
backend. Illegal manual positions and impossible auto layouts fail explicitly;
no forbidden coordinates are silently accepted.

**Scope:** These zones constrain macro *placement*. They do not automatically
prevent top-level signal/clock/PDN routing across a stay-out, nor substitute
for the actual final-DEF placement check. A physical routing keepout must be
implemented separately through appropriate PDK/OpenROAD routing obstructions.

## Normal PICADS workflow

1. Start Docker Desktop, enable Ubuntu under WSL integration, and wait for its
   engine to be running.
2. Open a normal PICADS project with an `architecture.co` macro section.
3. Open **Edit CO Floorplan (Drag and Drop)**. Drag within the cyan region;
   red zones and macro clearances are enforced live.
4. Click **Repack Compact** if desired, then **Save Positions to CO**. PICADS
   saves an `.architecture.co` backup under `.chipcompiler/floorplan_backups`.
5. Regenerate GDS. Saving a CO location does not move previously routed cells.
6. Run **Verify Existing Layout** for post-layout signoff checks.

This change does not automatically attribute arbitrary flattened PICADS DLS
logic to physical modules. Required macros remain explicit, separately
hardened RTL instances; Python and RTL equivalence remains unverified.
