"""Optional compiler-independent C reference check, executed out of process.

This tests the user's original C/C++ against executable DLS. It does not
replace formal hardware equivalence, and must be opted into because it
compiles and executes the user's source on the local host.
"""
from __future__ import annotations
import ast,itertools,random,shutil,subprocess,tempfile,json,re,sys
from pathlib import Path
from dataclasses import dataclass,asdict
from .reference import annotation_type
from .ir import DLS

@dataclass
class NativeReferenceResult:
    status:str
    tested:int
    counterexample:dict|None=None
    message:str=''
    def as_dict(self):return asdict(self)

def verify_native(original_path:Path,dls:DLS,source:str,timeout:int=60,max_vectors:int=256)->NativeReferenceResult:
    suffix=original_path.suffix.lower()
    is_cpp=suffix in ('.cpp','.cc','.cxx')
    from .dependencies import resolve_tool, dependency_environment
    compiler=resolve_tool('g++' if is_cpp else 'gcc')
    if not compiler:return NativeReferenceResult('UNAVAILABLE',0,message='GCC/G++ executable not on PATH')
    if dls.registers:return NativeReferenceResult('UNAVAILABLE',0,message='Native reference only supports combinational sources')
    f=next((n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==dls.name),None)
    if f is None:return NativeReferenceResult('UNAVAILABLE',0,message='Missing normalized top for native verification')
    types=[annotation_type(a.annotation) for a in f.args.args]
    out=annotation_type(f.returns)
    c_types=lambda t: ('int' if t.signed else 'uint')+str(t.width)+'_t' if t.width!=1 else '_Bool'
    widths=[t.width for t in types]
    rng=random.Random(1749)
    if sum(widths)<=9:
        vectors=list(itertools.product(*(range(1<<w) for w in widths)))[:max_vectors]
    else:
        vectors=[tuple(0 for _ in widths),tuple((1<<w)-1 for w in widths)]
        vectors += [tuple(rng.getrandbits(w) for w in widths) for _ in range(max(0,max_vectors-2))]
    original_path=Path(original_path).resolve()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',dls.name):return NativeReferenceResult('UNAVAILABLE',0,message='Unsafe native top name')
    # Include only a path vetted by open_project's safe_path; string literal
    # quoting supports Windows path separators as well.
    inc=json.dumps(str(original_path).replace('\\','/'))
    program=['#include <stdint.h>','#include <stdbool.h>','#include <stdio.h>',f'#include {inc}','int main(void) {']
    for vals in vectors:
        args=', '.join(f'({c_types(t)}){v}ULL' for v,t in zip(vals,types))
        program.append(f'printf("%llu\\n", (unsigned long long){dls.name}({args}));')
    program.append('return 0; }')
    with tempfile.TemporaryDirectory(prefix='chipcompiler-native-') as td:
        folder=Path(td)
        harness=folder/('reference.cpp' if is_cpp else 'reference.c')
        harness.write_text('\n'.join(program)+'\n',encoding='utf-8')
        exe=folder/('reference.exe' if sys.platform=='win32' else 'reference')
        cmd=[compiler,'-std=c++17' if is_cpp else '-std=c11','-O0','-o',str(exe),str(harness)]
        try:
            compiled=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout)
            if compiled.returncode:
                return NativeReferenceResult('UNAVAILABLE',0,message='Native reference compile failed: '+compiled.stderr[-1800:])
            proc=subprocess.run([str(exe)],text=True,capture_output=True,timeout=timeout)
            if proc.returncode:
                return NativeReferenceResult('UNAVAILABLE',0,message=f'Native reference exited with {proc.returncode}: '+proc.stderr[-1200:])
        except (OSError,subprocess.TimeoutExpired) as exc:
            return NativeReferenceResult('UNAVAILABLE',0,message=f'Native reference execution failure: {exc}')
    lines=proc.stdout.strip().splitlines()
    if len(lines)!=len(vectors):return NativeReferenceResult('UNAVAILABLE',0,message=f'Expected {len(vectors)} numeric lines, got {len(lines)}')
    sim=dls.new_simulator();mask=(1<<out.width)-1
    for i,(values,line) in enumerate(zip(vectors,lines),1):
        try:actual=int(line.strip(),10)&mask
        except ValueError:return NativeReferenceResult('UNAVAILABLE',i,message=f'Invalid native numeric output line {i}: {line[:100]}')
        inp=dict(zip(dls.inputs,values));predicted=sim.step(inp,clock=False)['result']
        if predicted!=actual:
            return NativeReferenceResult('FAIL',i,{'inputs':inp,'native_c':actual,'dls':predicted},
                                         'Native C/C++ semantics diverge from generated DLS')
    return NativeReferenceResult('PASS',len(vectors),message='Original C/C++ execution matches DLS for tested vectors; not a formal proof')
