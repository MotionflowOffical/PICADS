# PICADS v0.16.0 — Windows-native dependency architecture

## Design principle

PICADS targets Windows 10/11. The GUI, Python source frontend, CO/MCD scheduler, gate-level DLS, logic simulator, and RTL generation run directly in Windows Python. Installing Linux or WSL is **not** required for these operations.

Native tool installation is optional and always opt-in. Opening PICADS or a project never downloads or executes an installer automatically.

## Setup through the GUI

1. Run `RUN_GUI.bat` and open **Settings**.
2. Click **Install / Manage Windows Tools...**.
3. Select one or both checkboxes: **OSS CAD Suite** and **KLayout**. Both start unchecked. Installed tools are indicated in the dialog. A managed installation with missing files is flagged as damaged and is never silently overwritten. Optional tools absent from a bundled suite are not incorrectly treated as proof that the entire install failed.
4. Click **Install Selected**. A worker thread downloads the official portable Windows archive, extracts it under the PICADS `dependencies/` folder, records the SHA-256 and release URL, and registers supported executables.
5. Review the output and use **Refresh tool status**. Existing **Choose App**, **Choose Folder**, and **Clear** controls remain supported.

The default folder is `PICADS/dependencies/`. For custom writable paths (e.g. a Program Files installation) use the `PICADS_DEPENDENCY_ROOT` environment variable. Registered executable paths are stored in the existing per-user registry under `%APPDATA%/PICADS/dependencies.json`.

## Tool support

| Component | Windows mode | Purpose | Status |
| --- | --- | --- | --- |
| PICADS Python/Qt | Native Windows | Editor, compiler, simulator, CO/MCD, DLS, generated Verilog | Native |
| OSS CAD Suite (Windows x64 archive) | Portable | Yosys, Icarus/vvp, Verilator, and available formal tools | Opt-in installer |
| KLayout (Windows ZIP) | Portable | View and inspect GDS/OASIS; DRC where applicable rule decks exist | Opt-in installer |
| KiCad | Separate optional Windows application | PCB companion; **not IC place-and-route** | Manual registration/download page |
| LibreLane/OpenROAD ASIC flow | Optional WSL2/Docker backend | Actual ASIC standard-cell placement/routing | **Not a native-Windows install** |
| Foundry PDK and signoff | Process-specific | Technology mapping, rules, extraction, timing, DRC/LVS | Not automatically provisioned |

The OSS CAD Suite upstream supplies a `windows-x64` build and requires activating its `environment.bat`. PICADS uses that environment only for external child processes, never permanently changes the user's PATH. The download receipt explicitly states whether an upstream SHA-256 digest was available for verification; always treat an unverified digest as unverified.

**Critical limitation:** OSS CAD Suite's `nextpnr` is for FPGA implementation, not a drop-in replacement for OpenROAD/LibreLane's ASIC place-and-route flow. A successful Yosys run is not a manufacturable mask. The final ASIC physical flow still depends on a supported backend and a suitable PDK. WSL2/Docker are optional for using PICADS but currently needed to run the integrated LibreLane-based physical flow on Windows. No unsupported native Windows OpenROAD binary is downloaded or presented as verified.

## Command-line alternative

```bat
set PYTHONPATH=%CD%\src
py -3 -m chipcompiler dependencies catalog
py -3 -m chipcompiler dependencies install oss-cad-suite
py -3 -m chipcompiler dependencies install klayout
py -3 -m chipcompiler dependencies list
```

Dependencies are registered immediately upon validated extraction. Existing installation folders are never silently overwritten. To reinstall, remove the old managed package folder deliberately, then run the installer again. Only the requested group is downloaded. Tool activation failures are surfaced in build logs.

## Security and failure behavior

- Only official HTTPS release hosts and redirects are accepted.
- Downloads have size limits and are streamed to temporary files.
- Archive traversal, absolute paths, and unsafe entry types are rejected.
- Temporary extraction is kept isolated; executable paths are checked before registration.
- No downloaded executable or script is run during installation.
- Download SHA-256 is recorded; upstream hash is verified when release metadata includes it.
- No hidden elevation, WSL installation, Docker installation or global PATH mutations.
- Packages requiring Linux/WSL are listed as optional integration paths with links to official setup guidance, not falsely presented as downloadable native Windows executables.
- A missing binary or missing compatible native version returns an explicit failure with manual-selection fallback, not a synthetic PASS.

## Verification status

The installer is tested here using local stand-in OSS CAD Suite and KLayout archives, malicious archive fixtures, mocked downloads, managed-install status checks, settings isolation, and CLI checks. A live Windows download and Qt runtime need testing on the user's Windows PC. Native EDA functionality and PDK-backed physical design remain independently unverified until those tools run successfully.

Upstream sources: <https://github.com/YosysHQ/oss-cad-suite-build>, <https://www.klayout.de/build.html>, and <https://librelane.readthedocs.io/en/stable/installation/index.html>.
