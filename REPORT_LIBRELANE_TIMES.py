"""Read-only LibreLane step timing approximation from a PICADS physical.log.

Run: python REPORT_LIBRELANE_TIMES.py path/to/build/latest/physical.log
No changes to Docker, WSL, design data, or physical flow configuration.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import datetime as dt
import re
import sys

ANSI = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
CLOCK = re.compile(r'\[(\d{2}):(\d{2}):(\d{2})\]')
STEP = re.compile(r"Running ['\u2018]([^'\u2019]+)['\u2019] at")


def parse_stage_timings(data:str):
    """Estimate serial stage duration from adjacent log starts; not CPU usage."""
    starts=[]; end=None; last=None; roll=0
    for raw in data.splitlines():
        line = ANSI.sub('',raw)
        stamp = CLOCK.search(line)
        if not stamp:
            continue
        seconds = int(stamp[1])*3600 + int(stamp[2])*60 + int(stamp[3])
        if last is not None and seconds < last - 3600*12:
            roll += 86400
        last=seconds
        absolute=seconds+roll
        start = STEP.search(line)
        if start:
            starts.append((absolute,start[1]))
        if 'Flow complete.' in line or 'Smoke test passed.' in line:
            end=absolute
    result=[]
    for n,(start,name) in enumerate(starts):
        nxt=starts[n+1][0] if n+1<len(starts) else end
        if nxt is not None and nxt >= start:
            result.append((name, nxt-start))
    return sorted(result, key=lambda t:t[1], reverse=True), (end-starts[0][0] if end is not None and starts else None)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('physical_log',type=Path)
    args=parser.parse_args(argv)
    if not args.physical_log.is_file():
        parser.error('File not found: '+str(args.physical_log))
    text=args.physical_log.read_text(encoding='utf-8',errors='replace')
    durations,total=parse_stage_timings(text)
    if not durations:
        print('No timestamped LibreLane step starts found; timing breakdown unavailable.')
        print('Share physical.log and final/metrics.json for a more precise diagnosis.')
        return 2
    print('LibreLane step wall-time estimates from log timestamps (NOT CPU time):')
    for stage,seconds in durations[:25]:
        print(f'  {seconds//60:3d}m {seconds%60:02d}s  {stage}')
    if total is not None:
        print(f'  Total observed elapsed time: {total//60}m {total%60:02d}s')
    print('Includes time between adjacent stage starts; excludes PICADS pre/post-processing.')
    return 0

if __name__=='__main__':sys.exit(main())
