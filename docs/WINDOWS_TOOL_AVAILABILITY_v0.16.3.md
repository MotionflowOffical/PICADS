# PICADS v0.16.3 — Windows toolchain registration and physical backend

## Why these tools appeared missing

* **pcbnew** is the KiCad PCB layout editor (`pcbnew.exe`). PICADS 0.16.2's KiCad installer registered only `kicad.exe` and `kicad-cli.exe`. It now registers all three when present and can repair an existing installation without downloading KiCad again.
* **Verilator** in Windows OSS CAD Suite may include an extensionless Perl frontend and `verilator_bin.exe`. PICADS can now create a Windows `verilator.cmd` launcher when the native engine and runtime directory are present. The existence of this launcher is **not** a successful compiled C++ simulation test; use the tool audit and RTL validator to confirm it.
* **GCC / G++** are C and C++ compilers, not the PICADS synthesizer. They are needed for some native compiled simulation workflows. An optional **MSYS2 UCRT64** package now installs/registers GCC, G++ and Verilator. The installer uses the official `MSYS2.MSYS2` WinGet package and the official `mingw-w64-ucrt-x86_64-gcc` and `mingw-w64-ucrt-x86_64-verilator` pacman packages. No WSL is needed.
* **OpenROAD**, **Magic**, and **Netgen** are physical IC EDA tools, not standard Windows programs in the PICADS native dependency list. On Windows, PICADS uses the optional **LibreLane WSL2/Docker backend** that bundles and manages compatible versions of those tools. Installing LibreLane is separate from native OSS CAD Suite. A successful container smoke test is not the same as successful PDK-backed DRC/LVS/STA or foundry signoff.

## Updating an existing PICADS installation

1. Exit PICADS.
2. Overlay the v0.16.3 patch on the existing PICADS source directory **without deleting `dependencies/`**. Alternatively use the cumulative ZIP, keeping/copying your existing tool installations and dependency settings.
3. Double-click `REPAIR_WINDOWS_TOOL_REGISTRATIONS.bat`. It re-registers available KiCad tools and repairs the OSS CAD Suite registry **without downloading anything**.
4. If GCC/G++ or Verilator remain absent, open **Settings → Install / Manage Windows Tools** and select **MSYS2 UCRT64 — native GCC, G++ and Verilator**. Installation requires WinGet and internet access, and may take some time. Follow any Windows prompts.
5. Run `RUN_WINDOWS_TOOL_AUDIT.bat`. Upload only `validation/PICADS_v0.16.3_tools_diagnostics.zip` if startup checks fail.

## MSYS2 installation directory caveat

MSYS2 does not support paths containing spaces reliably. If PICADS resides in a directory such as `C:\ChipManuSoftware\PICADS Build`, the WinGet installer uses `C:\msys64` (or the system drive equivalent) for MSYS2, while keeping its registry receipt and helper launcher in `dependencies/msys2-toolchain/`. This is an intentional exception to PICADS's usual managed-dependency directory.

## Verification contract

The dependency audit records **FOUND**, **UNAVAILABLE** and real **startup probe PASS/FAILED** separately. GUI executables (e.g. pcbnew.exe) are not automatically launched by this audit. Physical backend tools are not marked native-Windows-installed just because LibreLane was selected. The real PICADS automatic test launcher remains `RUN_PICADS_AUTOTEST.bat`.

References:
- MSYS2: https://www.msys2.org/
- Native GCC: https://www.mingw-w64.org/getting-started/msys2/
- Verilator MSYS2: https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-verilator
- OpenROAD platform support: https://openroad.readthedocs.io/en/latest/
- LibreLane installation: https://librelane.readthedocs.io/en/stable/installation/index.html
