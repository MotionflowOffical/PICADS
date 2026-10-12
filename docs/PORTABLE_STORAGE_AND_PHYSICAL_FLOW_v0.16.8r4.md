# PICADS v0.16.8r4 — storage lifecycle and physical-layout recovery

## What this release fixes

1. **Safe reclaim/reinstall** for recognized, PICADS-managed Windows portable tools, the PICADS LibreLane Python virtualenv in WSL, and PICADS-scoped caches. This is explicit opt-in removal, not automatic deletion at GUI startup. No user project source or backups are removed.
2. **Guided first real GDS build** via `RUN_SKY130_REFERENCE.bat` or the GUI's Physical Layout tab. Unlike the LibreLane smoke test (an unrelated test design), this compiles a PICADS circuit and attempts the real Yosys → LibreLane → GDSII flow.
3. **WSL project working directory** is converted with `wslpath` for Windows-native PICADS processes and validated as reachable in the chosen distribution before running Yosys/LibreLane. Paths containing spaces are not passed through shell quoting or string interpolation.
4. **GDS visibility:** successful LibreLane runs generate `build/latest/layout_artifacts.json` pointing to the actual GDS under `build/latest/runs/<tag>/final/gds`. It records top and numeric GDS layers but does **not** copy multi-megabyte GDS into a second location. GUI supports `Latest GDS / Mask Layers`.
5. Disabled physical generation now produces a direct `PHYSICAL.DISABLED` diagnostic *before* calling the external tools.

## Get physical layout working

### Quickest Windows check

From the PICADS root double-click **`RUN_SKY130_REFERENCE.bat`**. It copies the bundled `examples/first_physical_chip` into `validation/PICADS_SKY130_DEMO` without replacing an existing demo's files. The script explicitly configures that copied project to use `Ubuntu` and `sky130A`, saves the original `chip.yaml`, runs a preflight, and attempts the full physical build. The PDK and Ubuntu distribution must be available as in the reported LibreLane 80/80 smoke test.

The script does not download/install dependencies. It does not edit your normal PICADS chip projects. Pass the WSL distro name as the first argument if it isn't `Ubuntu`.

If a build fails, upload:

- `validation/PICADS_SKY130_DEMO/build/latest/report.json`
- `validation/PICADS_SKY130_DEMO/build/latest/yosys.log`, if generated
- `validation/PICADS_SKY130_DEMO/build/latest/physical.log`, if generated
- `validation/PICADS_SKY130_DEMO/build/latest/physical_preflight.json`, if generated

The first failing native tool error in those logs is needed to diagnose target-specific issues. The Windows Docker and LibreLane setup logs alone do not provide it.

### Use a different project

Physical Layout → **Configure SKY130 / WSL** in the GUI requests a WSL distribution and explicit confirmation. It updates that project's `chip.yaml` and preserves the prior content at `.chipcompiler/physical_config_backups/`. If `chip.yaml` has unsaved GUI changes it refuses rather than overwriting the buffer. The external flow is started separately by **Run Physical Flow**.

Equivalent PowerShell from inside the PICADS program directory:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3 -m chipcompiler configure-physical 'C:\Path\To\ChipProject' --wsl-distribution Ubuntu
py -3 -m chipcompiler physical-preflight 'C:\Path\To\ChipProject'
py -3 -m chipcompiler physical 'C:\Path\To\ChipProject'
```

The project needs a bounded PICADS-supported digital circuit. The reference is clocked with a nominal `CLOCK_PERIOD` of 20 ns. A `PARTIAL` preflight from an omitted PDK root does not automatically mean failure; LibreLane can resolve the PDK from its managed Ciel installation. An actual `BLOCKED` or `UNAVAILABLE` check must be resolved.

**Meaning of “mask”:** the real `*.gds` contains hierarchical layout data and process-numbered layers. It is useful for IC mask design and for display in KLayout; a foundry-approved photomask set, process-specific layer processing, DRC/LVS/antenna closure, PDK qualification, and tape-out are distinct requirements. The current reference uses the SKY130 digital standard-cell PDK, NOT the proposed custom TFT materials and 40 µm experimental process.

## Reclaim disk space safely

In GUI, open Settings → External Dependencies → **Storage / Uninstall / Cleanup...**. The dialog scans in the background, shows estimated bytes, requires selection and then shows the exact paths for confirmation. All entries are unchecked by default. The user may reinstall the removed managed packages using the original installer.

CLI read-only inventory:

```powershell
py -3 -m chipcompiler dependencies storage --project-root 'C:\Path\To\ChipProject'
```

Preview (does not delete anything):

```powershell
py -3 -m chipcompiler dependencies uninstall oss-cad-suite
py -3 -m chipcompiler dependencies cleanup project:build-history --project-root 'C:\Path\To\ChipProject'
```

Repeat with `--apply` to explicitly perform selected removals. Multiple IDs can be comma-separated. A removed `build/latest` or `build/history` directory is **generated output**, not source; important GDS should be exported/backed up before selecting those entries.

### Reclaimable categories

| Managed item | Removal | Reinstall or regenerate |
|---|---|---|
| OSS CAD Suite and KLayout | Only recognized PICADS portable install directories bearing matching receipts | Install / Manage Windows Tools |
| PICADS LibreLane virtualenv inside Ubuntu | Only `$HOME/.local/share/picads-librelane/venv`, confirmed by a matching LibreLane smoke-test receipt | Run original LibreLane guided setup again |
| PICADS pip download cache | Only future-installer-scoped `$HOME/.cache/picads-librelane-pip` | Recreated on next pip install |
| Docker Desktop **installer download cache** | Only `dependencies/librelane/docker-installer-cache` | Re-download only if a reinstall is needed |
| Interrupted PICADS install staging | Only expected staging names older than 24 hours | Next installation generates fresh staging |
| Python bytecode caches | Only known PICADS source package locations | Python regenerates them |
| Current and historical project builds | Only a selected project with recognized `build/latest` and PICADS-formatted `build/history` entries | Run compiler/EDA again |
| KiCad installed *by PICADS through WinGet* | Explicit WinGet uninstall of package `KiCad.KiCad`, which may affect other projects | Install / Manage Windows Tools |

### Intentionally excluded

- **Docker Desktop itself, images and volumes:** potentially shared by unrelated software. A LibreLane container image may also be shared. No `docker system prune`, reset, or uninstallation is performed.
- **Ubuntu/WSL distributions:** PICADS never executes `wsl --unregister`.
- **Sky130/Ciel PDKs under `~/.ciel`:** shared process technology assets; no automated removal in this release.
- **MSYS2, Python global packages, unrelated WinGet installations and user-selected custom tool folders:** no automatic deletion.
- **Project source, `.chipcompiler` recovery snapshots, file backups and arbitrary directories:** preserved.

Installed size estimates are not promised filesystem-recovery amounts, particularly with shared Docker/WSL virtual disks. Removing files *inside a WSL VHDX* may not immediately shrink the Windows host's VHDX; compaction is a separate operation and is deliberately not attempted automatically here.

## Verification scope

The regression suite includes fixed-path and mocked Windows/WSL invocations, filesystem safety tests, GUI presence checks, temporary PICADS project compilations, and a mocked external LibreLane run that returns a real structurally parseable GDS file. Actual WSL, Docker and LibreLane are **not available inside this build environment**, so a complete PICADS-authored hardware place-and-route remains unverified until `RUN_SKY130_REFERENCE.bat` runs on the user's system.
