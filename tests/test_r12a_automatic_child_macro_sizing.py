"""r12a: actual LEF-sized auto child macros, area-first packing and safe cache."""
from pathlib import Path
import json
import shutil

import pytest
import yaml

from chipcompiler.co_macros import (
    read_macro_constraints, child_macro_librelane_config,
    child_macro_cache_digest, cached_macro_lef_size,
    allocate_macro_rectangles, autosized_macro_die, MacroConstraintError,
)

EXAMPLE=Path(__file__).resolve().parents[1]/'examples'/'tiny8_co_native'


def _project(tmp_path):
    root=tmp_path/'chip'
    shutil.copytree(EXAMPLE,root)
    doc=yaml.safe_load((root/'architecture.co').read_text(encoding='utf-8'))
    phys=yaml.safe_load((root/'chip.yaml').read_text(encoding='utf-8'))['physical']
    return root,doc,phys


def test_auto_child_has_no_explicit_die_or_core_and_utilization_controls_size(tmp_path):
    root,doc,phys=_project(tmp_path)
    raw=doc['physical_macros']
    raw['auto_core_utilization']=48
    raw['blocks'][0]['die_size_um']='auto'
    raw['blocks'][0]['preview_size_um']=[210,180]
    spec=read_macro_constraints(raw,root,phys)
    block=spec['blocks'][0]
    assert block['die_mode']=='auto'
    assert block['width']==210 and block['height']==180
    auto=child_macro_librelane_config(block,phys)
    assert auto['FP_SIZING']=='relative'
    assert auto['FP_CORE_UTIL']==48
    assert 'DIE_AREA' not in auto and 'CORE_AREA' not in auto
    assert auto['FP_ASPECT_RATIO']==1
    fixed=child_macro_librelane_config(spec['blocks'][1],phys)
    assert 'FP_SIZING' not in fixed
    assert fixed['FP_CORE_UTIL']==phys['core_utilization']
    assert fixed['DIE_AREA']==[0,0,spec['blocks'][1]['width'],spec['blocks'][1]['height']]
    raw['blocks'][0]['core_utilization']=52
    again=read_macro_constraints(raw,root,phys)
    assert child_macro_librelane_config(again['blocks'][0],phys)['FP_CORE_UTIL']==52


def test_cache_accepts_only_hash_matched_auto_lef(tmp_path):
    root,doc,phys=_project(tmp_path)
    doc['physical_macros']['blocks'][0]['die_size_um']='auto'
    doc['physical_macros']['auto_core_utilization']=45
    b=read_macro_constraints(doc['physical_macros'],root,phys)['blocks'][0]
    digest=child_macro_cache_digest(b,phys)
    folder=root/'build'/'co_macro_cache'/b['module']
    folder.mkdir(parents=True)
    (folder/'source.sha256').write_text(digest+'\n')
    lef=folder/'runs'/('hard_'+digest[:14])/'final'/'lef'/(b['module']+'.lef')
    lef.parent.mkdir(parents=True)
    lef.write_text('MACRO '+b['module']+'\n SIZE 93.2 BY 101.6 ;\nEND '+b['module']+'\n')
    assert cached_macro_lef_size(root,b,phys)==[93.2,101.6]
    doc['physical_macros']['auto_core_utilization']=55
    new=read_macro_constraints(doc['physical_macros'],root,phys)['blocks'][0]
    assert cached_macro_lef_size(root,new,phys) is None


def test_invalid_auto_size_and_density_do_not_become_fixed(tmp_path):
    root,doc,phys=_project(tmp_path)
    raw=doc['physical_macros']
    raw['blocks'][0]['die_size_um']='auto'
    raw['blocks'][0]['preview_size_um']=[10,100]
    with pytest.raises(MacroConstraintError,match='preview_size_um'):
        read_macro_constraints(raw,root,phys)
    raw['blocks'][0]['preview_size_um']=[100,100]
    raw['auto_core_utilization']=95
    with pytest.raises(MacroConstraintError,match='auto_core_utilization'):
        read_macro_constraints(raw,root,phys)


def test_minimum_area_is_primary_optimizer_objective():
    blocks=[{'name':name,'module':name,'instance':name,'size_um':dims} for name,dims in
            [('a',[120,150]),('b',[170,110]),('c',[80,90]),('d',[65,70])]]
    gap={'min_um':15,'preferred_um':40,'max_um':150}
    rows,die=allocate_macro_rectangles(blocks,gap,mode='compact')
    assert die==[autosized_macro_die(rows)['width_um'],autosized_macro_die(rows)['height_um']]
    assert len(rows)==4
    from chipcompiler.co_macros import _validate_2d_clearance
    _validate_2d_clearance(rows,gap)


def test_tiny8_can_switch_all_macro_blocks_to_relative_sizing(tmp_path):
    root,doc,phys=_project(tmp_path)
    for block in doc['physical_macros']['blocks']:
        block['die_size_um']='auto'
        block['preview_size_um']=[100,100]
    spec=read_macro_constraints(doc['physical_macros'],root,phys)
    assert len(spec['blocks'])==3
    assert all(b['die_mode']=='auto' for b in spec['blocks'])
    assert all('DIE_AREA' not in child_macro_librelane_config(b,phys) for b in spec['blocks'])


def test_auto_macro_child_config_used_during_actual_layout_dispatch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from chipcompiler import co_macros, pipeline
    from chipcompiler.pipeline import BuildSession
    root=tmp_path/'cpu'
    shutil.copytree(EXAMPLE,root)
    co_path=root/'architecture.co'
    co=co_path.read_text()
    co=co.replace('physical_macros:', 'physical_macros:\n  auto_core_utilization: 45', 1)
    import re
    co=re.sub(r'die_size_um:\s*\[[^]\n]+\]','die_size_um: auto',co)
    co_path.write_text(co)
    monkeypatch.setattr(pipeline,'physical_preflight',lambda *args,**kwargs:SimpleNamespace(
        status='READY_TO_ATTEMPT',checks={'settings':{'status':'PASS'}},
        librelane_config={'CLOCK_PERIOD':100,'FP_CORE_UTIL':25},
        as_dict=lambda:{'status':'READY_TO_ATTEMPT','checks':{'settings':{'status':'PASS'}}}))
    seen=[]
    def fail_before_hardening(argv,cwd,logs,issues,events,stage,timeout=600,**opts):
        seen.append((stage,argv,cwd))
        if stage.startswith('abc_'):
            (cwd/'abc_optimized.aig').write_bytes(b'aig 0 0 0 0 0\n')
            return {'status':'PASS','returncode':0}
        return {'status':'FAIL','returncode':2,'stdout_tail':'intentional test interruption'}
    monkeypatch.setattr(co_macros,'run_external',fail_before_hardening)
    result=BuildSession(root,'layout').run()
    assert result.stages['generate']['status']=='PASS'
    assert result.stages['physical']['status']=='FAIL'
    assert seen[0][0]=='macro_tiny8_memory'
    assert seen[0][1][-3:]==['--to','Magic.WriteLEF','config.json']
    cfg=json.loads((root/'build/co_macro_cache/tiny8_memory/config.json').read_text())
    assert cfg['FP_CORE_UTIL']==45 and cfg['FP_SIZING']=='relative'
    assert 'DIE_AREA' not in cfg and 'CORE_AREA' not in cfg
