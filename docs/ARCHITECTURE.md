# Architecture and stage contracts

```
chip.yaml, MCD, CO, typed Python
    -> independent config/source validation
    -> behavioral AST
    -> bit-vector elaboration
    -> procedural gates: ripple or parallel-prefix, partial products, multiplexers
    -> DLS (one authoritative gate-level graph)
      |-> native gate interpreter -> compare to independent numeric source interpreter
      |-> structural Verilog -> optional Yosys synthesis -> optional LibreLane physical EDA
      |-> IDE graph, registers, variables, hierarchy, issue provenance
```

**Core invariant:** the RTL generator only exports the actual primitives in DLS, and the DLS simulator executes those same primitives. Source behavior checking is done with a separate interpreter to detect incorrect construction. The Verilog backend has not yet been proven equivalent by an installed third-party formal equivalence tool, and electrical mask connectivity cannot be inferred solely from DLS.

## Reporting

- `PASS_EXHAUSTIVE`: all relevant small combinational input combinations checked; source/DLS behavioral equivalence only.
- `PASS_SAMPLED`: randomized deterministic tests succeeded; explicit warning and seed recorded.
- `FAIL`: native functional verification or tool failure.
- `UNAVAILABLE`: required external executable absent.
- `BLOCKED`: causally skipped stage with one or more `blocked_by` IDs. This is **not** a secondary error.
- `SKIPPED`: explicitly disabled by project configuration.

When independent configuration files contain multiple bugs, the load stage reports each. If generation lacks valid prerequisites, it does not manufacture derivative faults downstream. All source, DLS, Verilog and tool failures have distinct origin categories.

## Physical toolchain

Run `python -m chipcompiler doctor` to probe available tools. The optional backend invokes installed Yosys and LibreLane commands and writes full stdout/stderr to `build/latest/<stage>.log`. It **does not** generate masks internally. LibreLane requires real technology files, standard cells and physical rule decks. A successful tool process exit is never enough to claim independent manufacturing signoff.

No automatic installation occurs during ordinary compile or GUI launch. On Windows, configure a supported external EDA environment (typically WSL2); the GUI expects an executable visible on its PATH or launches KLayout separately. This is an important current integration gap: a Windows-hosted IDE doesn't automatically see executables installed only inside WSL2.

## GUI workspaces

- Code + Graph: source tabs, syntax highlighting, generated primitive DLS nodes, source provenance tooltips.
- Architecture: module hierarchy, signal/port list, dependency metadata, generated gate-type statistics.
- Simulation: editable input vectors, sequential DLS state, step-cycle history.
- Physical: opens actual GDSII/OASIS in KLayout if installed; does not draw fabricated layouts.
- Build: actual stages, artifact paths, causal diagnostic IDs.
- History: snapshots, autosave, restore, unsaved-buffer recovery, revisions.

The dark-theme reference mockups define design direction. All displayed physics is based on real backend files; no representative timing/power/area numbers are invented in the application.


## v0.6: executable network binding

MCD can now specify actual typed `network.instances`, `network.outputs`, and the optional safe `network.auto_connect` policy. These compose individual procedurally synthesized child DLS definitions into a verifiable hierarchical top circuit. The original source top is retained as an independent behavioral oracle; its own synthesized gates are not copied into the composition. Network dependency edges are sorted, with invalid refs/widths/cycles rejected at the network stage and causal downstream blocking. The generated `network_connections.json` is retained for reproducibility. See [MCD_NETWORK_v0.6.0.md](MCD_NETWORK_v0.6.0.md).

This does **not** replace the scheduler, physical place-and-route, or process-specific mask signoff. It is the missing high-level module wiring frontend that feeds the existing executable DLS and RTL pipeline.
