# PICADS v0.16.8r3 — recognize successful LibreLane WSL smoke test

## Confirmed case

On 2026-10-12, the Windows 10 user reported a *real* LibreLane Dockerized
SKY130 smoke test completing 80/80 steps, including DRC, LVS, and antenna.
This proves the separately installed LibreLane backend ran successfully inside
Ubuntu at that time. It does **not** demonstrate that an arbitrary PICADS chip
has completed place and route.

The UI's Windows dependency registry still called LibreLane `UNAVAILABLE`,
because it looked for a native Windows `librelane.exe`. The actual installation
is the Python module at
`$HOME/.local/share/picads-librelane/venv/bin/python -m librelane` in Ubuntu.

## Fixed paths

- `src/chipcompiler/wsl_backend.py` checks the recorded smoke receipt and distro
  separately from current live executable reachability. Runtime diagnostic
  checks WSL Yosys, WSL Docker, and the PICADS-managed LibreLane venv. No
  downloads, updates, deletions, or service restarts occur during probes.
- GUI → Settings → External Dependencies: the LibreLane row shows
  `INSTALLED [WSL: Ubuntu] LibreLane smoke-test PASS` when the matching
  successful receipt exists, rather than reporting it as missing on Windows.
  The status text accurately identifies **historical** evidence, not a new
  complete flow run. Native Windows OpenROAD/Magic/Netgen do not become
  standalone registered Windows executables.
- CLI `picads doctor` adds live `librelane_wsl_backend` information. CLI
  `picads dependencies list` includes recorded status, and
  `picads dependencies wsl-status` explicitly performs read-only live probes.
- CLI and GUI `physical-preflight` now check project-selected WSL backend
  rather than always requiring Windows-native Yosys/LibreLane.
- `pipeline.py` checks relevant WSL prerequisites before the LibreLane step,
  preserves precise unavailable status, and leaves an explicit `pdk_root`
  unchanged when supplied as a **Linux** filesystem path.
- The first-chip acceptance runner accepts `--execution auto|native|wsl`
  (`auto` defaults to WSL only for a recorded and live-working managed backend),
  plus `--wsl-distribution`; it now copies backend settings into its temporary
  test projects. Linux WSL default PDK path comes from Ciel, not from the
  Windows selected-PDK setting.
- A launcher `CHECK_LIBRELANE_WSL.bat` presents live diagnostics in a separate
  console with no installation operations.

## Install (non-destructive)

Close the PICADS GUI. Extract the patch ZIP **over the existing PICADS root**
`C:\ChipManuSoftware\PICADS Build`, replacing matching source scripts only.
Do **not** delete `dependencies/`; it contains your smoke-test receipt and
staged installer scripts. The patch ZIP has no top-level wrapping folder and
no `dependencies/`, `build/`, `.chipcompiler/`, PDK, Docker or WSL contents.

Open `CHECK_LIBRELANE_WSL.bat` or run from PowerShell at the PICADS root:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3 -m chipcompiler dependencies wsl-status
```

Expected result: `"status": "READY"`, `"distribution": "Ubuntu"`, and
`"checks"` with PASS for `yosys`, `docker`, and `librelane`. If this instead
reports `UNAVAILABLE`, inspect the per-tool detail. This is a current runtime
probe and not the 80-stage LibreLane flow.

For each PICADS project requiring synthesis and physical implementation, set
in its **existing** `chip.yaml` (merge with, do not replace other sections):

```yaml
tools:
  execution: wsl
  wsl_distribution: Ubuntu
physical:
  enabled: true
  pdk: sky130A
  clock_period_ns: 20
  core_utilization: 35
  timeout_s: 5400
```

The physical sample assumes a clocked design and a supported SKY130 digital
standard-cell library, not the user's custom experimental TFT process. For
unclocked designs, clock-related settings may differ. Leave out `pdk_root`
when using LibreLane's Ciel-managed default in Ubuntu. If explicitly providing
`pdk_root` in a WSL project, use an **absolute Linux path accessible to Ubuntu**,
e.g. `/home/<linux-user>/...`, not `C:\...`. A separate Windows selected-PDK
folder does not automatically translate to a WSL physical PDK installation.

Then run `Physical Preflight` (GUI) or:

```powershell
py -3 -m chipcompiler physical-preflight "C:\path\to\your\project"
```

If `pdk_root` is unselected, preflight can remain `PARTIAL` with a recorded
`UNVERIFIED` PDK root while runtime tools all pass; LibreLane may resolve its
PDK with Ciel during an actual physical run. Do not equate this preflight to
signoff.

For the first-chip automatic physical acceptance with live WSL toolchain:

```powershell
py -3 -m chipcompiler.acceptance --execution wsl --wsl-distribution Ubuntu --skip-gui
```

The runner invokes the real toolchain and leaves an evidence ZIP. Native
Icarus is a separate optional prerequisite. Missing WSL Icarus is reported
UNAVAILABLE rather than assumed available because it exists on Windows.

## Verification limits

- Unit tests use *mocked* WSL processes, receipt records, Docker and tools;
  no live Windows/WSL toolchain was accessible in this development container.
- New and adjacent preflight/GUI/installer tests passed on Linux; no actual
  Windows PySide6 GUI interaction or PICADS-driven reference GDS was verified.
- A successful Dockerized LibreLane smoke test validates only that test design
  on its reference PDK; custom TFT/analog fabrication remains a separate task.
