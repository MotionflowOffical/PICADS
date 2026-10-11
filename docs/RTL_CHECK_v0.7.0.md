# Optional external RTL check — v0.7.0

`verification.external_rtl: true` requires *real* Icarus Verilog (`iverilog` and `vvp`). It compares structural exported RTL against executable DLS in a separate process. Source-vs-DLS verification is a separate stage and is not silently replaced by an RTL comparison.

```yaml
verification:
  external_rtl: true
  rtl_vectors: 64
```

- Supports combinational and synchronous DLS designs with nested hierarchy, as in v0.6.
- Now also generates scheduled clock-vector samples for `schedule.mode: time_share` and `schedule.mode: transactional` and samples outputs before each rising clock edge, matching the DLS simulator contract. Scheduled samples exercise `start`, `ready`, optional `stall`, and `unit_ready_*` while varying original inputs during BUSY.
- `rtl_vectors` is a cycle budget, not necessarily number of completed transactions. If the budget cannot complete one transaction, `RTL.SAMPLE_CONFIG` reports a clear error requesting a larger budget; an incomplete sample is never marked PASS.
- All vectors and native logs are retained as `rtl_check_tb.v`, `rtl_compile.log`, `rtl_execute.log` and `rtl_verification.json` when execution progresses far enough.
- A native compiler error, missing executable, incomplete output markers, unknown-X/Z result, wrong top, or mismatch is an explicit failure with source evidence and dependent stages blocked. No mock compiler success is accepted.

**Scope:** sampled RTL/DLS cycle equality only; neither formal sequential equivalence nor physical timing, memory macro verification, DRC/LVS or manufacturing signoff. The release environment does not have Icarus installed, so the new bench generator and missing-tool behavior were tested, but there is no claim that real Icarus execution passed.
