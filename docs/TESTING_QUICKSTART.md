# PICADS v0.16.2 — Windows test quick start

## What to do

1. **Extract** `PICADS_Source_v0.16.2.zip` completely (do not run the batch file inside a ZIP preview).
2. Have **Python 3.10+** installed. The launcher checks for PySide6, pytest, PyYAML, and pycparser and offers automatic user-profile installation if missing.
3. Optional but recommended: run `RUN_GUI.bat`, open **Settings → External Dependencies**, and register **Icarus (`iverilog` and `vvp`), Yosys, LibreLane** and a compatible PDK using **Choose App / Choose Folder**. Native checks are marked unavailable if these are absent.
4. Double-click **`RUN_PICADS_AUTOTEST.bat`**. Do not close the console while tests are running; native place/route may take a long time.
5. **Upload exactly one file**: `validation/PICADS_v0.16.2_automated_diagnostics.zip`.

## What's inside the one ZIP

- `summary.json`: PASS/FAIL/UNAVAILABLE/PARTIAL for each check.
- `HOW_TO_REPORT.txt` and `FILE_MANIFEST.json`: how to share it, included files, SHA-256 checksums.
- `launcher.log` and, when needed, `python_setup.log`: startup and dependency-installation diagnostics.
- `evidence/*.log`, `evidence/installed_tools.json`: compiler/simulator outputs, fault injection, tool detection and native tool output.
- `evidence/alu_generated/`: the actual generated Verilog (`.v`), DLS (`.dls`), waveform (`.vcd`), reports and copied source-only ALU inputs.
- `evidence/physical_native_acceptance/`: first-chip RTL, synthesis, and LibreLane/PDK result evidence where generated, including a small GDS file when available; no proprietary PDK files are copied.
- GUI test logs and screenshots if a Qt runtime is available.

You should **not** need to send screenshots, log files, or multiple separate archives. Upload this ZIP even when tests show **FAIL** or **PARTIAL**. A partial result is expected without external EDA tools.

## Manual verification (separate from automated test)

Run `RUN_GUI.bat`, open `examples/alu_slice_component`, compile the design, simulate ADD/SUB/AND/XOR, and inspect the DLS/Verilog. Report GUI usability observations in the chat; the single ZIP is still the automated diagnostic attachment.

**Privacy:** the report may contain Windows installation paths and executable names. It does not intentionally copy unrelated projects, PDK binaries, credentials, or environment variables. Inspect the ZIP before sharing if folder names are sensitive.
