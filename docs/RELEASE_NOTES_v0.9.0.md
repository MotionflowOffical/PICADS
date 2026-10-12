# PICADS 0.9.0 — release notes

- Introduced PICADS brand and `picads` launcher while preserving backward-compatible `chipcompiler` names and DLS serialization format.
- Added tagged concurrent multi-outstanding resource fabric (max 8 virtual slots), response tags, duplicate-tag blocking, sticky response lock and fairness state.
- Added restricted MCD source-function-to-client binding for pure fixed-width ADD/MUL functions.
- Added independent external memory request and response channels with ready/valid, arbitration, owner state, variable completion time and explicit fault reporting.
- Added independent randomized tagged arithmetic oracle and simulated memory-device verification with mutation tests.
- Added optional bounded SymbiYosys safety-property collateral; generated-but-unrun collateral is not a formal PASS.
- Expanded Icarus stimulus support and one-command Windows diagnostic runner; GUI inspector supports tagged modes.
- Still incomplete: arbitrary concurrent high-level source scheduling; general C/C++ language; AXI/complex multi-beat protocols; real EDA runtime and Qt testing on a full Windows+EDA installation; PDK-specific mask preparation; manufacturing signoff.
