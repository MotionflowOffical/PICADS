"""Conservative global datapath selection for bounded source processes.

Automatic selection shares a binary operator only when at least two separately
instantiated clients actually use it. This is a structural heuristic, not an
area optimization: post-synthesis PPA may favor separate datapaths.
"""
from __future__ import annotations
import ast
from collections import Counter

SHARED_BINARY_OPS = ('ADD','SUB','MUL','AND','OR','XOR','EQ','NE','LT','LE','GT','GE')
_BIN = {ast.Add:'ADD',ast.Sub:'SUB',ast.Mult:'MUL',ast.BitAnd:'AND',
        ast.BitOr:'OR',ast.BitXor:'XOR'}
_COMPARE = {ast.Eq:'EQ',ast.NotEq:'NE',ast.Lt:'LT',ast.LtE:'LE',
            ast.Gt:'GT',ast.GtE:'GE'}


def _used_operators(function:ast.FunctionDef)->set[str]:
    used=set()
    for node in ast.walk(function):
        if isinstance(node,ast.BinOp):
            used.update(v for t,v in _BIN.items() if isinstance(node.op,t))
        elif isinstance(node,ast.Compare) and len(node.ops)==1:
            used.update(v for t,v in _COMPARE.items() if isinstance(node.ops[0],t))
    return used


def resolve_shared_types(source:str, clients:list, selection)->list[str]:
    """Validate explicit types or derive shared operators across client slots."""
    if selection != 'auto':
        if not isinstance(selection,list) or not selection or any(type(v)!=str or v not in SHARED_BINARY_OPS for v in selection) or len(selection)!=len(set(selection)):
            raise ValueError('CO.GLOBAL_SHARE_TYPES: expected auto or unique list of supported binary operators')
        return selection[:]
    tree=ast.parse(source)
    functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    counts=Counter()
    for client in clients:
        if not isinstance(client,dict) or client.get('function') not in functions:
            raise ValueError('MCD.PROCESS_FUNCTION: invalid source function in automatic operator selection')
        counts.update(_used_operators(functions[client['function']]))
    selected=[kind for kind in SHARED_BINARY_OPS if counts[kind]>=2]
    if not selected:
        raise ValueError('CO.GLOBAL_AUTO_EMPTY: no operator is used by at least two source clients; use independent source_processes instead')
    return selected
