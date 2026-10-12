# PICADS v0.16.3 — Windows dependency compatibility verification

## Implemented fixes

1. KiCad now discovers and registers `pcbnew.exe` alongside `kicad.exe` and `kicad-cli.exe`; offline repair does not reinstall KiCad.
2. OSS CAD Suite offline repair recognizes optional native GCC/G++ if bundled and can create a Windows `.cmd` launcher around `verilator_bin.exe` if the upstream Verilator runtime directory is present. An absent native engine is **not** reported installed.
3. Added explicit opt-in **MSYS2 UCRT64** toolchain installation through WinGet plus official pacman packages for GCC, G++, and Verilator; no WSL needed. On space-containing PICADS installation paths the MSYS2 installation may be placed in `C:\msys64` with its registration receipt under PICADS `dependencies/`.
4. OpenROAD, Magic, and Netgen are now labeled as **LibreLane WSL2/Docker backend tools** in GUI Settings rather than advertised as missing ordinary native Windows executables.
5. Added a scrollable installer UI, an offline repair launcher, and a read-only dependency audit that packages results in a single ZIP.

## Tests

- Focused Windows dependency and regression tests: **39 passed** under Linux using simulated WinGet and pacman operations.
- Full Python regression suite: **527 passed, 3 skipped, 0 failed** (49.41 seconds); skip reasons include unavailable GUI/native tool runtimes.
- `windows_tool_audit` ran and its ZIP passed `zipfile` integrity checks; the report distinguishes available paths from actual startup probes.
- Actual online MSYS2 installation, actual Verilator execution and native GUI runtime: **NOT RUN** in this environment.
- The upstream OpenROAD/Magic/Netgen backend and PDK-dependent manufacturing checks: **NOT VERIFIED**. None of the above tests provide fabrication signoff.

## Safety and integrity

- Package selection is explicit; nothing is downloaded on GUI startup.
- Offline repair preserves the existing managed OSS CAD Suite and KiCad installation.
- MSYS2 installer uses a fixed upstream WinGet package ID and fixed official pacman package names, never arbitrary downloaded commands.
- Missing/failed packages produce SETUP_REQUIRED or FAILED rather than INSTALLED.
- External EDA software is never embedded in this source-only ZIP.

## Windows diagnostic instructions

1. Overlay the v0.16.3 source patch on v0.16.2, without deleting `dependencies/`.
2. Run `REPAIR_WINDOWS_TOOL_REGISTRATIONS.bat` (offline).
3. Optionally use **Settings → Install / Manage Windows Tools → MSYS2 UCRT64** for GCC/G++/Verilator.
4. Run `RUN_WINDOWS_TOOL_AUDIT.bat` and upload `validation/PICADS_v0.16.3_tools_diagnostics.zip`.
5. For end-to-end application verification, separately run `RUN_PICADS_AUTOTEST.bat`.
