# PICADS v0.16.0 — Verification report

- Source baseline: v0.15.1 cumulative release.
- Full local pytest suite: **500 passed, 3 skipped** (baseline before two extra managed-install tests; a later combined all-in-one run was interrupted), after adding the native installer and its security tests.
- Included new tests: native bundle selection/registration using offline mock ZIP, malicious ZIP/TAR traversal rejection, HTTPS origin enforcement, upstream checksum mismatch, failure atomicity, independent tool environment, CLI catalog, KLayout release parsing and Windows-only backend discrimination.
- GUI installer code: imports and Qt smoke test included; PySide6 unavailable locally; live Windows GUI execution **not verified**.
- Native online installer: HTTP access unavailable locally, so official downloads and real executable activation remain **not verified**.
- Full manufacturing physical run: **not performed**; LibreLane backend optional and WSL2/Docker-based on Windows.
- No fabricated DRC/LVS/STA/manufacturing claims.

Live Windows testing should run `RUN_PICADS_AUTOTEST.bat` and report the resulting versioned diagnostic ZIP. Actual native tool installation and running Yosys/Icarus/KLayout should be examined on the Windows host.

## Release follow-up checks

- The installer-specific regression group (`test_windows_installer.py` and `test_iteration14.py`) passed **40 tests** after improvements to managed status and portable KLayout installation.
- Another relevant focused group (iterations 13–15 plus installer and GUI installation smoke test) passed **73 tests, 1 skipped** before the final portable-KLayout test was added.
- Subsequent all-in-one historical regression invocations were interrupted by the execution limit. They are **not** reported as successful full-suite runs after the final two test additions.
- The GUI installer and official online binary downloads still require the user's Windows machine for actual runtime verification.
