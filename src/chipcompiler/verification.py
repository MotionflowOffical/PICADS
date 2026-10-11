"""Source vs constructed DLS behavioral checks, deterministic and bounded."""
from __future__ import annotations
import itertools, random, hashlib
from dataclasses import dataclass, asdict
from .diagnostics import IssueCollector
from .reference import SourceInterpreter
from .ir import DLS

@dataclass
class VerificationReport:
    status:str
    vectors:int
    exhaustive:bool
    failures:list[dict]
    seed:int=1729
    def as_dict(self):return asdict(self)

def verify(source:str, dls:DLS, issues:IssueCollector, exhaustive_limit:int=4096,
           random_vectors:int=320, cycles:int=128) -> VerificationReport:
    if (dls.metadata.get('schedule') or {}).get('mode')=='transactional':
        from .transactional_verify import verify_transactional
        return verify_transactional(source,dls,issues,random_vectors=min(72,random_vectors))
    if (dls.metadata.get('schedule') or {}).get('mode')=='time_share':
        from .time_sharing import verify_time_share
        return verify_time_share(source,dls,issues,random_vectors=min(128,random_vectors))
    if dls.metadata.get('pipeline'):
        from .pipelining import verify_pipeline
        return verify_pipeline(source,dls,issues,exhaustive_limit,random_vectors)
    try:
        sim=dls.new_simulator()
        ref=SourceInterpreter(source,dls.metadata.get('top',dls.name))
    except Exception as e:
        issues.add('VERIFY.SETUP','ERROR','VERIFIER','equivalence',str(e),
                   cause='Verifier cannot initialize source and/or generated hardware.',
                   remedy='Check source annotations and DLS graph validity.')
        return VerificationReport('ERROR',0,False,[])
    widths=dls.inputs;total=sum(widths.values());exhaustive=(total<=12 and 2**total<=exhaustive_limit and not dls.requires_clock())
    if exhaustive:
        combos=itertools.product(*(range(2**w) for w in widths.values()))
    else:
        rng=random.Random(1729)
        cases=[dict(zip(widths,(0 for _ in widths))),dict(zip(widths,((1<<w)-1 for w in widths.values())))]
        cases.extend({k:rng.getrandbits(w) for k,w in widths.items()} for _ in range(cycles if dls.requires_clock() else random_vectors))
        combos=(tuple(case[k] for k in widths) for case in cases)
        issues.add('VERIFY.SAMPLING','WARNING','VERIFIER','equivalence',
                   'Equivalence was tested on sampled vectors, not proven for all possible inputs/states.',
                   cause='Input space too large or circuit contains state.',
                   remedy='Use formal equivalence checking for exhaustive guarantees.',
                   evidence={'seed':1729,'samples':len(cases),'input_bits':total})
    failures=[];attempts=0
    for values in combos:
        inp=dict(zip(widths,values));attempts+=1
        try:
            expected=ref.step(inp); actual=sim.step(inp)
        except Exception as e:
            issues.add('VERIFY.EXECUTION','ERROR','VERIFIER','equivalence',str(e),
                       cause='An interpreter failed while executing a vector.',
                       evidence={'inputs':inp,'vector':attempts})
            return VerificationReport('ERROR',attempts,exhaustive,failures)
        if actual!=expected:
            failure={'index':attempts,'inputs':inp,'expected':expected,'actual':actual,
                     'dls_source':dls.metadata.get('source'),'cycle':sim.cycle}
            failures.append(failure)
            if len(failures)>=8:break
    if failures:
        issues.add('VERIFY.MISMATCH','ERROR','VERIFIER','equivalence',
                   f'Generated DLS differs from source ({len(failures)} counterexample(s) captured).',
                   cause='Logic construction, source semantic handling, or DLS execution is inconsistent.',
                   remedy='Replay captured inputs and inspect DLS gate origins; do not proceed to physical implementation.',
                   evidence={'first_counterexample':failures[0],'failures':failures})
    return VerificationReport('FAIL' if failures else 'PASS_SAMPLED' if not exhaustive else 'PASS_EXHAUSTIVE',attempts,exhaustive,failures)
