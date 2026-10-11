# Remaining engineering after v0.8.0

## 1. Full concurrent high-level synthesis and MCD integration

The v0.8 fabric is a **real but bounded synchronous hardware resource service**. It is not a general compiler translating independent arbitrary Python/C++ programs into concurrently executing architectures. Still required: discovering resource requests in MCD modules, automatic cross-module routing/binding, per-module scheduling state machines, real context/transaction IDs, multiple tasks in flight per client, SSA/value lifetime analysis, data hazards, burst interfaces and deadlock checking across arbitrary feedback networks.

## 2. External operator and memory protocols

Expand from one external single-owner untagged ALU to multiple characterized pipelined operator instances, ready/valid across stalls without a shared global stall assumption, explicit flush semantics, transaction-tag matching and cancellation. Expand one register-bank memory port to SRAM macros/AXI-like protocols with variable access latency, bandwidth/resource limits, coherence when required and independently verified memory ordering.

## 3. Independent executable tests on target platform

Run `RUN_FULL_VALIDATION.bat` and inspect the returned ZIP. Fix real GUI exceptions and independent RTL-vs-DLS mismatches if they appear. Ensure actual RTL simulation and Yosys pass on a fully installed Windows/WSL2 setup; investigate clock/reset timing and synthesizability of the generated sequential logic. Expand formal properties beyond deterministic sampled protocol checks.

## 4. Physical design and custom fabrication

Use a known-good open process before a custom thin-film transistor library. Characterize transistor and wire behavior, standard-cell timing/area/leakage, RC extraction, LEF/GDS, DRC/LVS decks, clocking/power and all relevant corners. Run actual Yosys/LibreLane/OpenROAD, verify extracted connectivity and physical checks. A GDS exists is NOT manufacturing signoff or mask preparation.

## 5. GUI and diagnostic improvements

End-to-end native PySide6 interaction tests and project recovery tests on actual Windows. Add interactive multi-client timeline and resource contention heatmaps, real native error links to source/CO and actionable remediation. Preserve the existing causal error-chain and no-silent-fallback policy.
