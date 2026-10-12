# PICADS v0.16.1

**Procedural Integrated Circuit Architecture and Design System** — experimental digital EDA software for restricted typed procedural hardware descriptions, MCD/CO architecture generation, executable gate-level DLS, structural Verilog, simulation and scheduling, with integration hooks for established external EDA tools.

## v0.16.1 — KiCad/LibreLane selectable installer fix

**Fixed:** KiCad and LibreLane checkboxes can now be selected. KiCad is installed with the native Windows Package Manager (WinGet), requesting a directory under `dependencies/` where supported and registering the actual program path after installation. LibreLane launches a **visible, explicitly confirmed** Windows WSL2/Docker setup console; administrator approval, Ubuntu first-run setup, Docker integration, and reboots can be required. The LibreLane installer returns `SETUP_STARTED`, not a fabricated `INSTALLED` result. Full end-to-end physical execution still requires Windows testing and a supported PDK.

[Read the KiCad and LibreLane setup instructions](docs/WINDOWS_INSTALLER_PATCH_v0.16.1.md).

## v0.16.0 — Windows-first native dependency installation

PICADS now has **Settings → Install / Manage Windows Tools...**. You can check the optional packages you want (none are selected by default) and download their upstream **Windows** portable archives into `PICADS/dependencies/`. The installer identifies supported tools, saves paths to the PICADS per-user registry, records SHA-256 hashes, and keeps the GUI responsive while downloading. Managed installation status is checked separately from tools discovered on PATH, and incomplete installs are never silently overwritten. The original manual **Choose App** and **Choose Folder** controls remain available.

The supported direct portable downloads are **OSS CAD Suite for Windows x64** (Yosys, Icarus, Verilator, and available formal tools) and the official Windows ZIP of **KLayout**. No Linux runtime is needed for PICADS compilation, DLS simulation, or these native RTL tools. **LibreLane is selectable for its guided Windows backend setup, but is not supplied as a fake Windows executable**: for full ASIC place-and-route it currently requires an optional WSL2/Docker backend and a working PDK. KiCad is for PCB design, not an ASIC mask flow.

[Read the Windows installation and verification guide](docs/WINDOWS_NATIVE_DEPENDENCIES_v0.16.0.md). Native package download and actual Windows process execution still require live testing on Windows; local installer behavior was verified using offline release-shaped archives and security tests.

## Original v1.0 scope and qualification target

This update prioritizes an **end-to-end, evidence-backed first-chip workflow** rather than adding more optional protocols. A new [future features roadmap](docs/FUTURE_FEATURES.md) separates post-v1.0 plans from requirements for the first usable release. The exact first-release requirements are defined in [v1.0 acceptance](docs/V1_SCOPE_AND_ACCEPTANCE.md).

The cumulative previous release added validated PDK/technology and floorplan preflight, a real LibreLane configuration handoff, hashes of input RTL and config, independent GDS top-cell/stream inspection and output hashes, CLI/GUI physical readiness checks, and a one-command Windows first-chip diagnostic runner.

**Important:** The software is not yet a manufacturing mask generator or foundry signoff product. Producing GDSII in a verified tool run does **not** mean the design meets a fabrication process's electrical constraints, DRC/LVS/STA/antenna/power requirements or mask acceptance rules. Those require a qualified PDK and independent evidence.

## v0.15.1 — automatic feature verification and source-only ALU component

The release includes an independently specified **4-bit ALU slice** in [`examples/alu_slice_component`](examples/alu_slice_component/circuit.py) (one piece of a future processor, not a complete chip), with its MCD/CO declarations and no handmade RTL or masks. The compiler's DLS passes a separate 1,024-case truth-table check; errors are injected deliberately to test diagnostics.

**Start with `RUN_PICADS_AUTOTEST.bat`.** This runs real compiler/CLI commands, source and wiring mutation tests, Qt GUI user-journey tests when PySide6 is installed, and optional installed Icarus/Yosys/LibreLane checks on temporary copies. It writes `validation/PICADS_v0.16.1_automated_diagnostics.zip`. The batch file may install missing Python test/GUI packages into your user environment; it does not install native EDA tools.

For a short checklist, see [Windows testing quick start](docs/TESTING_QUICKSTART.md). See [automated acceptance guide](docs/AUTOMATED_V1_VERIFICATION_v0.15.1.md) and [ALU chip-part specification](docs/ALU_SLICE_REFERENCE_v0.15.1.md).

**Status:** v1.0 **candidate for Windows integration testing**, not certified feature-complete or foundry-signoff-ready. Qt and native EDA stages are still untested in this environment.

## Windows quick start

1. Extract this ZIP into a directory (no outer wrapper folder).
2. Run `SETUP_GUI_WINDOWS.bat` to install Python GUI dependencies if necessary.
3. Run `RUN_GUI.bat` and use **Settings → External Dependencies → Choose App / Choose Folder** to register Icarus (`iverilog` + `vvp`), Yosys, LibreLane, KLayout and other tools you have.
4. For the first complete hardware-to-GDS test, run **`RUN_V1_ACCEPTANCE.bat`**. It compiles a bundled synchronous example and attempts real RTL/synthesis/physical checks where the required tools and PDK are available.
5. Return `validation/PICADS_v0.16.1_v1_acceptance.zip` for detailed debugging. `PARTIAL` is expected without the native EDA toolchain.

To select a target other than the default `sky130A`, run:

```bat
RUN_V1_ACCEPTANCE.bat --pdk my_pdk --pdk-root "C:\path\to\pdk_root" --std-cell-library my_cells
```

`pdk_root` must be the containing PDK root expected by LibreLane, not an arbitrary folder of LEF/Liberty files. For a custom thin-film process, you must supply an actually usable characterized technology and standard-cell library; PICADS does not create qualified electrical models from material names.

## CLI

```sh
python -m pip install -e ".[test,gui]"
picads doctor
picads compile examples/first_physical_chip
picads physical-preflight examples/first_physical_chip
python -m chipcompiler.acceptance --output validation/PICADS_v0.16.1_v1_acceptance
python -m pytest -q tests/test_iteration14.py
```

`physical-preflight` reports BLOCKED until `physical.enabled: true` and a target PDK are configured. It does not claim a physical run or signoff. `chipcompiler` remains a compatibility command alias.

Existing `RUN_GLOBAL_VALIDATION.bat` and `RUN_FULL_VALIDATION.bat` continue to validate the more complex scheduler and broader integration.

## Key documentation

- [Future planned features (deferred)](docs/FUTURE_FEATURES.md)
- [Fixed v1.0 acceptance contract](docs/V1_SCOPE_AND_ACCEPTANCE.md)
- [Current implementation status](docs/IMPLEMENTATION_STATUS.md)
- [Remaining required work](docs/NEXT_IMPLEMENTATION.md)
- [v0.15.1 release notes](docs/RELEASE_NOTES_v0.15.1.md)
