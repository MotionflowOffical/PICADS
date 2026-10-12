# PICADS v0.16.8 standalone LibreLane import repair

## Confirmed cause

The optional Windows installer stages a stand-alone file named
`dependencies/librelane/DISCOVER_WSL_DISTRO.py`, while the setup code executes
`from wsl_backend_discovery import discover_distro` after its relative import
fails in script mode. Python module imports use the actual basename. Thus the
setup failed with `ModuleNotFoundError: No module named 'wsl_backend_discovery'`
before reaching WSL or Docker.

## Permanent repair

- `src/chipcompiler/windows_optional_install.py` now stages the importable
  `wsl_backend_discovery.py` **and** the older `DISCOVER_WSL_DISTRO.py` alias.
- `src/chipcompiler/windows_librelane_setup.py` imports the package module when
  installed as a package; as a stand-alone script it accepts either generated
  basename. It does not swallow unrelated import errors.
- The source overlay includes already-staged helper files under
  `dependencies/librelane/` so that an EXISTING
  `SETUP_LIBRELANE_WINDOWS.bat` can be retried without launching PICADS GUI to
  regenerate it. These are scripts only; the overlay does not include a
  launcher with a hardcoded Python path.

## Apply

Close the current setup window. Extract the small import-fix ZIP directly into
`C:\ChipManuSoftware\PICADS Build`, preserving relative `src/` and
`dependencies/librelane/` paths. Agree to replace script files; **do not
remove the existing `dependencies` folder**.

Now test in PowerShell:

```powershell
cd "C:\ChipManuSoftware\PICADS Build"
py -3 ".\dependencies\librelane\LIBRELANE_SETUP_WINDOWS.py" --help
py -3 ".\dependencies\librelane\LIBRELANE_SETUP_WINDOWS.py" --probe-only
```

The `--probe-only` mode detects existing components and does not install tools
or change files. If it passes, rerun the existing
`dependencies\librelane\SETUP_LIBRELANE_WINDOWS.bat`.

### Alternative: immediate workaround without a ZIP

```powershell
cd "C:\ChipManuSoftware\PICADS Build\dependencies\librelane"
Copy-Item .\DISCOVER_WSL_DISTRO.py .\wsl_backend_discovery.py
.\SETUP_LIBRELANE_WINDOWS.bat
```

This is enough to resolve the currently reported traceback, but on its own it
does not repair the `stage_librelane` generator for future runs. Use the overlay
for that permanent fix.

## Verification scope

- 40 focused Python tests pass on Linux, including a new-process execution of
  generated `LIBRELANE_SETUP_WINDOWS.py`, fallback from the legacy filename,
  and a `--probe-only` end-to-end run with isolated fake WSL/Docker executables.
- This does NOT prove actual Windows 10/WSL2/Docker/LibreLane runtime setup,
  container downloads, EDA synthesis, PDK compatibility, or fabricated mask
  signoff. Run the actual setup on the user's machine to validate those.
