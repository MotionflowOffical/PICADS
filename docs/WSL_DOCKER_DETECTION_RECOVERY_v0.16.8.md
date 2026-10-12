# PICADS v0.16.8 — WSL + Docker detection and execution repair

## Cause observed from user logs

Windows `wsl -l -v` shows a runnable `Ubuntu` distribution, and Windows `docker info`
shows a running Docker Desktop Linux engine. Nevertheless the original PICADS v0.16.7
CMD installer reported `WSL_E_DISTRO_NOT_FOUND` after Python discovery and treated
Docker Desktop as absent. It downloaded and reinstalled Docker Desktop unnecessarily.

There were two implementation weaknesses:

1. The CMD script exchanged the discovered distro name via an intermediate text file
   and environment variable, then invoked WSL again. The source alone does not
   establish why the second invocation returned WSL_E_DISTRO_NOT_FOUND on the user's
   machine. Removing the CMD handoff keeps distro naming and execution consistent.
2. Docker checking was based on the old launcher process's `PATH` and a small list
   of files. A stale launcher PATH can miss an installed/running Docker CLI. The
   revised helper explicitly checks engine reachability and per-user program paths,
   and refuses to reinstall when Docker Desktop binaries already exist.

The **Windows Docker engine** and **Docker inside Ubuntu** are separate probes.
The latter needs Docker Desktop Settings → Resources → WSL Integration → Ubuntu.

## Changes

- `SETUP_LIBRELANE_WINDOWS.bat` is now a minimal visible console launcher. It calls
  `LIBRELANE_SETUP_WINDOWS.py`, a staged copy of
  `src/chipcompiler/windows_librelane_setup.py`.
- WSL discovery stages `wsl_backend_discovery.py` and a legacy-compatible `DISCOVER_WSL_DISTRO.py`; **no WSL distro is
  installed** if an existing one is runnable.
- Windows Docker status: `READY`, `ENGINE_NOT_READY`, `INSTALLED_CLI_NOT_FOUND`,
  or `ABSENT`. Per-user installation runs **only** for `ABSENT`; no ACL changes or
  Docker data deletion. Docker success requires a real `docker info --format` reply.
- WSL Docker checks are independent. If Ubuntu lacks Docker integration, the setup
  prints the exact Docker Desktop Settings action and stops without installing.
- Linux venv uses Python 3.10+, installs `librelane` with pip, and confirms the
  **official Dockerized smoke test** before recording `backend_smoke_passed.txt`.
- Yosys is checked in Ubuntu because PICADS also invokes Yosys outside LibreLane.
- `tools.py` executes LibreLane through the managed venv's `python -m librelane`
  inside WSL, avoiding the previous dependency on a global `/usr/local/bin` link.
- WSL physical runs enable `--dockerized` automatically. Other execution modes
  retain their existing behavior.

## Apply to the installed PICADS project

1. **Close PICADS** and any old LibreLane setup console.
2. Extract the **patch ZIP at the actual PICADS project root**, matching the
   `src/chipcompiler/`, `tests/`, and `docs/` paths. Do **not** erase or replace
   the `dependencies/` directory. Alternatively use the complete source ZIP.
3. Start `RUN_GUI.bat` and select **Settings → Install / Manage Windows Tools →
   LibreLane → Install Selected**. The launcher regenerates the new helper scripts.
4. If `docker info` in Windows works but Ubuntu integration fails, open Docker
   Desktop → Settings → Resources → WSL Integration → enable **Ubuntu** → Apply & Restart.
5. Rerun PICADS setup. It will install the missing Linux prerequisites if required,
   then run the Dockerized LibreLane smoke test. It does not download Docker again
   when the existing Windows Docker CLI/engine are functional.

### Non-destructive manual probes (PowerShell)

```powershell
wsl --list --verbose
wsl -d Ubuntu --exec sh -c 'echo WSL_OK'
docker info
wsl -d Ubuntu --exec docker info
```

The final command must succeed **inside Ubuntu**, not merely in PowerShell.

After PICADS stages the launcher, an additional probe-only command is available:

```powershell
py -3 ".\dependencies\librelane\LIBRELANE_SETUP_WINDOWS.py" --probe-only
```

Run this from the PICADS project root. It performs no installations or file writes.

## Verification and limits

- All focused v0.16.8 installer tests and selected adjacent legacy tests were run
  in an isolated Linux environment with fake WSL/Docker launchers; see the
  `tests/test_librelane_windows_setup_0168.py` regression tests.
- Real Windows 10/WSL2/Docker 4.95.0 execution, Python venv package download,
  and LibreLane container smoke tests **must be verified on the user's machine**.
- No actual custom thin-film PDK, process-design rules, mask signoff, electrical
  verification, or fabrication readiness is established by passing this setup.
- The complete historical pytest suite was not finished during this repair.

Official references:
- Docker WSL integration: https://docs.docker.com/desktop/features/wsl/
- LibreLane Windows setup: https://librelane.readthedocs.io/en/stable/installation/docker_installation/installation_win.html
