"""Detect existing, usable WSL distributions for PICADS LibreLane setup.

This module is also staged as a standalone script alongside the Windows batch
installer, so it works before any PICADS Python package is installed in WSL.
It NEVER creates, upgrades or deletes a distribution.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Do not put arbitrary untrusted text returned by WSL into a cmd.exe variable.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_TOKEN = "PICADS_WSL_SHELL_READY"


def decode_wsl_output(payload: bytes | str | None) -> str:
    """wsl.exe -l -q can write UTF-16LE even in a non-Unicode CMD pipe."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.lstrip("\ufeff").replace("\x00", "")
    if payload.startswith(b"\xff\xfe"):
        return payload.decode("utf-16", errors="replace")
    if payload.startswith(b"\xfe\xff"):
        return payload.decode("utf-16", errors="replace")
    # Windows WSL sometimes emits UTF-16LE without a BOM.
    if payload[1::2].count(0) >= max(2, len(payload) // 8):
        return payload.decode("utf-16-le", errors="replace")
    return payload.decode("utf-8-sig", errors="replace").replace("\x00", "")


def distro_names(payload: bytes | str | None) -> list[str]:
    names = []
    for line in decode_wsl_output(payload).splitlines():
        name = line.strip().replace("\ufeff", "").replace("\x00", "")
        if not _SAFE_NAME.fullmatch(name):
            continue
        # Docker's WSL distros are not interactive Linux development environments.
        if name.casefold().startswith("docker-desktop"):
            continue
        if name not in names:
            names.append(name)
    return names


def _priority(name: str) -> tuple[int, str]:
    n = name.casefold()
    if n == "ubuntu":
        return (0, n)
    if n.startswith("ubuntu-"):
        return (1, n)
    if n == "debian" or n.startswith("debian-"):
        return (2, n)
    return (3, n)


def discover_distro(*, run=None, override: str | None = None) -> dict:
    """Select a real, *runnable* installed WSL distro; do not install over it.

    Status: READY, NONE, PRESENT_NOT_READY, WSL_UNAVAILABLE.
    """
    run = run or subprocess.run
    try:
        listed = run(["wsl.exe", "--list", "--quiet"], capture_output=True,
                     check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "WSL_UNAVAILABLE", "error": str(exc), "installed": []}
    if listed.returncode:
        return {"status": "WSL_UNAVAILABLE", "error": decode_wsl_output(listed.stderr),
                "installed": []}
    names = distro_names(listed.stdout)
    if not names:
        return {"status": "NONE", "installed": []}
    preferred = override if override is not None else os.environ.get("PICADS_WSL_DISTRO")
    if preferred:
        if preferred not in names:
            return {"status": "PRESENT_NOT_READY", "installed": names,
                    "error": f"Requested distribution {preferred!r} is not installed"}
        ordered = [preferred]
    else:
        ordered = sorted(names, key=_priority)
    errors = []
    for name in ordered:
        try:
            result = run(["wsl.exe", "--distribution", name, "--exec", "sh", "-c",
                          f"printf {_TOKEN}"], capture_output=True, check=False,
                         timeout=25)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{name}: {exc}")
            continue
        if result.returncode == 0 and _TOKEN in decode_wsl_output(result.stdout):
            return {"status": "READY", "distribution": name, "installed": names}
        detail = decode_wsl_output(result.stderr).strip()[-500:]
        errors.append(f"{name}: exit {result.returncode}" + (f" ({detail})" if detail else ""))
    return {"status": "PRESENT_NOT_READY", "installed": names, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("Usage: discover_wsl.py OUTPUT_DISTRO_TXT")
        return 4
    destination = Path(argv[0])
    # A stale previous selection must never be mistaken for a new probe result.
    if destination.exists():
        destination.unlink()
    result = discover_distro()
    status = result["status"]
    if status == "READY":
        destination.write_text(result["distribution"] + "\n", encoding="ascii")
        print("Found usable WSL distribution:", result["distribution"])
        return 0
    if status == "NONE":
        print("No user-managed Linux distribution is installed (Docker's internal distros are excluded).")
        return 2
    if status == "PRESENT_NOT_READY":
        print("WSL distributions are installed:", ", ".join(result["installed"]))
        print("None is currently runnable with a basic Linux shell. PICADS will NOT reinstall Ubuntu.")
        for error in result.get("errors", []):
            print("  ", error)
        if result.get("error"):
            print(result["error"])
        print("Try opening the existing distro from Windows Terminal once, or select it using PICADS_WSL_DISTRO.")
        return 3
    print("Could not query WSL:", result.get("error", "unknown error"))
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
