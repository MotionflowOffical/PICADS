# PICADS v0.16.6 — Existing WSL distribution detection fix

## Problem corrected

The generated `dependencies/librelane/SETUP_LIBRELANE_WINDOWS.bat` in earlier releases used `wsl.exe --list --quiet | findstr /i "Ubuntu"` and assumed the distro was called exactly `Ubuntu`. On Windows, WSL can produce UTF-16 output that `findstr` does not reliably handle. Existing distributions such as `Ubuntu-24.04` were not handled. PICADS incorrectly called `wsl --install -d Ubuntu`, which failed with `Wsl/InstallDistro/ERROR_ALREADY_EXISTS`.

## Fix

- A staged `DISCOVER_WSL_DISTRO.py` helper reads WSL's UTF-16LE/UTF-8 output, ignores Docker's internal distributions, and probes the Linux shell in each installed distribution.
- The installer reuses a runnable distribution, preferring `Ubuntu`, then versioned Ubuntu distributions, then Debian and other installed Linux distributions.
- If one or more user distributions exist but none can be launched, it **stops with an explanation** rather than attempting an unnecessary reinstallation.
- Only if no user Linux distribution is present will it request a new Ubuntu installation.
- The chosen distribution is recorded under `dependencies/librelane/wsl_distribution.txt` and used for subsequent setup commands.
- The console retains its interactive nature. WSL initialization, Docker Desktop's WSL integration, Linux `sudo`, and the LibreLane smoke test may still require your involvement. **SETUP_STARTED is not success.**
- The installer only creates a backend success marker after the actual LibreLane smoke test succeeds.

## How to apply the patch

1. Close PICADS.
2. Extract `PICADS_v0.16.6_WSL_Installer_Fix_Patch.zip` over your existing PICADS v0.16.5 installation, replacing matching source files.
3. **Do not delete `dependencies/` or reinstall Ubuntu.** Your existing WSL distro and downloaded Windows EDA tools remain untouched.
4. Restart PICADS. Open Settings → Install / Manage Windows Tools → select LibreLane → Install Selected.
5. The regenerated setup console should say `Reusing WSL distribution: Ubuntu` (or your actual installed distro name). It will then check Docker Desktop and continue with LibreLane setup.
6. If your installed distribution isn't initialized, open it once in Windows Terminal and finish its account setup. You can check installed names with `wsl --list --verbose` in PowerShell.

The actual Windows Docker/LibreLane installation has **not** been run in the release build environment. The detection logic has unit tests for UTF-16 output, versioned distro names, no distro, uninitialized distro, and user-selected distro.

### Important note about PICADS physical builds

After the smoke test passes, ensure your PICADS project has `tools.execution: wsl` and `tools.wsl_distribution` equal to the selected distro name (found in `dependencies/librelane/wsl_distribution.txt`). Real physical generation additionally requires a PDK and end-to-end flow validation; the installer does not constitute physical-design signoff.
