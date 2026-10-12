# PICADS v0.16.4 — Windows DLL recovery release verification

## Evidence from supplied Windows diagnostic

Analyzed `PICADS_v0.16.3_tools_diagnostics.zip` (Windows 10, Python 3.12.6, October 12, 2026). `kicad-cli`, `iverilog`, `vvp`, `verilator` and `klayout` probes passed. Yosys returned `3221225781` (`0xC0000135`, DLL not found); Z3 returned `3221225785` (`0xC0000139`, DLL entry point not found). PICADS also recorded failure invoking the managed OSS CAD Suite `environment.bat` under a folder named `PICADS Build`.

These failures demonstrate that `available` in the dependency registry only meant a file existed, not that the executable could launch. The two environment problems in the prior code were: (1) `cmd /c` mishandling the quoted `environment.bat` path, and (2) constructing a universal PATH containing KiCad, KLayout, OSS CAD Suite and MSYS2 tool directories.

## Implemented repair

- Use a short-lived temporary `.cmd` file to call the managed `environment.bat`, then parse the child process's environment; delete the file even on activation failure.
- On Windows use separate runtime environments for each external tool family, with OSS CAD Suite's own DLL path before unrelated installed software. GUI/Python/Qt processes do not inherit a broad union of tool directories.
- Apply tool-specific environments to actual native builds, version probes and GUI launches of KLayout.
- Label Windows loader `0xC0000135`, `0xC0000139`, `0xC0000142`, and `0xC000007B` with clear diagnostic categories. Attempt to suppress Windows loader pop-up dialogs during the synchronous audit subprocess probe.
- Regenerate the one-command `RUN_WINDOWS_TOOL_AUDIT.bat` ZIP report with v0.16.4 naming.

## Regression results

All 24 existing/new test files completed as independent Python pytest processes, preventing slow historical tests from blocking the whole run. Aggregate result: **534 passed, 3 skipped, 0 failed**, including seven new focused Windows environment/DLL tests. Some Qt tests are skipped because PySide6/GUI runtime is unavailable in the Linux execution environment. File-by-file machine-readable results are in `REGRESSION_GROUP_RESULTS_v0.16.4.json`.

The monolithic test run previously timed out in an older CPU-heavy test group and is not claimed to have passed as one command. The file-by-file run covers the full test directory.

## Evidence still required from the Windows installation

The Windows activation, external DLL loading, and executable startup cannot be run on the Linux test host. To validate the actual fix, overlay v0.16.4 on the user's v0.16.3 installation without touching `dependencies/`, run `RUN_WINDOWS_TOOL_AUDIT.bat`, and return `validation/PICADS_v0.16.4_tools_diagnostics.zip`.

**Pass criteria for this hotfix:** both `yosys` and `z3` startup probes pass with no DLL-loader errors. All unrelated existing working tools should remain working. Optional LibreLane and GCC/G++ remain independent installation tasks; physical signoff is NOT verified.
