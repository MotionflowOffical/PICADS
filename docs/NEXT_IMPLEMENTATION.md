# PICADS — remaining v1.0 blockers after v0.15

**Scope freeze:** Do not treat the deferred capabilities in [FUTURE_FEATURES.md](FUTURE_FEATURES.md) as requirements for PICADS v1.0. The v1 acceptance target is defined in [V1_SCOPE_AND_ACCEPTANCE.md](V1_SCOPE_AND_ACCEPTANCE.md).

## Work required before a real v1 release

1. **Execute first-chip acceptance on Windows/WSL with real tools.** The new `RUN_V1_ACCEPTANCE.bat` must run Icarus RTL equivalence, Yosys synthesis, LibreLane placement/routing and Qt smoke tests on the user's system; collect its diagnostic ZIP and fix any real errors.
2. **Establish a supported PDK.** Select a verifiable digital standard-cell technology supported by LibreLane; confirm library choice, legal layers, power pins, accurate timing and physical constraints. Custom TFT materials require separate device characterization and library creation.
3. **Resolve physical errors from evidence, not assumptions.** Only actual fresh-run GDSII with correct top, routing views and reported signoff data counts as physical implementation. Extract and preserve stage logs and failed constraints.
4. **Native RTL/formal cross-checks.** Use the installed RTL simulator for source-to-DLS/RTL comparisons. Where possible, prove bounded properties with a real solver. Sampled Python tests are not enough for silicon confidence.
5. **Finish the GUI runtime workflows.** Exercise project opening, source editor, dependency picker, preflight button, DLS simulation, RTL export, physical launch and GDS inspection in real Qt on Windows.
6. **Finalize documentation and install package.** Provide an explicit v1 subset/language contract, supported platform/PDK/tool versions, deterministic install/run scripts and artifact/provenance logs.
7. **Manufacturing signoff remains outside automated v1 self-certification.** Obtain qualified DRC/LVS/STA/parasitic/power/antenna verification and foundry acceptance separately before describing masks as manufacturable.

**Next practical action:** Run `RUN_PICADS_AUTOTEST.bat` after registering native external dependencies, then upload `validation/PICADS_v0.15.0_automated_diagnostics.zip`. The automated report explains PASS vs UNAVAILABLE vs FAIL per subsystem.

## v0.15 verification mechanism

`RUN_PICADS_AUTOTEST.bat` runs deterministic CLI workflows, injects source faults, rebuilds a source-only ALU component, calls the independent 1,024-case truth-table test and, where available, exercises Qt widgets automatically. It also attempts native ALU RTL/synthesis and the first-chip source-to-GDS flow. Optional `--full-regression` isolates historical tests to prevent a single hung test from masking the others.

Native DRC/LVS/STA and physical process qualification remain open until a real installed and characterized process and EDA toolchain produce passing independent evidence. The acceptance runner is not a substitute for foundry signoff.
