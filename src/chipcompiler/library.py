"""Verified, user-extensible DLS macro library.

Currently matches entire combinational functions. It never substitutes an
unverified candidate, never assumes a name implies logical equivalence.
"""
from __future__ import annotations
from pathlib import Path
from itertools import product
from .ir import DLS
from .diagnostics import IssueCollector


def try_reuse(design:DLS, directory:Path, issues:IssueCollector)->DLS:
    if design.registers:return design
    best=design
    for file in sorted(Path(directory).glob('*.dls')) if Path(directory).is_dir() else []:
        try:
            candidate=DLS.load(file)
            if candidate.registers or candidate.inputs!=design.inputs:continue
            if set(candidate.outputs)!=set(design.outputs):continue
            if {k:len(v) for k,v in candidate.outputs.items()}!={k:len(v) for k,v in design.outputs.items()}:continue
            if sum(design.inputs.values())>12:
                issues.add('LIBRARY.UNPROVEN_MATCH','INFO','DLS','library',
                           f'Cannot prove candidate library module {file.name}: input space exceeds exhaustive matcher limit.',
                           evidence={'library_file':str(file),'limit_input_bits':12})
                continue
            if len(candidate.nodes)>=len(best.nodes):continue
            a=design.new_simulator();b=candidate.new_simulator()
            same=True
            for row in product(*(range(1<<w) for w in design.inputs.values())):
                v=dict(zip(design.inputs,row))
                if a.step(v,clock=False)!=b.step(v,clock=False):same=False;break
            if same:best=candidate
        except Exception as exc:
            issues.add('LIBRARY.INVALID','WARNING','DLS','library',f'Library candidate {file.name} was ignored: {exc}',
                       file=str(file),cause='Candidate cannot be parsed or validated.',
                       remedy='Repair or remove the invalid library module.')
    if best is not design:
        # Required names/ports are identical; metadata must reflect provenance of substitution.
        best.metadata={**design.metadata,'library_source':str(directory),'reused_library_design':True}
        issues.add('LIBRARY.REUSED','INFO','DLS','library',
                   'Verified lower-gate-count library implementation selected.',
                   evidence={'before_gates':len(design.nodes),'after_gates':len(best.nodes)})
    return best
