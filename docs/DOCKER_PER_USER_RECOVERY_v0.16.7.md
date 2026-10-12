# PICADS v0.16.7: Docker Desktop per-user installation recovery

## Observed Windows failure

The previous guided LibreLane installer used the WinGet `Docker.DockerDesktop` package, which attempted an elevated machine-wide Docker installation on Windows 10 Pro. The installer exited after reporting:

```
For security reasons C:\ProgramData\DockerDesktop must be owned by an elevated account
```

This is a **Docker Desktop installation failure**, not a LibreLane or WSL compiler failure. No LibreLane smoke-test success should be reported.

## Fix

The Windows guided setup now installs Docker Desktop using the **official Docker Desktop EXE in per-user mode**:

```
Docker Desktop Installer.exe install --user --backend=wsl-2
```

The installer first checks for existing Docker binaries, then searches a narrow Docker installer cache populated by previous attempts. It reuses a cached installer only after a `Valid` Windows Authenticode signature from a Docker-related publisher. If none is found, it downloads the EXE from Docker's official HTTPS endpoint and verifies the signature before running it.

The helper intentionally **does not** delete `C:\ProgramData\DockerDesktop`, reassign security ownership, change system ACLs, reinstall WSL, or erase container data. These are sensitive operations with potential data-loss and security consequences.

## Apply on Windows

1. Close PICADS.
2. Extract `PICADS_v0.16.7_Docker_Per_User_Patch.zip` over your PICADS v0.16.6 folder and replace files. **Keep `dependencies/`.**
3. Restart PICADS and select **Settings → Install / Manage Windows Tools → LibreLane → Install Selected**.
4. PICADS opens a setup console, reuses your installed WSL distribution and then launches the signed Docker Desktop installer with `--user`.
5. Start Docker Desktop and select its WSL 2 backend. Under **Settings → Resources → WSL Integration**, enable your Ubuntu distribution. Apply and restart Docker Desktop if necessary.
6. Select **LibreLane → Install Selected** again to continue with the Docker checks, Python venv, LibreLane and the smoke test.

The presence of Docker executable files is not a PASS. The installer also checks Docker daemon connectivity from Windows and Ubuntu, and runs a LibreLane smoke test before creating its completion marker.

## If the per-user installer fails too

Do not automatically change Windows system-folder ownership or delete data. If you have an interrupted machine-wide Docker installation, reboot once and retry the per-user installer. If this still fails, collect the installer log at `C:\ProgramData\DockerDesktop\install-log-admin.txt` if available and the exact new console message. Follow Docker's official Windows installation/uninstall guidance before manually removing existing installations.

## Technical validation

This patch is regression-tested on a non-Windows environment with staged BAT/PowerShell script assertions. **Actual signed Docker downloads, PowerShell execution, and WSL/Docker/LibreLane startup have not been exercised on your machine yet.**

Official upstream docs:
- https://docs.docker.com/desktop/setup/install/windows-install/
- https://docs.docker.com/desktop/features/wsl/
- https://github.com/docker/desktop-feedback/issues/335
