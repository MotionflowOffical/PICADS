# PICADS v0.16.0 — Windows-native tool setup

- Added opt-in native Windows installer for OSS CAD Suite and KLayout portable archives.
- Installer uses trusted upstream HTTPS hosts, bounded streaming downloads, path-safe extraction and download SHA-256 receipts.
- Added Settings dialog with unchecked package checkboxes, installation progress, and per-machine automatic registration.
- Added `picads dependencies catalog` / `picads dependencies install <package>` CLI commands.
- Portable OSS CAD Suite Windows `environment.bat` activates external child tool processes (without global PATH changes).
- Clarified that LibreLane and OpenROAD physical layout are not natively provisioned on Windows; WSL2/Docker is an optional physical backend, not a dependency for PICADS GUI and digital design.
- Retained the v0.15.1 automated tests and source-only test circuits. A native Windows download / process-execution run remains unverified here.

See [Windows dependency architecture](WINDOWS_NATIVE_DEPENDENCIES_v0.16.0.md).
