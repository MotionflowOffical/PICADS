# PICADS v0.16.8r5: Diagnosing WSL Docker runtime during physical implementation

This update does not claim to fix an offline Docker Desktop engine. It fixes
missing diagnostics when the *live* WSL probe fails and provides a read-only
Windows troubleshooting launcher. An older successful LibreLane smoke test is
not proof that Docker is running today.

## Identified scenario

`physical_preflight.json` shows `yosys: PASS`, `librelane: PASS` and
`docker_wsl: UNAVAILABLE`. Yosys finishes, but the `physical` stage correctly
aborts before attempting a Dockerized LibreLane run. No GDS is created.

## What changed

* WSL Docker probe no longer redirects away the Docker server version.
* Each runtime probe records command argv, exit code, stderr, stdout and a
  specific diagnostic hint (missing Docker CLI / inaccessible daemon /
  socket permission / other failure). PICADS stores these details in
  `physical_preflight.json`, including for `docker_wsl`.
* `CHECK_PHYSICAL_DOCKER_WSL.bat` independently compares Windows Docker,
  Ubuntu direct Docker, and the precise PICADS `bash -lc` shell environment.
  It is read-only and does not modify Docker, Ubuntu or installed dependencies.

## What to do

1. Start Docker Desktop and wait until the engine is ready.
2. Run `CHECK_PHYSICAL_DOCKER_WSL.bat` from the PICADS root.
3. If Windows Docker passes but Ubuntu Docker fails, ensure Ubuntu is enabled
   under Docker Desktop > Settings > Resources > WSL Integration. Apply & Restart.
4. If both checks pass, rerun the physical build. If it still reports Docker
   unavailable, send the new `physical_preflight.json` and diagnostic output.
5. If LibreLane reaches the physical run and fails later, send `physical.log`.

## Important

No probe bypass is added. Docker must actually be reachable inside the
selected distro to execute LibreLane `--dockerized`. A GDS file is not
manufacturing signoff and cannot be assumed from a successful Yosys run.
