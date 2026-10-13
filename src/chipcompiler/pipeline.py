"""Causality-aware compilation pipeline and debug bundles.

Only independent stages continue after errors. Mandatory dependents become BLOCKED
with the upstream issue ID, preventing duplicate secondary errors.
"""
from __future__ import annotations
import json,os,shutil,traceback,datetime,hashlib,uuid
from pathlib import Path
from dataclasses import dataclass,field
from .diagnostics import IssueCollector,DiagnosticException,EventLog
from .project import open_project,atomic_write,ChipProject
from .generator import HardwareCompiler
from .verification import verify
from .export import export_verilog
from .ir import DLS
from .library import try_reuse
from .architecture import analyze,check_requirements,apply_mcd_names,count_instantiated_operators
from .physical import inspect_librelane
from .physical_flow import physical_preflight, make_physical_handoff, verify_handoff_inputs
from .native_reference import verify_native
from .tools import run_external,probe,write_librelane_config

@dataclass
class BuildResult:
    project:str
    mode:str
    stages:dict=field(default_factory=dict)
    files:dict=field(default_factory=dict)
    issues:list=field(default_factory=list)
    status:str='UNKNOWN'
    run_id:str=''
    def as_dict(self):
        return {'project':self.project,'mode':self.mode,'status':self.status,'run_id':self.run_id,
                'stages':self.stages,'files':self.files,'issues':self.issues}

class BuildSession:
    def __init__(self,root:Path,mode='compile',build_dir:Path|None=None):
        self.root=Path(root).resolve();self.mode=mode
        self.out=Path(build_dir).resolve() if build_dir else self.root/'build'/'latest'
        previous=None
        if mode != 'verify_layout' and build_dir is None and self.out.is_dir() and any(self.out.iterdir()):
            history=self.root/'build'/'history';history.mkdir(parents=True,exist_ok=True)
            name=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:6]
            previous=history/name
            self.out.rename(previous)
        self.out.mkdir(parents=True,exist_ok=True)
        self.issues=IssueCollector();self.events=EventLog(self.out/('layout_verification_events.jsonl' if mode=='verify_layout' else 'events.jsonl'))
        self.result=BuildResult(str(self.root),mode,run_id=self.events.run_id)
        if previous:self.result.files['previous_build_archive']=str(previous)
        self.project=None;self.dls=None
        self.events.emit('pipeline','begin',mode=mode,project=str(self.root),archived_previous=str(previous) if previous else None)

    def _done(self,stage,status,**details):
        self.result.stages[stage]={'status':status,**details}
        self.events.emit(stage,'status',status=status,**details)

    def _block(self,stage,reason=None):
        parents=[reason] if reason else self.issues.errors
        issue=self.issues.blocked(stage,parents)
        self._done(stage,'BLOCKED',upstream_issue_ids=issue.blocked_by)

    def run(self)->BuildResult:
        try:
            if self.mode=='verify_layout':self._verify_existing_layout()
            else:self._run()
        except DiagnosticException as e:
            self.events.emit('pipeline','stopped_expected',issue_id=e.issue.issue_id)
        except Exception as exc:
            issue=self.issues.internal_exception('pipeline',exc)
            self.events.emit('pipeline','uncaught_exception',issue_id=issue.issue_id)
        finally:
            if self.project and self.project.translation:
                mapping=self.project.translation.get('line_map') or {}
                source_path=str(self.project.source_file)
                for issue in self.issues.issues:
                    if issue.file==source_path and issue.stage=='generate' and issue.line:
                        normalized=issue.line
                        mapped=mapping.get(normalized)
                        if mapped:
                            issue.line=mapped
                            issue.evidence['normalized_line']=normalized
                            issue.evidence['normalized_source']=str(self.out/'normalized_source.py')
            self.result.issues=self.issues.as_dict()
            statuses=[x['status'] for x in self.result.stages.values()]
            self.result.status=('FAILED' if self.issues.errors else
                                'INCOMPLETE' if any(s in ('UNAVAILABLE','BLOCKED','SKIPPED','FAIL') for s in statuses)
                                else 'SUCCESS_WITH_WARNINGS' if self.issues.warnings else 'SUCCESS')
            if not self.issues.errors and self.mode=='layout' and self.result.stages.get('physical',{}).get('status')=='PASS':
                self.result.status='LAYOUT_GENERATED_UNVERIFIED'
            elif not self.issues.errors and self.mode=='verify_layout' and self.result.stages.get('verification',{}).get('status')=='PASS':
                self.result.status='VERIFIED_REPORTED_CHECKS_NOT_FOUNDRY_SIGNOFF'
            report_file=self.out/('layout_verification_report.json' if self.mode=='verify_layout' else 'report.json')
            self.result.files['report']=str(report_file)
            self.result.files['events']=str(self.out/('layout_verification_events.jsonl' if self.mode=='verify_layout' else 'events.jsonl'))
            atomic_write(report_file,json.dumps(self.result.as_dict(),indent=2,default=str))
            self.events.emit('pipeline','finished',status=self.result.status,errors=len(self.issues.errors),warnings=len(self.issues.warnings))
        return self.result

    def _run(self):
        before=len(self.issues.errors)
        self.project=open_project(self.root,self.issues)
        if self.project is None:
            self._done('project','FAIL',issue_ids=[i.issue_id for i in self.issues.errors]);
            for stage in ('generate','equivalence','export'):
                self._block(stage)
            return
        self._done('project','PASS' if len(self.issues.errors)==before else 'FAIL',
                   name=self.project.name,top=self.project.top,source_kind=self.project.source_kind)
        if self.mode=='layout':
            # Ensure the deferred software/RTL equivalence test uses exactly
            # the source compiled into the saved GDS, not later editor changes.
            atomic_write(self.out/'layout_source_snapshot.py',self.project.source)
            self.result.files['layout_source_snapshot']=str(self.out/'layout_source_snapshot.py')
        if self.project.translation:
            normalized=self.out/'normalized_source.py'
            atomic_write(normalized,self.project.source)
            self.result.files['normalized_source']=str(normalized)
            self.events.emit('frontend','translated',**self.project.translation)

        # Treat faulty independent configs as independent findings, not derivative generator failures.
        if self.issues.errors:
            for stage in ('generate','equivalence','export'):self._block(stage)
            return
        if (self.project.co.get('schedule') or {}).get('mode')=='source_processes':
            return self._run_source_processes()
        if (self.project.co.get('schedule') or {}).get('mode') in ('concurrent_fabric','tagged_fabric','bound_fabric','axi_lite_fabric'):
            return self._run_fabric()
        self.events.emit('generate','start',source=str(self.project.source_file))
        try:
            schedule_mode=(self.project.co.get('schedule') or {}).get('mode','spatial')
            if self.project.mcd.get('network') is not None:
                if schedule_mode!='spatial' or (self.project.co.get('schedule') or {}).get('pipeline_stages',0):
                    issue=self.issues.add('MCD.NETWORK_SCHEDULE_CONFLICT','ERROR','MCD','network',
                        'Explicit MCD network requires spatial schedule with zero automatic pipeline stages.',
                        cause='Automatic retiming and time-sharing across bound module instances is unsupported.',
                        remedy='Disable schedule.mode: time_share and pipeline_stages for this explicit network.')
                    raise DiagnosticException(issue)
                from .network import compile_network
                try:
                    built=compile_network(self.project.source,str(self.project.source_file),self.project.top,
                                          self.project.mcd,self.project.co,self.issues)
                except DiagnosticException as exc:
                    self._done('network','FAIL',root_issue_id=exc.issue.issue_id,
                               issue_ids=[i.issue_id for i in self.issues.errors if i.stage=='network'])
                    raise
                self.dls=built.design
                atomic_write(self.out/'network_connections.json',json.dumps(built.connections,indent=2))
                self.result.files['network_connections']=str(self.out/'network_connections.json')
                self._done('network','PASS',instances=len(self.dls.instances),connections=len(built.connections))
            elif schedule_mode=='transactional':
                from .transactional import TransactionalCompiler
                self.dls=TransactionalCompiler(self.issues,self.project.co).compile_source(
                    self.project.source,str(self.project.source_file),self.project.top)
                self._done('scheduling','PASS',mode='transactional',
                           instructions=self.dls.metadata['schedule']['instruction_count'],
                           physical_units=self.dls.metadata['schedule']['physical_units'],
                           protocol=self.dls.metadata['schedule']['protocol'])
            elif schedule_mode=='time_share':
                from .time_sharing import TimeShareCompiler
                self.dls=TimeShareCompiler(self.issues,self.project.co).compile_source(
                    self.project.source,str(self.project.source_file),self.project.top)
                self._done('scheduling','PASS',mode='time_share',
                    execution_cycles=self.dls.metadata['schedule']['execution_cycles'],
                    physical_units=self.dls.metadata['schedule']['physical_units'],
                    protocol=self.dls.metadata['schedule']['protocol'])
            else:
                self.dls=HardwareCompiler(self.issues,self.project.co).compile_source(
                    self.project.source,str(self.project.source_file),self.project.top)
            self.dls=try_reuse(self.dls,self.root/'library',self.issues)
            stage_count=(self.project.co.get('schedule') or {}).get('pipeline_stages',0)
            if stage_count:
                from .pipelining import pipeline_dls
                try:
                    self.dls=pipeline_dls(self.dls,stage_count)
                except ValueError as exc:
                    issue=self.issues.add('CO.PIPELINE_UNSUPPORTED','ERROR','CO','generate',str(exc),
                        cause='Requested pipelining is incompatible with the generated circuit.',
                        remedy='Review CO schedule, supported source and module hierarchy.',
                        evidence={'pipeline_stages':stage_count})
                    raise DiagnosticException(issue)
                self._done('scheduling','PASS',mode='spatial-pipeline',
                           latency_cycles=stage_count,initiation_interval_cycles=1,
                           temporal_contract='output valid after N rising clock edges')
            elif schedule_mode not in ('time_share','transactional'):
                self._done('scheduling','NOT_REQUESTED',reason='No multi-cycle schedule requested')
            if self.project.translation:
                mapping=self.project.translation.get('line_map') or {}
                origin_prefix=str(self.project.source_file)+':'
                for node in self.dls.nodes:
                    if node.origin.startswith(origin_prefix):
                        try:lineno=int(node.origin[len(origin_prefix):])
                        except ValueError:continue
                        if lineno in mapping:node.origin=origin_prefix+str(mapping[lineno])
                self.dls.metadata['source_origin']='C/C++ original; normalized source separately saved'
                self.dls.metadata['original_source_sha256']=self.project.translation['original_sha256']
            graph=analyze(self.project.source,self.project.top,self.project.mcd)
            if self.project.mcd.get('network') is not None:
                # This network replaces the behavior of source top; network
                # instances, rather than top source callsites, determine the
                # required physical instance count.
                graph.edges=[e for e in graph.edges if e['caller']!=graph.top]
                for inst in self.dls.instances:
                    entry=next(x for x in self.project.mcd['network']['instances'] if x['name']==inst['name'])
                    if entry.get('function'):
                        graph.edges.append({'caller':graph.top,'callee':entry['function'],
                                            'instance':inst['name'],'line':None})
                reach=[]
                def visit(fn):
                    if fn in reach:return
                    reach.append(fn)
                    for edge in graph.edges:
                        if edge['caller']==fn:visit(edge['callee'])
                visit(graph.top)
                graph.reachable=reach
                graph.unused=sorted(set(graph.functions)-set(reach))
                graph.semantics='MCD_EXPLICIT_ROUTED_NETWORK'
            requirements=check_requirements(graph,self.project.mcd)
            if requirements:
                atomic_write(self.out/'required_capabilities.json',json.dumps(requirements,indent=2))
                self.result.files['required_capabilities']=str(self.out/'required_capabilities.json')
                failed=[]
                for req in requirements:
                    if req['status']=='SATISFIED':continue
                    failed.append(req)
                    self.issues.add('MCD.REQUIRED_'+req['status'],'ERROR','MCD','module_allocation',
                        f'Mandatory MCD capability {req["requirement"]!r} is {req["status"].lower()}.',
                        cause='The required function must be reachable in the actual source call graph.',
                        remedy='Call the bound function from top, correct the module binding, or revise the required instance count.',
                        evidence=req)
                if failed:
                    raise DiagnosticException(self.issues.errors[-1])
            # MCD declares optional expected interfaces; disagreeing declarations
            # are first-class errors, not ignored comments or downstream RTL bugs.
            import ast
            for module in self.project.mcd.get('modules',[]):
                if not isinstance(module,dict):continue
                function=module.get('function',module.get('name'))
                if not isinstance(function,str) or not any(r['function']==function for r in graph.requested):continue
                for direction in ('inputs','outputs'):
                    declared=module.get(direction)
                    if declared is None:continue
                    if function==self.project.top: candidate=self.dls
                    else:
                        try:candidate=HardwareCompiler(self.issues,self.project.co).compile_source(
                            self.project.source,str(self.project.source_file),function)
                        except DiagnosticException:continue
                    actual=candidate.inputs if direction=='inputs' else {
                        name:len(bits) for name,bits in candidate.outputs.items()}
                    # Generated handshake signals belong to scheduler, not the source-level MCD.
                    if function==self.project.top and (candidate.metadata.get('pipeline') or candidate.metadata.get('schedule')):
                        scheduler_ports={'input_valid','valid','start','stall','reset','ready','done','fault'}
                        actual={k:v for k,v in actual.items() if k not in scheduler_ports
                                and not k.startswith('unit_ready_') and not k.startswith('unit_active_')}
                    if declared!=actual:
                        issue=self.issues.add('MCD.PORT_MISMATCH','ERROR','MCD','module_allocation',
                            f'Module {module.get("name")!r} {direction} do not match function {function!r}.',
                            cause='Explicit MCD interface contradicts compiled source bit widths or names.',
                            remedy='Correct the MCD declaration or source signature.',
                            evidence={'declared':declared,'actual':actual,'module':function})
                        raise DiagnosticException(issue)
            if (self.project.co.get('modules') or {}).get('naming')=='mcd':
                try:apply_mcd_names(self.dls,self.project.mcd)
                except ValueError as exc:
                    issue=self.issues.add('MCD.BINDING_INVALID','ERROR','MCD','module_allocation',str(exc),
                        cause='The requested MCD module identifiers cannot be mapped uniquely to hardware definitions.',
                        remedy='Use unique legal identifiers for every bound function and preserve the source top name.')
                    raise DiagnosticException(issue)
            if self.dls.instances:
                counts,locations=count_instantiated_operators(self.dls)
                self.dls.metadata['hierarchical_operator_counts']=counts
                limits=(self.project.co.get('allocation') or {}).get('max_instances',{}) or {}
                for kind,limit in limits.items():
                    if counts.get(kind,0)>limit:
                        issue=self.issues.add('CO.GLOBAL_RESOURCE_LIMIT','ERROR','CO','module_allocation',
                            f'Hierarchical design instantiates {counts[kind]} {kind} operators, above requested maximum {limit}.',
                            cause='Resources inside separately instantiated helper modules are not automatically shared across instances.',
                            remedy='Increase the limit, change hierarchy to flatten, or use an explicit supported time-share schedule.',
                            evidence={'operator':kind,'required':counts[kind],'limit':limit,'instances':locations[kind]})
                        raise DiagnosticException(issue)
                if self.project.mcd.get('network') is None:
                    graph.semantics='HIERARCHICAL_EXECUTABLE_DLS'
            elif stage_count:
                graph.semantics='PIPELINED_EXECUTABLE_DLS'
            elif schedule_mode=='time_share':
                graph.semantics='TIME_MULTIPLEXED_EXECUTABLE_DLS'
            atomic_write(self.out/'architecture.json',json.dumps(graph.as_dict(),indent=2))
            self.result.files['architecture']=str(self.out/'architecture.json')
            # CO-driven hierarchical physical *planning* is separate from
            # cell placement. Never claim a rectangle was enforced in GDS.
            floor_settings=self.project.co.get('floorplan')
            if floor_settings is not None:
                from .floorplanning import plan_floorplan, render_floorplan_svg, FloorplanError
                try:
                    if not isinstance(floor_settings,dict) or type(floor_settings.get('enabled',True)) is not bool:
                        raise FloorplanError('CO.FLOORPLAN_INVALID: floorplan must be a mapping with boolean enabled')
                    if floor_settings.get('enabled',True):
                        planned=plan_floorplan(floor_settings,self.dls,graph,self.project.co,
                                               self.project.config.get('physical') or {})
                        path=self.out/'module_floorplan.json'
                        atomic_write(path,json.dumps(planned,indent=2))
                        picture=render_floorplan_svg(planned,self.out/'module_floorplan.svg')
                        self.result.files['module_floorplan']=str(path)
                        self.result.files['module_floorplan_svg']=str(picture)
                        self._done('floorplan','GUIDE_ONLY',module_count=len(planned['modules']),
                                   pruned=planned['pruned'],enforcement='NOT_APPLIED_TO_PNR')
                except FloorplanError as exc:
                    issue=self.issues.add('CO.FLOORPLAN_ERROR','ERROR','CO','floorplan',str(exc),
                        cause='Requested floorplan constraints cannot be satisfied or cannot be physically enforced.',
                        remedy='Check CO floorplan regions, spacing and module bindings. Use enforcement: guide until a cell-region EDA backend is available.')
                    self._done('floorplan','FAIL',issue_id=issue.issue_id)
                    raise DiagnosticException(issue)
            # A separate functional DLS is generated for every reachable helper.
            # The physical top is flattened; hierarchy isn't falsely implied.
            modules_dir=self.out/'modules';modules_dir.mkdir(exist_ok=True)
            children={}
            for fn in graph.reachable:
                if fn==self.project.top:continue
                try:
                    child=HardwareCompiler(self.issues,self.project.co).compile_source(
                        self.project.source,str(self.project.source_file),fn)
                    child_path=modules_dir/(fn+'.dls');child.save(child_path)
                    child_report=verify(self.project.source,child,self.issues) if self.mode!='layout' else None
                    if child_report:atomic_write(modules_dir/(fn+'.verification.json'),json.dumps(child_report.as_dict(),indent=2))
                    if child_report and child_report.status in ('FAIL','ERROR'):
                        children[fn]={'status':'FAIL','path':str(child_path),
                            'verification':str(modules_dir/(fn+'.verification.json'))}
                    else:
                        child_rtl=modules_dir/(fn+'.v');export_verilog(child,child_rtl)
                        children[fn]={'status':'PASS','dls':str(child_path),'verilog':str(child_rtl),
                            'verification':child_report.status if child_report else 'DEFERRED','stats':child.stats()}
                except DiagnosticException as exc:
                    children[fn]={'status':'FAIL','issue_id':exc.issue.issue_id}
                except Exception as exc:
                    issue=self.issues.internal_exception('module:'+fn,exc)
                    children[fn]={'status':'FAIL','issue_id':issue.issue_id}
            self._done('module_allocation','PASS' if all(x['status']=='PASS' for x in children.values()) else 'PARTIAL',
                       candidates=children,physical_hierarchy='preserved' if self.dls.instances else 'flattened')
            for request in graph.requested:
                if request['status']=='descriptive-only':
                    self.issues.add('MCD.DESCRIPTIVE_ONLY','INFO','MCD','module_allocation',
                        f'Module {request["name"]!r} has no matching source function; it is descriptive only.',
                        cause='No function binding or same-named implementation was defined.',
                        remedy='Set function: to a source function to generate a separately executable module candidate.')
            dls_path=self.out/(self.dls.name+'.dls')
            self.dls.save(dls_path)
            self.result.files['dls']=str(dls_path)
            if (self.dls.metadata.get('schedule') or {}).get('mode')=='transactional':
                schedule_file=self.out/'co_schedule.json'
                atomic_write(schedule_file,json.dumps(self.dls.metadata['schedule'],indent=2,sort_keys=True))
                self.result.files['co_schedule']=str(schedule_file)
            self._done('generate','PASS',stats=self.dls.stats(),strategies=self.dls.metadata['strategies'])
        except DiagnosticException as exc:
            if self.result.stages.get('network',{}).get('status')=='FAIL':
                self._block('generate',exc.issue)
            else:
                self._done('generate','FAIL',issue_id=exc.issue.issue_id)
            self._block('equivalence',exc.issue);self._block('export',exc.issue)
            return
        except Exception as exc:
            i=self.issues.internal_exception('generate',exc)
            self._done('generate','FAIL',issue_id=i.issue_id)
            self._block('equivalence',i);self._block('export',i)
            return
        if self.mode=='layout':
            self._done('equivalence','DEFERRED',reason='Use Verify Existing Layout; no sampled DLS equivalence during initial GDS generation')
        else:
            self.events.emit('equivalence','start')
            report=verify(self.project.source,self.dls,self.issues)
            atomic_write(self.out/'equivalence.json',json.dumps(report.as_dict(),indent=2))
            self.result.files['equivalence']=str(self.out/'equivalence.json')
            self._done('equivalence',report.status,vectors=report.vectors,exhaustive=report.exhaustive)
            if report.status in ('ERROR','FAIL'):
                self._block('export',self.issues.errors[-1]);return
        native=(self.project.config.get('verification') or {}).get('native_c',False) and self.mode!='layout'
        if native and self.project.translation and self.dls.metadata.get('schedule'):
            self.issues.add('C.NATIVE_SCHEDULE_UNSUPPORTED','WARNING','VERIFIER','native_reference',
               'Native reference testing does not yet understand the START/READY/DONE scheduled protocol.',
               remedy='Use generated scheduled transaction test and independent external sequential equivalence.')
        if native and self.project.translation and not self.dls.metadata.get('schedule'):
            independent=verify_native(self.project.source_file,self.dls,self.project.source)
            atomic_write(self.out/'native_reference.json',json.dumps(independent.as_dict(),indent=2))
            self.result.files['native_reference']=str(self.out/'native_reference.json')
            self._done('native_reference',independent.status,tested=independent.tested,
                       counterexample=independent.counterexample,message=independent.message)
            if independent.status=='FAIL':
                issue=self.issues.add('C.NATIVE_MISMATCH','ERROR','VERIFIER','native_reference',
                     independent.message,evidence=independent.as_dict(),
                     cause='Generated DLS does not match compiled original C/C++ behavior.',
                     remedy='Inspect the counterexample and differences in integer promotions, casts and overflow.')
                self._block('export',issue);return
            if independent.status=='UNAVAILABLE':
                self.issues.add('C.NATIVE_UNAVAILABLE','WARNING','DEPENDENCY','native_reference',
                   independent.message,remedy='Install GCC/G++ or disable the explicit verification.native_c option.')
        try:
            rtl=self.out/(self.dls.name+'.v');export_verilog(self.dls,rtl)
            self.result.files['verilog']=str(rtl)
            self._done('export','PASS',path=str(rtl))
        except Exception as e:
            i=self.issues.add('EXPORT.VERILOG','ERROR','DLS','export',str(e),
                              cause='Generated DLS could not be serialized into structural Verilog.',
                              remedy='Inspect DLS ports and gate names.')
            self._done('export','FAIL',issue_id=i.issue_id);return
        if self.mode!='layout' and (self.project.config.get('verification') or {}).get('external_rtl',False):
            from .rtl_check import check_rtl
            toolconf=self.project.config.get('tools') or {}
            opts={'runner':toolconf.get('execution','native'),
                  'wsl_distribution':toolconf.get('wsl_distribution')}
            outcome=check_rtl(self.dls,rtl,self.out,self.issues,self.events,
                              run_options=opts,
                              vector_count=(self.project.config.get('verification') or {}).get('rtl_vectors',64))
            self._done('rtl_check',outcome['status'],**{k:v for k,v in outcome.items() if k!='status'})
            if outcome['status']!='PASS':
                if self.mode in ('build','physical'):
                    self._block('yosys',outcome.get('issue_id'))
                    self._block('physical',outcome.get('issue_id'))
                return
            self.result.files['rtl_verification']=str(self.out/'rtl_verification.json')
        if self.mode not in ('build','physical','layout'):return
        return self._run_native_flow(rtl)

    def _run_native_flow(self,rtl):
        # Optional external dependencies are actual required steps in build mode, not silent fallbacks.
        if self.mode in ('physical','layout'):
            physical_options = self.project.config.get('physical') or {}
            if not isinstance(physical_options, dict) or not physical_options.get('enabled'):
                issue = self.issues.add('PHYSICAL.DISABLED', 'ERROR', 'CONFIG', 'physical',
                    'The project has physical.enabled: false or no physical configuration. '
                    'No physical layout can be generated.',
                    remedy='Use Physical Layout > Configure SKY130 / WSL, or set physical.enabled: true and a supported PDK in chip.yaml.')
                self._done('physical', 'BLOCKED', issue_id=issue.issue_id)
                return
            if not physical_options.get('pdk'):
                issue = self.issues.add('PHYSICAL.PDK_REQUIRED','ERROR','CONFIG','physical',
                    'Physical design requires an explicit PDK name.',
                    remedy='Configure physical.pdk: sky130A for the tested reference process.')
                self._done('physical', 'BLOCKED', issue_id=issue.issue_id)
                return
        backend=(self.project.config.get('tools') or {}).get('execution','native')
        wsl_dist=(self.project.config.get('tools') or {}).get('wsl_distribution')
        opts={'runner':backend,'wsl_distribution':wsl_dist} if backend=='wsl' else {}
        yosys=run_external(['yosys','-p',f'read_verilog {rtl.name}; hierarchy -check -top {self.dls.name}; synth -top {self.dls.name}; check -assert; write_verilog -noattr synthesized.v'],
                           self.out,self.out,self.issues,self.events,'yosys',timeout=600,**opts)
        self._done('yosys',yosys['status'],**{k:v for k,v in yosys.items() if k!='status'})
        if yosys['status']!='PASS':
            self._block('physical',yosys.get('issue_id'));return
        # A zero return code is NOT sufficient proof that the expected output
        # exists and contains the requested top. Refuse stale/empty artifacts.
        synthesized=self.out/'synthesized.v'
        if not synthesized.is_file() or synthesized.stat().st_size==0:
            i=self.issues.add('YOSYS.OUTPUT_MISSING','ERROR','TOOL','yosys',
                'Yosys returned success but did not generate a nonempty synthesized.v.',
                cause='Tool output missing despite zero process status; output cannot be trusted.',
                remedy='Inspect yosys.log and verify the write_verilog stage executed.',
                evidence={'expected':str(synthesized),'yosys_stage':yosys})
            self._done('yosys','FAIL',issue_id=i.issue_id,process_returncode=yosys.get('returncode'))
            self._block('physical',i);return
        if not __import__('re').search(r'\bmodule\s+'+__import__('re').escape(self.dls.name)+r'\b',
                                       synthesized.read_text(encoding='utf-8',errors='replace')):
            i=self.issues.add('YOSYS.TOP_MISSING','ERROR','TOOL','yosys',
                f'Synthesized netlist does not declare expected top module {self.dls.name!r}.',
                cause='Wrong or incomplete synthesis output.',
                remedy='Inspect generated Verilog and Yosys hierarchy checking.',
                evidence={'artifact':str(synthesized)})
            self._done('yosys','FAIL',issue_id=i.issue_id)
            self._block('physical',i);return
        # Optional ABC-optimized AIG is a real post-synthesis artifact, not a
        # replacement for the technology-mapped PDK netlist consumed by PnR.
        synth_co = self.project.co.get('synthesis') or {}
        if synth_co.get('abc_aig'):
            from .aig import inspect_aiger_header
            aig_name='abc_optimized.aig'
            aig_cmd=('read_verilog '+rtl.name+'; '
                     'hierarchy -check -top '+self.dls.name+'; '
                     'synth -top '+self.dls.name+' -flatten -noabc; '
                     'dffunmap; abc -g AND; aigmap; '
                     'write_aiger -zinit -symbols '+aig_name)
            aig_run=run_external(['yosys','-p',aig_cmd],self.out,self.out,
                                 self.issues,self.events,'abc_aig',timeout=600,**opts)
            if aig_run['status'] != 'PASS':
                self._done('abc_aig',aig_run['status'],
                           **{k:v for k,v in aig_run.items() if k!='status'})
                self._block('physical',aig_run.get('issue_id'))
                return
            try:
                aig_stats=inspect_aiger_header(self.out/aig_name)
            except (ValueError,OSError) as exc:
                i=self.issues.add('ABC.AIG_INVALID','ERROR','TOOL','abc_aig',str(exc),
                    cause='No valid nonempty optimized AIGER was produced.',
                    remedy='Inspect abc_aig.log; ensure Yosys ABC and AIGER backend are available.')
                self._done('abc_aig','FAIL',issue_id=i.issue_id)
                self._block('physical',i)
                return
            atomic_write(self.out/'abc_aig_stats.json',json.dumps(aig_stats,indent=2))
            self.result.files['abc_optimized_aig']=str(self.out/aig_name)
            self.result.files['abc_aig_stats']=str(self.out/'abc_aig_stats.json')
            self._done('abc_aig','PASS',**aig_stats,
                       physical_input='Original RTL; LibreLane performs PDK-specific ABC mapping')
        self.result.files['synthesized_netlist']=str(synthesized)
        self.events.emit('yosys','artifact_verified',path=str(synthesized),bytes=synthesized.stat().st_size)
        if self.mode not in ('physical','layout'):return
        config=self.project.config.get('physical') or {}
        if not isinstance(config,dict):config={}
        if not config.get('enabled',False):
            self.issues.add('PHYSICAL.DISABLED','WARNING','CONFIG','physical',
                            'Physical implementation was explicitly disabled by project settings.',
                            remedy='Set physical.enabled: true and provide PDK and library configuration.')
            self._done('physical','SKIPPED',reason='Disabled in project config');return
        if not config.get('pdk'):
            i=self.issues.add('PHYSICAL.PDK_REQUIRED','ERROR','CONFIG','physical',
                             'Physical layout requested but no PDK is declared.',
                             remedy='Set physical.pdk in chip.yaml; run LibreLane PDK verification.')
            self._done('physical','FAIL',issue_id=i.issue_id);return
        name=self.dls.name
        if not self.dls.requires_clock():
            self.issues.add('PHYSICAL.COMBINATIONAL','WARNING','CONFIG','physical',
                            'The top is combinational. Explicit IO input/output timing constraints may be needed for meaningful timing validation.',
                            remedy='Provide target-specific input/output delays and a suitable timing setup.')
        preflight=physical_preflight(config, self.dls.requires_clock(), execution=backend,
                                     wsl_distribution=wsl_dist)
        atomic_write(self.out/'physical_preflight.json',json.dumps(preflight.as_dict(),indent=2))
        self.result.files['physical_preflight']=str(self.out/'physical_preflight.json')
        self._done('physical_preflight',preflight.status,checks=preflight.checks)
        if preflight.status=='BLOCKED':
            failed={k:v for k,v in preflight.checks.items() if v['status'] in ('FAIL','BLOCKED')}
            i=self.issues.add('PHYSICAL.PREFLIGHT_BLOCKED','ERROR','CONFIG','physical',
                'Physical preflight failed: '+', '.join(failed),
                cause='Invalid/absent technology or physical configuration.',
                remedy='Run `picads physical-preflight PROJECT` and correct the reported settings.',
                evidence=failed)
            self._done('physical','FAIL',issue_id=i.issue_id);self._block('signoff',i);return
        missing_backend = [k for k in ('yosys', 'librelane', 'docker_wsl')
                           if preflight.checks.get(k, {}).get('status') == 'UNAVAILABLE']
        if backend=='wsl' and missing_backend:
            i=self.issues.add('PHYSICAL.BACKEND_UNAVAILABLE','ERROR','DEPENDENCY','physical',
                'Selected physical backend is unavailable: ' + ', '.join(missing_backend),
                cause='The tools in the selected execution environment could not be reached.',
                remedy='Verify Docker Desktop WSL integration and the selected Ubuntu distribution; rerun PICADS dependency diagnostics.',
                evidence={k:preflight.checks[k] for k in missing_backend})
            self._done('physical','UNAVAILABLE',issue_id=i.issue_id);self._block('signoff',i);return
        period=config.get('clock_period_ns')
        write_librelane_config(name, 'clk' if self.dls.requires_clock() else None,period,
                               self.out/'config.json',extra=preflight.librelane_config)
        # Explicit fresh run tag, preventing an earlier mask from being
        # mistaken for the result of this compilation.
        tag='cc_'+self.result.run_id
        if (self.out/'runs'/tag).exists():
            i=self.issues.add('PHYSICAL.RUN_COLLISION','ERROR','FILESYSTEM','physical',
                f'Unique LibreLane run directory {tag} already exists.',remedy='Select another build directory.')
            self._done('physical','FAIL',issue_id=i.issue_id);return
        from .dependencies import resolve_tool
        manifest=make_physical_handoff(rtl,self.out/'config.json',self.out/'physical_handoff.json',
                                       pdk=str(config['pdk']),run_tag=tag,
                                       tool_path=resolve_tool('librelane') if backend!='wsl' else 'wsl')
        self.result.files['physical_handoff']=str(self.out/'physical_handoff.json')
        cmd=['librelane']+(['--dockerized'] if (backend=='wsl' or config.get('dockerized',False)) else [])
        if config.get('pdk_root'):
            # WSL root is already a Linux path; do not mangle it with Windows pathlib.
            root_arg=(str(config['pdk_root']) if backend=='wsl' else
                      str(Path(config['pdk_root']).expanduser().resolve()))
            cmd.extend(['--pdk-root',root_arg])
        cmd += ['--pdk',str(config['pdk']),'--run-tag',tag]
        if self.mode=='layout':cmd += ['--to','KLayout.StreamOut']
        cmd += ['config.json']
        result=run_external(cmd,self.out,self.out,self.issues,self.events,'physical',timeout=int(config.get('timeout_s',3600)),**opts)
        if not verify_handoff_inputs(manifest):
            i=self.issues.add('PHYSICAL.INPUTS_CHANGED','ERROR','FILESYSTEM','physical',
                'RTL or LibreLane config changed after the run started; resulting layout is untrustworthy.',
                remedy='Prevent external modification of build/latest and rerun from a clean build.',
                evidence=manifest)
            self._done('physical','FAIL',issue_id=i.issue_id);self._block('signoff',i);return
        if result['status']!='PASS':
            self._done('physical',result['status'],**{k:v for k,v in result.items() if k!='status'})
            self._block('signoff',result.get('issue_id'));return
        evidence=inspect_librelane(self.out/'runs'/tag,expected_top=name)
        atomic_write(self.out/'physical_evidence.json',json.dumps(evidence.as_dict(),indent=2))
        self.result.files['physical_evidence']=str(self.out/'physical_evidence.json')
        if evidence.gds:
            # Do not duplicate potentially large GDS files just to make them
            # discoverable in the GUI. A small manifest links to the *actual*
            # LibreLane run artifact and records the real numeric GDS layers.
            from .maskinspect import inspect_gds
            selected = Path(evidence.gds[0])
            self.result.files['gds'] = str(selected)
            gds_info = inspect_gds(selected)
            manifest_path = self.out/'layout_artifacts.json'
            from .physical_flow import artifact_hash
            manifest = {
                'schema': 1, 'status': 'LAYOUT_GENERATED_NOT_MASK_SIGNOFF',
                'gds_sha256': artifact_hash(selected),
                'gds': str(selected),
                'gds_relative_to_build': str(selected.relative_to(self.out)),
                'run_tag': tag, 'top': name,
                'layers': gds_info.layer_elements,
                'meaning': 'Numeric GDSII layers are layout data. Real photomask preparation requires the target PDK layer map, foundry-specific mask operations and independent verification.',
                'duplicated_large_files': False}
            atomic_write(manifest_path,json.dumps(manifest,indent=2))
            self.result.files['layout_layers'] = str(manifest_path)
        self.events.emit('physical','inspect_artifacts',**evidence.as_dict())
        if evidence.status=='FAIL' and self.mode!='layout':
            i=self.issues.add('PHYSICAL.ARTIFACT_INVALID','ERROR','PHYSICAL','physical',
                'LibreLane returned zero, but output GDS is missing or a reported physical check failed.',
                evidence=evidence.as_dict(),cause='Expected physical output is missing or noncompliant.',
                remedy='Inspect the exact LibreLane run directory and final metrics; do not reuse an old GDS.')
            self._done('physical','FAIL',issue_id=i.issue_id,evidence=str(self.out/'physical_evidence.json'))
            self._block('signoff',i);return
        if self.mode=='layout':
            if not evidence.gds or evidence.checks.get('expected_top',{}).get('status')!='PASS':
                i=self.issues.add('PHYSICAL.LAYOUT_NOT_FOUND','ERROR','PHYSICAL','physical',
                    'Partial LibreLane run ended, but no usable GDS with the expected top was found.',
                    remedy='Inspect physical.log, the run step outputs, and the selected stream-out stage.')
                self._done('physical','FAIL',issue_id=i.issue_id);return
            self._done('physical','PASS',gds=evidence.gds,
                       flow_stop='KLayout.StreamOut',verification='NOT_PERFORMED',
                       floorplan_enforcement='GUIDE_ONLY' if 'module_floorplan' in self.result.files else 'NOT_REQUESTED')
            self._done('signoff','DEFERRED',reason='Select Verify Existing Layout to resume LibreLane checks')
            return
        self._done('physical','PASS',evidence=str(self.out/'physical_evidence.json'),gds=evidence.gds,
                   checks=evidence.checks)
        missing=[k for k,v in evidence.checks.items() if v['status']=='UNVERIFIED']
        if missing:
            self.issues.add('PHYSICAL.CHECKS_UNVERIFIED','WARNING','PHYSICAL','signoff',
                f'No usable evidence for required checks: {missing}.',
                evidence={'checks':evidence.checks},remedy='Review LibreLane configuration and final metrics for missing checks.')
        self.issues.add('PHYSICAL.SIGNOFF_UNVERIFIED','WARNING','PHYSICAL','signoff',
            'A real nonempty GDS layout exists, but manufacturing signoff has not been independently established.',
            cause='PDK/foundry mask data and exhaustive signoff evidence are not certified by Chip Compiler.',
            remedy='Qualify every required DRC/LVS/timing/corner/antenna/power check and mask preparation with your PDK.')
        self._done('signoff','UNAVAILABLE',reason='Foundry-qualified independent signoff not established')

    def _verify_existing_layout(self):
        """Resume post-stream-out checks without re-generating or overwriting RTL/GDS.

        Source changes after generation do not alter the design under test;
        the saved handoff is hashed and checked before LibreLane resumes.
        """
        from .physical_flow import verify_handoff_inputs
        prior_file=self.out/'report.json'
        layout_file=self.out/'layout_artifacts.json'
        handoff_file=self.out/'physical_handoff.json'
        if not (prior_file.is_file() and layout_file.is_file() and handoff_file.is_file()):
            i=self.issues.add('VERIFY.NO_LAYOUT','ERROR','CONFIG','verification',
                'No PICADS-produced physical layout and input handoff available in build/latest.',
                remedy='Generate Physical Layout first, then run Verify Existing Layout.')
            self._done('verification','BLOCKED',issue_id=i.issue_id);return
        previous=json.loads(prior_file.read_text(encoding='utf-8'))
        manifest=json.loads(layout_file.read_text(encoding='utf-8'))
        handoff=json.loads(handoff_file.read_text(encoding='utf-8'))
        if previous.get('mode')!='layout' or previous.get('stages',{}).get('physical',{}).get('status')!='PASS':
            i=self.issues.add('VERIFY.NOT_PARTIAL_LAYOUT','ERROR','CONFIG','verification',
                'The latest layout was not produced by the separately resumable layout workflow.',
                remedy='Generate Physical Layout using the new button first; older full runs are not resumable here.')
            self._done('verification','BLOCKED',issue_id=i.issue_id);return
        gds=(self.out/manifest['gds_relative_to_build']).resolve()
        if not gds.is_relative_to(self.out.resolve()) or not gds.is_file():
            i=self.issues.add('VERIFY.LAYOUT_MISSING','ERROR','FILESYSTEM','verification',
                'Previously generated GDS was moved or removed. Rebuild the layout.')
            self._done('verification','BLOCKED',issue_id=i.issue_id);return
        from .physical_flow import artifact_hash
        if manifest.get('gds_sha256')!=artifact_hash(gds):
            i=self.issues.add('VERIFY.GDS_CHANGED','ERROR','FILESYSTEM','verification',
                'The saved GDS differs from the original layout artifact.',
                remedy='Regenerate the layout to verify the correct original geometry.')
            self._done('verification','BLOCKED',issue_id=i.issue_id);return
        if not verify_handoff_inputs(handoff):
            i=self.issues.add('VERIFY.INPUT_CHANGED','ERROR','FILESYSTEM','verification',
                'The original netlist or PDK configuration changed since GDS generation.',
                remedy='Regenerate layout before verifying so checks match the design.')
            self._done('verification','BLOCKED',issue_id=i.issue_id);return
        self._done('layout_reuse','PASS',gds=str(gds),bytes=gds.stat().st_size,
                   no_resynthesis=True,no_replacement_of_gds=True)
        prior_tag=manifest['run_tag']
        from .project import open_project
        self.project=open_project(self.root,self.issues)
        if self.project is None:return
        dls_path=Path(previous.get('files',{}).get('dls',''))
        snapshot=self.out/'layout_source_snapshot.py'
        if dls_path.is_file() and snapshot.is_file():
            original=snapshot.read_text(encoding='utf-8')
            dls=DLS.load(dls_path)
            functional=verify(original,dls,self.issues)
            functional_path=self.out/'layout_verification_equivalence.json'
            atomic_write(functional_path,json.dumps(functional.as_dict(),indent=2))
            self.result.files['dls']=str(dls_path)
            self.result.files['equivalence']=str(functional_path)
            self._done('equivalence',functional.status,vectors=functional.vectors,exhaustive=functional.exhaustive,
                       provenance='saved source snapshot + saved DLS')
            if functional.status in ('FAIL','ERROR'):
                i=self.issues.add('VERIFY.FUNCTIONAL_FAIL','ERROR','VERIFIER','equivalence',
                    'The saved generated DLS failed source equivalence. Physical verification not run.')
                self._done('verification','BLOCKED',issue_id=i.issue_id);return
        else:
            i=self.issues.add('VERIFY.SOURCE_SNAPSHOT_MISSING','ERROR','FILESYSTEM','equivalence',
                 'Saved source snapshot or DLS is missing, so separate functional verification is not possible.',
                 remedy='Regenerate the layout with the two-stage workflow.')
            self._done('verification','BLOCKED',issue_id=i.issue_id);return
        settings=self.project.config.get('physical') or {}
        if settings.get('pdk')!=handoff.get('pdk'):
            i=self.issues.add('VERIFY.PDK_CHANGED','ERROR','CONFIG','verification',
                'The configured project PDK differs from the PDK used to generate the existing GDS.',
                remedy='Restore the original PDK setting or regenerate the layout.')
            self._done('verification','BLOCKED',issue_id=i.issue_id);return
        backend=(self.project.config.get('tools') or {}).get('execution','native')
        distro=(self.project.config.get('tools') or {}).get('wsl_distribution')
        options={'runner':backend,'wsl_distribution':distro} if backend=='wsl' else {}
        cmd=['librelane']+(['--dockerized'] if backend=='wsl' or settings.get('dockerized') else [])
        if settings.get('pdk_root'):
            cmd+=['--pdk-root',str(settings['pdk_root'])]
        cmd+=['--pdk',str(settings.get('pdk','sky130A')),'--run-tag',prior_tag,
              '--from','KLayout.Render','config.json']
        self._done('verification_resume','RUNNING',start='KLayout.Render',run_tag=prior_tag,
                   existing_layout=str(gds))
        result=run_external(cmd,self.out,self.out,self.issues,self.events,'layout_verification',
                            timeout=int(settings.get('timeout_s',3600)),**options)
        if result['status']!='PASS':
            self._done('verification','FAIL',**{k:v for k,v in result.items() if k!='status'})
            return
        if not gds.exists() or artifact_hash(gds)!=manifest.get('gds_sha256'):
            i=self.issues.add('VERIFY.LAYOUT_REMOVED','ERROR','FILESYSTEM','verification',
                'Verification unexpectedly removed the original GDS. Check the run directory.')
            self._done('verification','FAIL',issue_id=i.issue_id);return
        evidence=inspect_librelane(self.out/'runs'/prior_tag,expected_top=manifest['top'])
        file=self.out/'layout_verification_evidence.json'
        atomic_write(file,json.dumps(evidence.as_dict(),indent=2))
        self.result.files['verification_evidence']=str(file)
        if evidence.status=='FAIL':
            i=self.issues.add('VERIFY.PHYSICAL_CHECK_FAIL','ERROR','PHYSICAL','verification',
                'LibreLane verification reported a failed check or missing required layout.',
                evidence=evidence.as_dict())
            self._done('verification','FAIL',issue_id=i.issue_id);return
        self._done('verification','PASS' if all(c['status']=='PASS' for k,c in evidence.checks.items()
                    if k in ('drc_klayout','drc_magic','lvs','antenna')) else 'PARTIAL',
                   checks=evidence.checks,foundry_signoff='NOT_CERTIFIED')

    def _run_source_processes(self):
        """Compile separate source-defined transactional FSMs that run concurrently.

        No cross-module operator sharing or automatic interprocess communication
        is claimed. Per-child equivalence and combined DLS state are checked.
        """
        from .processes import compile_source_processes,check_source_processes
        from .global_sharing import compile_global_source_processes,check_global_source_processes
        sched=self.project.co.get('schedule') or {}
        global_types=sched.get('global_shared_types') or []
        global_enabled=bool(global_types or sched.get('global_shared_memory'))
        builder=compile_global_source_processes if global_enabled else compile_source_processes
        checker=check_global_source_processes if global_enabled else check_source_processes
        try:
            self.dls=builder(self.project.source,
                  self.project.mcd.get('concurrent_clients'),self.project.co,
                  self.project.top,self.issues)
            path=self.out/(self.dls.name+'.dls');self.dls.save(path)
            self.result.files['dls']=str(path)
            self._done('generate','PASS',stats=self.dls.stats(),
                       clients=len(self.dls.metadata['schedule']['source_bindings']),
                       global_shared_units=self.dls.metadata['schedule'].get('shared_physical_units',{}))
            if global_enabled:
                path=self.out/'global_schedule.json'
                atomic_write(path,json.dumps(self.dls.metadata['schedule'],indent=2,sort_keys=True))
                self.result.files['global_schedule']=str(path)
                self._done('scheduling','PASS',mode='global_source_processes',
                      physical_shared_units=self.dls.metadata['schedule']['shared_physical_units'],
                      arbitration='independent round-robin per operator')
        except DiagnosticException as exc:
            self._done('generate','FAIL',issue_id=exc.issue.issue_id)
            self._block('equivalence',exc.issue);self._block('export',exc.issue);return
        except (ValueError,TypeError,SyntaxError) as exc:
            issue=self.issues.add('MCD.PROCESS_GENERATION','ERROR','MCD','generate',str(exc))
            self._done('generate','FAIL',issue_id=issue.issue_id)
            self._block('equivalence',issue);self._block('export',issue);return
        evidence=(checker(self.project.source,self.dls,self.issues,rounds=14)
                  if global_enabled else checker(self.project.source,self.dls,self.issues,random_vectors=14))
        atomic_write(self.out/'process_verification.json',json.dumps(evidence,indent=2,sort_keys=True))
        self.result.files['process_verification']=str(self.out/'process_verification.json')
        if evidence['status']!='PASS':
            issue=self.issues.add('VERIFY.PROCESS_EQUIVALENCE','ERROR','VERIFIER','equivalence',
                'Parallel process DLS failed sampled source or state-isolation verification.',
                evidence=evidence,remedy='Inspect process_verification.json; do not export this design.')
            self._done('equivalence','FAIL',issue_id=issue.issue_id)
            self._block('export',issue);return
        memory_shared=self.dls.metadata['schedule'].get('global_shared_memory',False)
        self._done('equivalence','PASS_PROTOCOL_AND_ISOLATED_SAMPLED' if memory_shared else 'PASS_SAMPLED',
                   clients=len(self.dls.metadata['schedule']['source_bindings']),
                   verification=(evidence.get('verification') if memory_shared else
                                 'Independent sampled source scoreboard with shared contention' if global_enabled
                                 else 'Sampled source equivalence plus directed concurrent-state check'),
                   concurrent_atomic_source_equivalence=('NOT_PROVEN' if memory_shared else 'NOT_APPLICABLE'))
        try:
            rtl=self.out/(self.dls.name+'.v');export_verilog(self.dls,rtl)
            self.result.files['verilog']=str(rtl)
            self._done('export','PASS',path=str(rtl))
        except Exception as exc:
            issue=self.issues.add('EXPORT.VERILOG','ERROR','DLS','export',str(exc))
            self._done('export','FAIL',issue_id=issue.issue_id);return
        if (self.project.config.get('verification') or {}).get('external_rtl',False):
            from .rtl_check import check_rtl
            opts=self.project.config.get('tools') or {}
            result=check_rtl(self.dls,rtl,self.out,self.issues,self.events,
                run_options={'runner':opts.get('execution','native'),
                             'wsl_distribution':opts.get('wsl_distribution')},
                vector_count=(self.project.config.get('verification') or {}).get('rtl_vectors',128))
            self._done('rtl_check',result['status'],**{k:v for k,v in result.items() if k!='status'})
            if result['status']!='PASS':return
        if self.mode!='compile':return self._run_native_flow(rtl)

    def _run_fabric(self):
        """Compile a reusable multi-client controller, not a behavioral source function.

        Source equivalence is explicitly NOT_APPLICABLE. An independent protocol
        regression provides the actual verification evidence instead.
        """
        from .concurrent import concurrent_fabric,FabricConfig
        from .tagged import tagged_fabric,TaggedFabricConfig
        from .tagged_verify import check_tagged_protocol,randomized_tagged_check
        from .fabric_verify import check_fabric_protocol,randomized_fabric_check
        from .memory_verify import check_external_memory
        mode=(self.project.co.get('schedule') or {}).get('mode')
        try:
            if mode=='concurrent_fabric':
                spec=FabricConfig(**(self.project.co.get('fabric') or {}))
                self.dls=concurrent_fabric(spec,self.project.top)
            else:
                spec=TaggedFabricConfig(**(self.project.co.get('fabric') or {}))
                if mode=='axi_lite_fabric':
                    from .axi_lite import axi_tagged_fabric
                    self.dls=axi_tagged_fabric(spec,self.project.top)
                elif mode=='bound_fabric':
                    from .source_binding import bound_source_fabric
                    self.dls=bound_source_fabric(self.project.source,self.project.mcd.get('concurrent_clients'),
                                                 spec,self.project.top)
                else:
                    self.dls=tagged_fabric(spec,self.project.top)
            dls_path=self.out/(self.dls.name+'.dls')
            self.dls.save(dls_path)
            self.result.files['dls']=str(dls_path)
            self._done('generate','PASS',stats=self.dls.stats(),spec=spec.__dict__)
        except (ValueError,TypeError) as exc:
            issue=self.issues.add('CO.FABRIC_GENERATION','ERROR','CO','generate',str(exc),
                cause='Invalid concurrent resource fabric configuration.',
                remedy='Correct CO.fabric and rerun the design.')
            self._done('generate','FAIL',issue_id=issue.issue_id)
            self._block('protocol_check',issue);self._block('export',issue)
            return
        self._done('equivalence','NOT_APPLICABLE',
                   reason='This design is an MCD/CO hardware service primitive, not a compiled source function.')
        self.issues.add('VERIFY.FABRIC_NO_SOURCE_EQUIVALENCE','WARNING','VERIFIER','equivalence',
                        'A resource service fabric is not source-equivalence proven; bound functions have restricted, validated operations only.',
                        remedy='Use protocol test evidence, an independent RTL simulator and formal properties before fabrication.')
        if mode=='axi_lite_fabric':
            from .axi_verify import check_axi_lite_protocol
            evidence=check_axi_lite_protocol(self.dls,tagged=True)
        elif spec.memory_backend=='external':
            evidence=check_external_memory(self.dls,tagged=mode!='concurrent_fabric')
        else:
            evidence=(check_fabric_protocol(self.dls,spec) if mode=='concurrent_fabric' else
                      check_tagged_protocol(self.dls,spec) if mode=='tagged_fabric' else
                      {'status':'PASS','checks':0,'scenarios':['type-checked MCD source bindings']})
        scoreboards=[]
        if evidence['status']=='PASS':
            for seed in (() if spec.memory_backend=='external' and mode=='concurrent_fabric' else (8291,29471,19013)):
                if mode=='axi_lite_fabric':
                    from .axi_verify import randomized_axi_lite_check
                    row=randomized_axi_lite_check(self.dls,tagged=True,seed=seed)
                else:
                    row=(randomized_fabric_check(self.dls,spec,cycles=160,seed=seed) if mode=='concurrent_fabric'
                         else randomized_tagged_check(self.dls,spec,cycles=130,seed=seed))
                scoreboards.append(row)
                if row['status']!='PASS':
                    evidence={'status':'FAIL','scenario':'randomized independent scoreboard',
                              'counterexample':row,'deterministic':evidence}
                    break
        if evidence['status']=='PASS':evidence['randomized_scoreboards']=scoreboards
        atomic_write(self.out/'fabric_protocol.json',json.dumps(evidence,indent=2,sort_keys=True))
        self.result.files['fabric_protocol']=str(self.out/'fabric_protocol.json')
        if evidence['status']!='PASS':
            issue=self.issues.add('VERIFY.FABRIC_PROTOCOL','ERROR','VERIFIER','protocol_check',
                       'Concurrent fabric did not satisfy the protocol reference tests.',
                       evidence=evidence,remedy='Inspect fabric_protocol.json and replay the failing vector.')
            self._done('protocol_check','FAIL',issue_id=issue.issue_id)
            self._block('export',issue);return
        self._done('protocol_check','PASS',scenarios=evidence['scenarios'],checks=evidence['checks'],random_seeds=[x['seed'] for x in scoreboards])
        try:
            rtl=self.out/(self.dls.name+'.v')
            export_verilog(self.dls,rtl)
            self.result.files['verilog']=str(rtl)
            self._done('export','PASS',path=str(rtl))
        except Exception as exc:
            issue=self.issues.add('EXPORT.VERILOG','ERROR','DLS','export',str(exc))
            self._done('export','FAIL',issue_id=issue.issue_id);return
        if (self.project.config.get('verification') or {}).get('external_rtl',False):
            from .rtl_check import check_rtl
            cfg=self.project.config.get('tools') or {}
            opts={'runner':cfg.get('execution','native'), 'wsl_distribution':cfg.get('wsl_distribution')}
            result=check_rtl(self.dls,rtl,self.out,self.issues,self.events,run_options=opts,
                      vector_count=(self.project.config.get('verification') or {}).get('rtl_vectors',128))
            self._done('rtl_check',result['status'],**{k:v for k,v in result.items() if k!='status'})
            if result['status']!='PASS':
                if self.mode in ('build','physical'):
                    self._block('yosys',result.get('issue_id'))
                    self._block('physical',result.get('issue_id'))
                return
        if self.mode=='compile':return
        return self._run_native_flow(rtl)
