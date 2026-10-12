# PICADS v0.16.1 — Selectable KiCad and LibreLane installers

## The reported problem

PICADS v0.16.0 displayed KiCad and LibreLane in **Settings → Install / Manage Windows Tools**, but intentionally disabled both checkboxes because the first installer only implemented portable Windows archives. This prevented choosing either program. The behavior has changed in v0.16.1.

## What to do on Windows

1. Open `RUN_GUI.bat` → **Settings** → **Install / Manage Windows Tools**.
2. All four entries are now selectable and **unchecked by default**.
3. Select **KiCad** to request its signed package from the Windows Package Manager (WinGet ID `KiCad.KiCad`). PICADS requests an installation at `dependencies/kicad/application`, but the official installer can ignore this path or require administrator approval. PICADS checks the actual installed executables before registering them. It does not invent a successful install when they cannot be located. See `dependencies/kicad/winget_install.log` if it fails.
4. Select **LibreLane** for the **guided WSL2 / Docker Desktop** route, the upstream-supported Windows method. The GUI asks for explicit confirmation before opening the separate setup console. The console checks WSL2 Ubuntu and Docker Desktop, attempts to install missing components through Microsoft/WinGet, installs LibreLane in an Ubuntu Python virtual environment, then attempts the official dockerized smoke test. It may require elevation, a reboot, Docker's first-run configuration, WSL integration, and an Ubuntu username/password or sudo password. The console prompts for these. This is **not a native Windows executable**.
5. If you must reboot, re-run `dependencies/librelane/SETUP_LIBRELANE_WINDOWS.bat` afterwards. Successful completion creates `dependencies/librelane/backend_smoke_passed.txt`. A marker alone is not independent verification of a full physical run.
6. After a completed WSL setup, configure the PICADS **project's** `chip.yaml` for physical operations:

   ```yaml
   tools:
     execution: wsl
     wsl_distribution: Ubuntu
   physical:
     dockerized: true
   ```

   Keep the project's existing `physical.pdk` and PDK settings, and use an actual compatible PDK. WSL operation in a live physical run is **not validated in this release**; the launcher and installer are prepared for testing on Windows.

## Key distinctions

| Tool | Windows path | Installed where? | Is it chip physical design? |
| --- | --- | --- | --- |
| OSS CAD Suite | Official portable Windows archive | `dependencies/oss-cad-suite` | RTL/synthesis; not ASIC place-and-route |
| KLayout | Official portable Windows archive | `dependencies/klayout` | Layout viewer, and rule-deck-dependent checks |
| KiCad | WinGet installation | PICADS **requests** `dependencies/kicad/application`; installation may be system-wide | **No**, KiCad is PCB design |
| LibreLane | Guided WSL2 Ubuntu + Docker Desktop setup | Setup launcher under `dependencies/librelane`; actual binaries **inside Ubuntu/Docker** | Yes, with a supported PDK and full toolchain |

**Do not assume that a selectable box guarantees that installation will succeed unattended.** WSL2 and Docker setup cannot generally avoid all Windows/UAC, Linux account, first-run and restart interactions.

The GUI editor, compiler, DLS simulator and structural Verilog generator do **not** require WSL, Docker, KiCad, or LibreLane.

## Testing and troubleshooting

- Run `RUN_PICADS_AUTOTEST.bat` and send the single diagnostics ZIP from `validation/`.
- If KiCad installation fails, send `dependencies/kicad/winget_install.log` or use Settings → Choose App / Choose Folder for an existing KiCad installation.
- If LibreLane setup stalls, complete Ubuntu's first-run prompts or start Docker Desktop, enable **Settings → Resources → WSL Integration → Ubuntu**, and re-run the prepared batch script.
- PICADS never counts a launched LibreLane setup as a completed installation. The result is `SETUP_STARTED` / overall `PARTIAL` until successful smoke-test evidence exists.

Upstream documentation: [KiCad for Windows](https://www.kicad.org/download/windows/), [Microsoft WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/install), [LibreLane Windows Docker instructions](https://librelane.readthedocs.io/en/stable/installation/docker_installation/installation_win.html).
