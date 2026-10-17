# PICADS — Known issues, bugs, limitations and untested functionality

**Status:** Work in progress (WIP), experimental / pre-1.0.  
**Last reviewed:** 2026-10-17. **Source baseline:** PICADS v0.16.8 r14.  
**Update rule:** Review this register after each change and actual tool run.
Reports from the user's installed environment and archived release notes are
not a substitute for independent reproducibility or silicon qualification.

## Warning and status vocabulary

- **Confirmed failure**: an observed non-passing native tool or report.
- **Known behavior / limitation**: a deliberate capability boundary in source.
- **Unverified**: not proven to work, not necessarily broken.
- **Tested subset**: a pass on specified inputs; not a universal guarantee.

PICADS cannot certify safe or manufacturable silicon on its own. A file ending
in `.gds` is a layout artifact, **not** a signed-off foundry mask set.

## Currently known failures and limitations

| ID | Status | Area | Evidence / present limitation | Expected follow-up |
|---|---|---|---|---|
| PIC-001 | Confirmed failure, input-dependent | Top-level PDN | Manual ASTER-8 placement run `cc802bd6d80a` failed `OpenROAD.GeneratePDN` with `PDN-0179` (unrepaired VPWR/VGND metal1 channels); examples include 7.82 µm and 6.44 µm channel widths. The nominal die was 627.01 × 519.65 µm. | Inspect `build/latest/co_macros/pdn_diagnostics.json`; improve clearance/PDN planning and rerun native layout. No assertion that r14 fixes this. |
| PIC-002 | Confirmed success, **not signoff** | Physical GDS | Earlier ASTER-8 run `da21aa121463` generated top GDS and verified six macro placements, but independent DRC/LVS, manufacturing and functional-equivalence signoff were deferred. | Preserve build artifacts and verify that exact run separately. |
| PIC-003 | Unverified | DRC and LVS | No independent passing foundry-qualified DRC or layout-versus-schematic result for ASTER-8 was provided. A generated GDS and basic integrity check are not DRC/LVS. | Run F9 Verify Existing Layout, inspect rule decks, native logs, full violation counts and LVS results. |
| PIC-004 | Unverified / previously reported issue | GDS XOR and viewer | The prior Magic–KLayout XOR concern has not been resolved by the r14 manual-editor changes; numeric GDS layers, layer purpose palettes, and hierarchies still require viewer-specific verification. | Run an independent geometry comparison on identical intended inputs; inspect genuine differences rather than relaxing checks. |
| PIC-005 | Unverified | Functional equivalence | The Python/DLS transactional reference and the independent, six-module modular CO RTL are **not** formally/sequentially proven equivalent. Synthesis of a Python function does not prove a complete CPU implementation. | Formal or exhaustive constrained verification of CPU observable behavior, reset/stall/memory/I/O, and RTL vs reference. |
| PIC-006 | Known limitation | Placement optimization | Compact auto placement minimizes computed **die area among enumerated candidate packings**; it is heuristic, not a global optimum and not aware of all power-grid and signal-routing obstacles. Legal geometry does not imply routable PDN. | Iterate with real LEF, routing/PDN feedback and objective scoring. |
| PIC-007 | Unverified new UI feature | Manual floorplan drag & chip size | r14 decouples dragging from strict on-motion validity and adds editable die dimensions and automatic reset. 68 targeted tests passed, one Qt-dependent test skipped; no native Windows mouse/Qt end-to-end GUI session was completed in that patch environment. | Validate selection, drag, zoom, save/reload, invalid placement, automatic recovery on Windows with PySide6. |
| PIC-008 | Unverified runtime detail | GUI macro labels | Earlier editor versions showed missing/unreadable macro names; r13 switched to direct Qt painting. No full runtime Qt visual verification here confirms legibility under all zoom/scale combinations. | Test named modules at several zoom levels and mixed DPI settings. |
| PIC-009 | Environment-dependent failure | Docker + WSL | Windows user run `563e2ffffaec` failed physical preflight because Ubuntu WSL did not have access to `docker`; after restoring WSL integration, `da21aa121463` passed physical generation. | Diagnose Docker Desktop engine, Ubuntu WSL integration and native tools before editing CPU source. |
| PIC-010 | Known limitation | Power verification | Presence of `VPWR`/`VGND` DEF SPECIALNETS is checked on successful runs; this does NOT independently certify continuity, voltage drop, electromigration or all macro pin hookups. PINMISSING power warnings appeared during Verilator lint in some runs. | Detailed routed connectivity, IR-drop/EM and PDN verification. |
| PIC-011 | Unverified | Timing / electrical corners | A reported timing PASS from a metric alone does not prove adequate paths, path constraints or process/voltage/temperature coverage. One reported setup metric was extremely large and should not be interpreted as normal measured slack without checking constraints. | Review unconstrained paths, clocks, endpoints, full STA, corners, extracted RC and actual frequencies. |
| PIC-012 | Known limitation | Source language and synthesis | Supports restricted typed Python and a limited C subset; not a compiler for arbitrary Python/C/C++ semantics. Resource sharing and clocked scheduling have documented subset restrictions. | Validate each supported construct using test oracle and hardware-specific tests; see `docs/IMPLEMENTATION_STATUS.md`. |
| PIC-013 | Known limitation | Technology | Custom experimental TFT/analog processes are not automatically characterized or fab-ready. Physical flow used SKY130A standard cells and requires PDK and external tools. | Obtain proper process models, rules, characterized cells and independent qualified signoff. |
| PIC-014 | Unverified on this host | Full native test matrix | The r14 patch reported 68 relevant pytest passes and one PySide6 skip; it did not run a complete Windows GUI + native OpenROAD/KLayout/DRC/LVS suite locally. Some older notes describe previous versions, not proof for r14. | Run full regression and v1 acceptance on target Windows+WSL setup, capture raw logs and tool versions. |
| PIC-015 | Incomplete qualification | Full manufacturing chain | Antenna, LVS, qualified DRC decks, multi-corner STA, extracted RC, IR/EM, formal equivalence, tapeout, mask prep and fabricated silicon have not all been signed off. | Mark 'UNVERIFIED' or 'NOT QUALIFIED' until real evidence exists. |

## Tested versus untested matrix (do not collapse these)

| Operation | Evidence currently available | What the evidence does **not** prove |
|---|---|---|
| Compile ASTER-8 Python datapath to RTL | Observed PASS in uploaded reports, plus relevant source tests | Correctness of the separately defined complete six-module CPU RTL |
| Harden six modular RTL children | Observed PASS in successful native physical run | Child DRC/LVS and fab suitability |
| Top-level placement/routing/GDS | `da21aa121463` reached GDS, 6 module instances verified | Other placements route; source equivalence; signoff |
| Manual placement `cc802bd6d80a` | Observed native OpenROAD `PDN-0179` failure | That r14 drag improvements alone repair PDN |
| Manual editor behavior on Windows | Code and targeted Python tests | Actual Qt/DPI/drag behavior on target Windows machine |
| Post-layout checks | Documentation and verification workflow provided | Passing full independent DRC/LVS, antenna or all timing corners |

## How to report and reproduce a new issue

1. State the PICADS release / patch, Windows and WSL distribution, Docker engine,
   target PDK and external EDA tool versions.
2. State GUI action (F7 synthesize, F8 generate layout, F9 verify), or exact CLI
   command, and attach the smallest reproducible project with `architecture.co`.
3. Include `build/latest/report.json`, `events.jsonl`, matching `physical.log`
   or `layout_verification.log`, `config.json` and `co_macro_plan.json` if relevant.
4. Classify **PASS**, **FAIL**, **PARTIAL**, **UNAVAILABLE**, **DEFERRED** and
   **UNVERIFIED** accurately. Never silently treat deferred signoff as passing.
5. Add an entry here when the issue is reproduced or its verification gap is
   material, including whether it was fixed, mitigated, or still untested.

Related documents: [implementation status](IMPLEMENTATION_STATUS.md),
[roadmap](FUTURE_FEATURES.md), [automatic macro sizing](AUTOMATIC_PHYSICAL_MACRO_SIZING.md),
[physical macros](CO_NATIVE_HARD_MACROS_r9.md),
[v1 acceptance](V1_SCOPE_AND_ACCEPTANCE.md), and
[`PATCH_README_r14.md`](../PATCH_README_r14.md).
