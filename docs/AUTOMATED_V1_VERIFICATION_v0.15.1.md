# PICADS v0.15.1 — automated feature-level and end-to-end testing

## Default procedure (Windows)

1. Extract the **entire** cumulative source ZIP to one folder; do not launch the batch file from inside the ZIP viewer.
2. If applicable, open `RUN_GUI.bat`, open **Settings → External Dependencies**, and register applications or installation folders for Icarus (`iverilog`, `vvp`), Yosys, LibreLane, KLayout, etc. Register a PDK folder separately. *The automated test can run without native EDA tools, but the unavailable stages are then marked UNAVAILABLE.*
3. Double-click **`RUN_PICADS_AUTOTEST.bat`**. It checks Python test and GUI dependencies, attempts a user-profile installation if missing, then runs the feature robot. It **does not install physical design tools or PDKs**.
4. Upload **`validation/PICADS_v0.15.1_automated_diagnostics.zip`**. It contains structured statuses, logs and (when Qt screenshots work) evidence images.
5. Perform your own manual GUI and chip-design trial with `examples/alu_slice_component`. The automatic suite will not change an existing project.

## What the robot actually does

The Python orchestrator `chipcompiler.feature_validation` runs:

- Real `picads compile` and `picads simulate` commands on a temporary copy of the source-only four-bit ALU slice, including selected known input/output pairs.
- A real `picads trace` waveform export; tests the VCD file exists and contains logical signal data.
- A **deliberately disabled** physical preflight: must return BLOCKED with a nonzero code, never pass because of a stale GDS.
- A deliberately malformed source file: compilation must return FAILED with a meaningful diagnostic and export marked BLOCKED.
- Recovery: restores the source text and recompiles; previous failed build is moved to history, not confused with the new result.
- Independent complete truth-table verification (1,024 combinations) and mutated-wiring detection in pytest.
- Qt GUI user journeys, **when PySide6 is installed**, using the actual window and event loop in an isolated offscreen Qt process: source editing/saving; GUI build action; graph and artifacts; two simulation inputs; induced compile failure and recovery; dependency Choose Folder/Clear interaction; project switch; and physical preflight. Screenshots are included if generated. Absence of Qt is UNAVAILABLE, not PASS.
- Real Icarus-generated-RTL comparison and Yosys synthesis of the ALU **only when executables are available**.
- Original small clocked first-chip acceptance: source -> DLS/RTL -> Icarus -> Yosys -> LibreLane -> GDS and available physical evidence, using a supplied real PDK. An absent tool or PDK is UNAVAILABLE/BLOCKED, never assumed to succeed.

Tests execute in subprocesses with per-file timeouts and retain output. A test that hangs, crashes or produces malformed evidence fails its stage. Basic feature testing is the default; `--full-regression` also runs the older test files one by one, since a combined test run has previously stalled in this development environment.

## Useful flags

```bat
RUN_PICADS_AUTOTEST.bat --full-regression
RUN_PICADS_AUTOTEST.bat --pdk sky130A --pdk-root "C:\path\to\pdks"
RUN_PICADS_AUTOTEST.bat --skip-native
RUN_PICADS_AUTOTEST.bat --skip-gui
```

The native physical stage may take much longer than logical tests. Its default timeout is 5,400 seconds; increase it using `--physical-timeout SECONDS` if genuinely needed. The suite runs external EDA tools if they are installed; avoid running it during another long physical build using the same target installation.

## Reading statuses

- **PASS:** test actually ran and its specific assertions passed.
- **FAIL:** actual mismatch, crash, timeout, invalid response, or unexpected nonzero exit status.
- **UNAVAILABLE:** required application/runtime cannot be found.
- **BLOCKED:** prerequisites fail or a prior required stage failed.
- **PARTIAL:** some useful tests passed but at least one required test was unavailable or not requested.
- **UNVERIFIED:** evidence is missing and no correctness claim is possible.

Even if all executable software checks pass, **foundry-qualified manufacturing signoff is still not implied**. It requires the correct process, extraction, DRC, LVS, timing, power and other rule sets and independent acceptance.

## Privacy

Test projects are copied to temporary directories. The diagnostic archive includes tool paths, report content and logs, which may reveal local installation folder names, but it does not intentionally archive your projects, private source or PDK binaries. Review the ZIP before sharing if machine paths are sensitive.

## Single-ZIP contract in v0.15.1

The automated run packages all its available evidence, including source-only ALU inputs, generated Verilog, gate-level DLS, waveform, reports, native tool outputs, and GUI screenshots (when available), into one ZIP. `FILE_MANIFEST.json` provides per-file SHA-256 hashes. A crash in the Python robot also attempts to generate an uploadable failure ZIP. The package never reports missing tool execution as success. When there is a validated small GDS output from the acceptance chip, the native evidence folder also includes it.
