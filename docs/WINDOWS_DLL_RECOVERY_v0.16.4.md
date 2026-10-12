# PICADS v0.16.4 — Windows DLL launch recovery

## Root cause confirmed from the uploaded v0.16.3 diagnostic ZIP

The October 12 Windows audit showed:

| Executable | Result | Interpretation |
| --- | --- | --- |
| `yosys.exe` | `3221225781` (`0xC0000135`) | Windows couldn't locate at least one dependent DLL |
| `z3.exe` | `3221225785` (`0xC0000139`) | A dependent DLL lacked an expected entry point, often a DLL version conflict |
| `iverilog.exe`, `vvp.exe`, `verilator.cmd` | PASS | OSS CAD Suite extraction is at least partially functional |
| `kicad-cli.exe`, `klayout_app.exe` | PASS | Already usable |
| `pcbnew.exe` | FOUND (not launched by headless audit) | Installed and registered; GUI startup untested |
| `gcc`, `g++` | UNAVAILABLE | A separate optional MSYS2 package can supply these |
| `openroad`, `magic`, `netgen`, LibreLane | NOT VERIFIED | Optional WSL2/Docker physical-design backend |

The audit independently recorded that invoking the OSS CAD Suite `environment.bat` failed because a path containing **`PICADS Build`** was improperly quoted. The old PICADS child environment also prepended **all** registered software directories, including KiCad and KLayout, before the OSS CAD Suite directory. That allows unrelated DLLs with identical names to be loaded. These are PICADS bugs; the evidence does not justify downloading OSS CAD Suite again.

## What v0.16.4 changes

1. **Batch activation:** Launch the managed OSS CAD Suite activation script using a temporary `.cmd` file; `cmd /d /s /c` receives only a fully quoted script name. Temporary files are deleted in success and failure cases.
2. **Per-tool DLL environment:** Yosys, Icarus, Z3, SymbiYosys and Verilator share the OSS CAD Suite environment, but do not receive KiCad or KLayout DLL directories. KiCad, KLayout and MSYS2 tools use their own executable directories. Ordinary PICADS GUI and Python processes keep a neutral environment.
3. **Independent tool testing:** Each startup probe is launched with its own environment rather than a shared global PATH. Windows loader errors include the signed exit code, hexadecimal code, and a human-readable category.
4. **Noninteractive audit:** The audit attempts to disable Windows loader error pop-up dialogs during each subprocess version probe, then restores Windows error-mode settings.
5. **Native execution:** PICADS build and validation paths use the same tool-scoped environment as the dependency audit.

### Applying the hotfix without reinstalling tools

1. Close PICADS.
2. Extract `PICADS_v0.16.4_Windows_DLL_Hotfix_Patch.zip` **over your existing PICADS v0.16.3 application folder** and allow changed source files to be replaced.
3. **Do not delete or move the `dependencies/` directory**. The patch deliberately contains no installed third-party binaries or package folders.
4. Double-click **`RUN_WINDOWS_TOOL_AUDIT.bat`** in the PICADS root.
5. Upload **`validation/PICADS_v0.16.4_tools_diagnostics.zip`**. We need to see `yosys` and `z3` startup probes passing after the change. `NOT_RUN` for GUI tools and `UNAVAILABLE` for tools you did not install are expected.
6. If Yosys and Z3 now pass, run **`RUN_PICADS_AUTOTEST.bat`** for full PICADS feature verification.

### If Yosys or Z3 still fails

The new ZIP records which runtime directories were used and the precise Windows loader status. Do **not** download individual DLLs from DLL aggregation websites or copy DLLs between KiCad, MSYS2, and OSS CAD Suite directories: that can cause exactly the entry-point problem reported. If the program continues to fail in the correct environment, the next investigation should identify the **actual DLL filename and build/runtime requirements** for the installed Windows OSS CAD Suite revision. A Microsoft Visual C++ runtime may be necessary for some native builds, but it should only be installed after a confirmed dependency is identified.

The solution has been tested using controlled subprocesses and DLL-failure codes in Linux, not with the actual Windows binaries. The Windows audit is the required final verification.
