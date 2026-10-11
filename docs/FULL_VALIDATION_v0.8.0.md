# One-command Windows integration tests

## Easiest workflow

1. Extract the complete v0.8.0 ZIP directly into a folder, e.g. `C:\ChipCompiler`.
2. Double-click **`RUN_FULL_VALIDATION.bat`**. It explicitly announces and installs the Python GUI/test dependencies into the current Python environment if needed. It does not install semiconductor EDA programs, PDKs, or modify your own chip projects.
3. When it finishes, locate `validation\ChipCompiler_v0.8.0_diagnostics.zip` in the extracted folder.
4. Send **that single diagnostic ZIP** back in this conversation. Do not copy only the last CMD error line; the useful cause IDs and native logs are in the ZIP.

The script does not silently retry broken commands with a different implementation. It records which tool was actually selected. `UNAVAILABLE` means the named external dependency was missing; `NOT_REQUESTED` means a PDK-backed physical run was not authorized/configured. Those are not passes.

If your external tools are installed only under WSL2, the runner probes WSL and selects it when its required executables can be found, otherwise preserves the missing-tool result. You can force a backend using `RUN_FULL_VALIDATION.bat --rtl-runner native` or `... --rtl-runner wsl`.

## Optional actual physical run

If you already have a valid PDK-backed Chip Compiler project configured for LibreLane, use:

```bat
RUN_FULL_VALIDATION.bat --physical-project "C:\Path\To\MyChipProject"
```

The validation runner copies the project before building, so it does not rewrite the original. Without a real PDK / standard-cell library, actual placement-and-routing and fabrication signoff cannot be tested merely by running a Python command.

## What's in the report

| Report stage | Actual operation |
| --- | --- |
| `compiler_pytest` | Full regression tests, including deliberate invalid and corrupted circuits |
| `qt_gui_smoke` | Starts real PySide6 offscreen GUI, checks window and recovery controls |
| `build_*` | Fresh isolated example compilation and generated reports |
| `dls_fabric_builtin/external` | Directed and independent randomized protocol tests |
| `rtl_fabric_builtin/external` | Compiles and runs Verilog with **actual** installed Icarus (`iverilog`/`vvp`), compares cycle-by-cycle to executable DLS |
| `yosys_real_synthesis` | Actual Yosys run and check of expected synthesized output |
| `physical_flow` | Only if a PDK-backed project was provided; attempts actual physical flow |

Each subprocess receives an explicit timeout and its full output goes to a stage-specific log. `summary.json` distinguishes `PASS`, `FAIL`, `TIMEOUT`, `BLOCKED`, `UNAVAILABLE`, and `NOT_REQUESTED`. Where available, native tool output is copied into `logs/` and cross-linked from the build report. Internal core test success does not imply GUI or mask-flow readiness.

The diagnostic archive includes OS version, Python version, tool discovery paths, generated test reports, logs and deterministic seeds/counterexamples. Review it before sharing if machine paths or other environment details are sensitive. Your personal source files are not included by default.

## If Python is unavailable

Python 3.10 or later must already be installed for the batch launcher to work. If no Python launcher is detected, the batch script reports that original dependency failure and exits. It does not pretend to have tested any part of the application.
