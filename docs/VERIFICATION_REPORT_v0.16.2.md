# PICADS v0.16.2 — Verified OSS CAD Suite recovery hotfix

## Real-world diagnostic input

The user reports that PICADS v0.16.1 downloaded the official OSS CAD Suite Windows x64 2026-10-12 archive (~544 MiB) and extracted 15,410 files (~2,079 MiB), then failed during the optional `verilator` registration: the registry refused `.../bin/verilator` as a Windows application. In the same run KiCad installed and registered successfully via WinGet.

## Root cause

In `windows_installer.py`, `_find_binary` checked merely that a matching filename existed, including extensionless shell/Python scripts in OSS CAD Suite. Later `register_tool` rejected that script under the Windows executable policy. The old code raised the error after the package had been permanently extracted, resulting in a failed status and no offline retry path.

## Fix and invariants

- Only `.exe`, `.cmd`, `.bat`, and `.com` program paths are accepted during Windows package registration. Unsupported optional `verilator`/`sby` entry points are skipped with a warning; core `yosys`, `iverilog`, and `vvp` must be registered successfully.
- An existing managed package with a PICADS receipt can have its registration reconstructed **offline**. This never redownloads or re-extracts the bundle.
- `REPAIR_OSS_CAD_WINDOWS.bat` and `picads dependencies repair oss-cad-suite` require an existing managed directory. A directory without a PICADS receipt is preserved and refused, not overwritten.
- The GUI checkbox for an existing managed portable package is enabled with a repair label; re-selecting it reuses the existing installation.
- KiCad/other packages are not removed or reinstalled by this repair.

## Executed tests

- Complete Python test suite: **518 passed, 3 skipped** (61.23 seconds; test process run on Linux).
- Focused dependency+GUI/scheduling regression group: **90 passed, 1 skipped**.
- Included explicit regression test reproducing the v0.16.1 version of the `verilator` script failure.
- Included explicit regression test of the offline recovery path with download calls disabled, preserving existing unrelated files.
- Included selection/installer compatibility tests for optional KiCad and LibreLane branches.
- Cumulative source ZIP integrity: flat ZIP, SHA-256 for all listed files, successful clean extraction.
- Small patch replay: overlay hotfix on the unmodified v0.16.1 source ZIP, verify all updated source bytes exactly equal the full v0.16.2 release and `dependencies/` preexisting content survives unchanged.

## What was not executed

- Real native Windows registration/startup of the user's OSS CAD Suite binaries and their Windows `.bat` activation script.
- Real live KiCad WinGet installation or WSL/Docker/LibreLane runs.
- Fabrication PDK-backed place/route/signoff.

Running `REPAIR_OSS_CAD_WINDOWS.bat` on Windows should test registration of the already-installed tools; running `RUN_PICADS_AUTOTEST.bat` should then provide independent actual executable evidence in its diagnostics ZIP. A detected Windows runtime error must be investigated, not inferred as solved merely from these Linux-based tests.
