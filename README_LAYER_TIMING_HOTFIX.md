# PICADS r8 — Named SKY130 Layers + Read-only LibreLane Timing Report

This is a small overlay patch for the PICADS v0.16.8r8 source tree. It does not overwrite projects, `dependencies`, Docker, Ubuntu, GDS geometries, or installed PDK assets.

## Install

1. Close PICADS/KLayout.
2. Back up your PICADS installation source files or use version control.
3. Extract the ZIP at the PICADS installation root, for example `C:\ChipManuSoftware\PICADS Build`, and overwrite matching `src/chipcompiler/*.py` files.
4. Restart `RUN_GUI.bat`. Use **Open Latest GDS in KLayout** again. Do not manually load the older generated `.lyp` afterwards; the launcher will use the newly generated sidecar.

## How the naming correction works

- The original PDK-authored layer palette remains untouched.
- The GDS is scanned read-only for precise `(layer, datatype)` pairs, not just layer numbers.
- Known layer pairs are mapped using the explicit Google/SkyWater SKY130 GDS table. The existing PDK display names take precedence, and missing verified names are added to a separate palette.
- Output: `<project>/build/latest/klayout_layers_picads_named.lyp`.
- Mapping evidence: `<project>/build/latest/klayout_layer_mapping.json`. `unmapped_pairs` are intentionally left numeric. This patch does NOT claim to know arbitrary non-SKY130 or private layers.
- The `-lx` option remains, so layers without a palette mapping remain visible rather than disappearing.
- In KLayout, select fewer layers or hide texts/pins for an architectural overview. Layer display is not a physical module boundary.

Authoritative source for the packaged common mapping:
https://github.com/google/skywater-pdk/blob/main/docs/rules/gds_layers.csv

A selected `.lyp` containing multiple independent tabs is left unchanged rather than flattening its display groups. Mapping evidence still reports identifiable pairs.

## Timing diagnosis

In PowerShell, from the extracted patch folder:

```powershell
python .\REPORT_LIBRELANE_TIMES.py "C:\path\to\Tiny8\build\latest\physical.log"
```

The script prints an approximate ranking of LibreLane steps, inferred from timestamped step-start messages; it does not modify anything or establish CPU utilization. Timing logged by PICADS outside LibreLane is not included. If no timestamps are present it reports that timing breakdown is unavailable rather than guessing.

For a meaningful optimization plan, compare `physical.log`, LibreLane run step reports, and the generated `final/metrics.json` or `final/metrics.csv` where available. Check if files reside under a Windows-mounted `/mnt/c/...` path and whether Docker Desktop has sufficient RAM.

**CPU worker guidance:** LibreLane's `DRT_THREADS` already defaults to the machine's thread count when unspecified. More CPUs may benefit detailed routing, but OpenROAD's flow stages are sequential and not all algorithms scale with threads. More concurrent routing tasks can increase memory pressure. Do not increase it without measurement.

## Not addressed

- Enforced ALU/memory/controller physical cell fences: unavailable in transactional Tiny8 in r8; the CO keepout only excludes *placement sites*. PDN and signal routing may still cross that keepout.
- PDN pitch/width optimization: requires final routed DEF, physical congestion and electrical evidence. Appearance alone is insufficient.
- Physical design runtime speedups: no architectural or PDK parameters are changed by this viewer/timing patch.

## Verification

71 selected tests passed and one skipped in the local Python regression suite. This is not a live Windows/KLayout test or an actual LibreLane run.
