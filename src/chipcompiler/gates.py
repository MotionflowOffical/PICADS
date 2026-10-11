"""Technology-independent, four-state gate semantics (Z at gate input behaves as X)."""
from typing import Optional
Bit = Optional[int]  # None = X; output Z intentionally unsupported by this primitive set

PRIMITIVES = {
    'AND': 2, 'OR': 2, 'XOR': 2, 'NAND': 2, 'NOR': 2, 'XNOR': 2,
    'NOT': 1, 'BUF': 1, 'MUX': 3, 'DFF': 1,
}

def gate(op: str, xs: tuple[Bit, ...]) -> Bit:
    if op == 'BUF' or op == 'DFF': return xs[0]
    if op == 'NOT': return None if xs[0] is None else 1-xs[0]
    if op == 'MUX':
        s, a, b = xs
        if s is None: return a if a == b else None
        return b if s else a
    a, b = xs
    if op in ('AND','NAND'):
        x = 0 if a == 0 or b == 0 else (1 if a == 1 and b == 1 else None)
    elif op in ('OR','NOR'):
        x = 1 if a == 1 or b == 1 else (0 if a == 0 and b == 0 else None)
    elif op in ('XOR','XNOR'):
        x = None if a is None or b is None else a ^ b
    else: raise ValueError(f'Unknown gate: {op}')
    if op in ('NAND','NOR','XNOR'): return None if x is None else 1-x
    return x
