"""Validate the header of an exported AIGER artifact, not its equivalence."""
from pathlib import Path

def inspect_aiger_header(path: Path) -> dict:
    path=Path(path)
    if not path.is_file() or path.stat().st_size < 8:
        raise ValueError('AIGER file is missing or too small')
    with path.open('rb') as fd:
        header=fd.readline(256)
    try:
        parts=header.decode('ascii').strip().split()
        if len(parts) < 6 or parts[0] not in ('aig','aag'):
            raise ValueError('Invalid AIGER signature/header')
        m,i,l,o,a=[int(v) for v in parts[1:6]]
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Invalid AIGER header') from exc
    if min(m,i,l,o,a) < 0 or m < i+l+a or max(m,i,l,o,a)>10**9:
        raise ValueError('Invalid AIGER node counts')
    return {'format':parts[0],'max_variable':m,'inputs':i,'latches':l,
            'outputs':o,'and_nodes':a,'bytes':path.stat().st_size,
            'verification':'STRUCTURE_HEADER_ONLY_NOT_FORMAL_EQUIVALENCE'}
