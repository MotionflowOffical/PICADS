"""Read-only DEF power/ground special-net inventory. Not an electrical signoff."""
from pathlib import Path
import re

def inspect_def_specialnets(path):
    path=Path(path)
    declared=None
    names=[]
    inside=False
    # Stream rather than loading giant placement files into RAM.
    with path.open('r',encoding='utf-8',errors='replace') as src:
        for line in src:
            if not inside:
                m=re.match(r'^\s*SPECIALNETS\s+(\d+)\s*;',line,re.I)
                if m:
                    declared=int(m.group(1));inside=True
                continue
            if re.match(r'^\s*END\s+SPECIALNETS\b',line,re.I):break
            m=re.match(r'^\s*-\s+([^\s]+)',line)
            if m:names.append(m.group(1))
    if declared is None:
        return {'status':'UNVERIFIED','reason':'DEF has no SPECIALNETS section',
                'scope':'physical power connectivity not verified'}
    if declared != len(names):
        return {'status':'UNVERIFIED','reason':'DEF SPECIALNETS count does not match header',
                'declared':declared,'names':names}
    return {'status':'PASS' if len(set(names))>=2 else 'UNVERIFIED',
            'declared':declared,'names':names,
            'scope':'power/ground SPECIALNETS existence only; not proven electrical continuity, IR drop or EM'}
