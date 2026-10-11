# Optional independent RTL execution check (v0.6)

This feature generates a deterministic Verilog testbench and runs `iverilog` and `vvp` to compare the **independently executed gate-level Verilog** with executable DLS on sampled vectors. The expected values come from DLS, while source-vs-DLS is verified in a separate earlier stage.

Enable explicitly in `chip.yaml`:

```yaml
verification:
  external_rtl: true
  rtl_vectors: 64  # 1..256
```

The script `rtl_check_tb.v` is retained in `build/latest/`. Native tool output is retained in `rtl_compile.log` and `rtl_execute.log` with structured issue IDs. `rtl_verification.json` contains the number of compared vectors and any first counterexamples. The testbench drives inputs, samples outputs **before** each rising clock edge, and then clocks any stateful DLS design, matching the DLS simulation contract. It supports one implicit shared clock and combinational designs (including nested module networks). It DOES NOT verify dynamic asynchronous behavior or physical timing.

If `iverilog`/`vvp` is absent, the explicitly requested check fails with `TOOL.MISSING`, and dependent synthesis is `BLOCKED`. A process exit of zero with missing/malformed output yields `RTL.BINARY_MISSING` or `RTL.OUTPUT_INCOMPLETE`, never PASS. Any observed mismatch yields `RTL.BEHAVIOR_MISMATCH` with a replayable input vector. Clocked designs are checked with a stream of deterministic inputs so register-history behavior is exercised.

Automatic pipelines (`schedule.pipeline_stages`) and time-shared transaction designs (`schedule.mode: time_share`) have distinct protocols. This simple testbench does not support those protocols; an explicit request is rejected with `RTL.PROTOCOL_UNSUPPORTED`. Do not claim RTL equivalence for those cases until a protocol-aware external testbench is implemented.

**Verification scope:** sampled RTL-vs-DLS agreement only. Not formal proof, not transistor/electrical validation, not DRC/LVS, not fabrication signoff. The external simulator was unavailable in the release environment; the harness has mock-driven protocol tests but no real Icarus execution evidence here.
