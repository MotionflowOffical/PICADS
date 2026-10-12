# PICADS v0.16.2 — OSS CAD Suite Windows registration hotfix

## Actual Windows failure addressed

The v0.16.1 Windows installer successfully downloaded the official `oss-cad-suite-windows-x64-20261012.tgz` archive (approximately 544 MiB) and extracted approximately 2 GiB, then failed with:

```
ERROR oss-cad-suite: verilator was not found at ...\oss-cad-suite\oss-cad-suite\bin\verilator.
Select the application executable. No setting was changed.
```

**Root cause:** The mixed-platform distribution has optional extensionless launcher scripts. The previous installer discovered `verilator` by filename alone and called the registry with it, but the Windows registry intentionally accepts only `.exe` / `.cmd` / `.bat` / `.com` files. This optional tool then caused the entire package to be reported FAILED, even though core tools had already been installed and the archive was intact.

**Fixes:**

1. Scan only launchable Windows binary/script extensions. Prefer native Windows programs over extensionless POSIX shell wrappers, and do not register an unusable optional script.
2. Validate and register **required** `yosys.exe`, `iverilog.exe`, and `vvp.exe` first. Optional tools, where properly launchable, are registered afterwards. Optional failures are logged and skipped; they do not invalidate the core tools.
3. If a PICADS-managed extracted suite and receipt are already present, re-register tools **offline** in place. There is no re-download, re-extraction or manual deletion of the 2 GiB directory. The original archive's SHA-256 in the receipt remains recorded; the repair does not re-check downloaded bytes.
4. The GUI offers **Install/Repair** for existing managed portable installations, and the CLI exposes `dependencies repair oss-cad-suite`.
5. Unsafe/unrecognized existing directories without a valid managed installation receipt remain untouched; no automatic overwrite occurs.

## Instructions for existing v0.16.1 installations

**Do not delete** `dependencies/oss-cad-suite` or `dependencies/kicad`. No additional 544 MiB download is necessary.

1. Exit PICADS.
2. Download the **v0.16.1-to-v0.16.2 hotfix patch** and extract it directly into your existing PICADS application root, allowing source files to be replaced. It does not include a `dependencies/` folder or modify your installed tools.
3. Double-click **`REPAIR_OSS_CAD_WINDOWS.bat`**. It runs `picads dependencies repair oss-cad-suite` and uses only the existing installation.
4. Reopen PICADS and check **Settings → External Dependencies**. `yosys`, `iverilog`, and `vvp` should now resolve to `...\dependencies\oss-cad-suite\oss-cad-suite\bin\*.exe`.
5. Run `RUN_PICADS_AUTOTEST.bat` and upload `validation/PICADS_v0.16.2_automated_diagnostics.zip` for independent verification. It should check the real binaries on Windows where available.

Alternative: In Settings → Install / Manage Windows Tools, tick **OSS CAD Suite** again and click Install Selected. PICADS will repair the managed directory rather than download it. This requires the existing PICADS installation receipt.

## Normal/failing outcomes

- **PASS / INSTALLED, repaired:true:** The managed directory was detected, core Windows binaries were found and re-registered.
- **Optional Verilator or SBY skipped:** Not an installation failure. An extensionless script is not a directly launchable Windows application. PICADS does not claim Verilator or SymbiYosys is usable until a Windows launcher is found and registered.
- **Missing core executable:** Repair fails with a specific error; it does not remove downloaded content. Upload the console message and installation receipt for diagnosis.
- **KiCad INSTALLED:** The earlier KiCad success is independent of this OSS CAD Suite registration issue.

This hotfix is verified by offline regression tests, including an exact simulated v0.16.1 failure and offline recovery. Actual Windows executable startup still requires running the diagnostic tests on the user's Windows computer. External RTL / synthesis / physical signoff are not asserted by registry success.
