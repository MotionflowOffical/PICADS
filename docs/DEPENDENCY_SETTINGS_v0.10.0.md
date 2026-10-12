# PICADS v0.10.0 — External dependency and technology configuration

## GUI controls

Open **RUN_GUI.bat**, select **Settings**, then scroll to **External Dependencies**.
Each tool has the following controls:

- **Choose App:** select the exact executable (`yosys.exe`, `kicad-cli.exe`, `klayout_app.exe`, `iverilog.exe`, `vvp.exe`, etc.). Registration checks that the executable name matches the selected tool and exists.
- **Choose Folder:** select the installation directory or the tool's `bin` folder. PICADS searches only bounded conventional subdirectories; it does not recursively enumerate a whole disk. Selecting the root of `C:\Program Files\KiCad\9.0` works for `kicad-cli.exe` if present in `bin`.
- **Clear:** remove a saved path, restoring automatic PATH discovery.
- **Refresh tool status:** revalidate the current selections.
- **Auto Detect Installed Tools:** try PATH and recognized Windows installation roots, and save discovered paths. Existing explicit selections, including broken ones, are preserved rather than silently overwritten.
- **Choose PDK Folder:** separately register a custom PDK directory for *read-only file inventory*, without claiming the PDK is electrically or manufacturing qualified.

Statuses show `AVAILABLE [registered]`, `AVAILABLE [PATH]` or `UNAVAILABLE` with a specific reason. Selecting an incompatible folder does not overwrite a working selection. Registration is stored **per user/per computer**, not in a project's source files:

- Windows: `%APPDATA%\PICADS\dependencies.json` (when APPDATA exists)
- Linux: `~/.config/picads/dependencies.json`
- Test/portable override: set `PICADS_SETTINGS_DIR` to an isolated settings directory.

A selected native executable is used by the build runner and external RTL checks, and its containing directory is temporarily prepended to **child-process** PATH for additional tools launched by SymbiYosys/LibreLane. PICADS does not modify your system PATH.

KiCad is a **PCB schematic/layout tool**. Registering it helps integrate a separately installed KiCad, but does not make KiCad an ASIC physical backend, custom-TFT process technology mapper, or foundry signoff system.

## CLI equivalents

```powershell
python -m picads dependencies list
python -m picads dependencies auto
python -m picads dependencies set kicad-cli "C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"
python -m picads dependencies set yosys "C:\oss-cad-suite\bin" --folder
python -m picads dependencies set klayout "C:\Program Files\KLayout" --folder
python -m picads dependencies clear yosys
python -m picads doctor
python -m picads pdk inspect "C:\my-custom-pdk"
python -m picads pdk set "C:\my-custom-pdk"
python -m picads pdk status
python -m picads pdk clear
```

**Important:** Native Windows paths do not automatically locate binaries inside a separate WSL Linux filesystem. The existing `tools.execution: wsl` selection still requires working WSL and Linux-side tool installation. A native tool registration is not a Linux executable registration.

## PDK inventory limits

The PDK inventory enumerates candidate `.lef`, `.lib`, `.gds`, `.lydrc`, LVS and layer-map files to a bounded depth and count. **`INVENTORIED` indicates only file presence, not correctness or compatibility**. Electrical models, cross-corner libraries, netlists, geometry decks, via stacks, routing rules and fabrication permissions must be configured and independently qualified. The selected inventory directory is not silently applied to `physical.pdk`; the physical implementation remains explicit in `chip.yaml`.

## One-command Windows diagnostics

Run **`RUN_FULL_VALIDATION.bat`** from the extracted project root. It collects the selected tool paths, probes native installed KiCad CLI, KLayout and OpenROAD (if available), runs the compiler suite and representative projects, checks RTL/formal/physical flows where supported, and generates `validation/PICADS_v0.10.0_diagnostics.zip`. The original user projects are not modified. Unavailable external tools are recorded as `UNAVAILABLE` instead of `PASS`. For fabrication validation, a real qualified PDK and physical project must be supplied independently.
