"""Project loading, independent config diagnostics, safe file handling, backups."""
from __future__ import annotations
import os, json, tempfile, hashlib, shutil, zipfile, time, uuid, datetime, ast
from pathlib import Path
from dataclasses import dataclass
import yaml
from .diagnostics import IssueCollector

PROJECT_FILE='chip.yaml'

@dataclass
class ChipProject:
    root:Path
    config:dict
    mcd:dict
    co:dict
    source_file:Path
    source:str
    source_kind:str="python"
    original_source:str=""
    translation:dict|None=None

    @property
    def top(self):return self.mcd.get('top',self.config.get('top','calculate'))
    @property
    def name(self):return self.config.get('name',self.root.name)
    @property
    def state_dir(self):return self.root/'.chipcompiler'


def safe_path(root:Path, raw:str)->Path:
    p=(root/raw).resolve();r=root.resolve()
    if not p.is_relative_to(r):raise ValueError(f'Project reference escapes project root: {raw}')
    return p

def load_yaml(root:Path, path:str, issues:IssueCollector,origin:str,required=True)->dict:
    try:
        target=safe_path(root,path)
        if not target.is_file():
            if required:issues.add(f'{origin}.NOT_FOUND','ERROR',origin,'load',f'File not found: {path}',file=path,
                                   cause='Project declares a missing file.',remedy='Correct the path or restore the file.')
            return {}
        obj=yaml.safe_load(target.read_text(encoding='utf-8'))
        if obj is None:return {}
        if not isinstance(obj,dict):raise ValueError('Root must be a YAML mapping.')
        return obj
    except (OSError,ValueError,yaml.YAMLError) as exc:
        issues.add(f'{origin}.PARSE','ERROR',origin,'load',str(exc),file=path,
                   cause='Invalid YAML or inaccessible configuration.',remedy='Fix YAML syntax and paths.')
        return {}

def open_project(path:Path,issues:IssueCollector)->ChipProject|None:
    root=Path(path).expanduser().resolve()
    config=load_yaml(root,PROJECT_FILE,issues,'CONFIG')
    if not config:return None
    for key in ('name','mcd','source'):
        if key not in config and not (key=='source' and 'source' in config):
            issues.add('CONFIG.MISSING_KEY','ERROR','CONFIG','load',f'Missing required key {key!r}',file=PROJECT_FILE,
                       remedy=f'Add {key}: to chip.yaml.')
    tool_settings=config.get('tools',{}) or {}
    if not isinstance(tool_settings,dict):
        issues.add('CONFIG.TOOLS','ERROR','CONFIG','load','tools must be a mapping.',file=PROJECT_FILE)
    else:
        for field in tool_settings:
            if field not in ('execution','wsl_distribution'):
                issues.add('CONFIG.TOOL_UNKNOWN','WARNING','CONFIG','load',f'Unknown tool setting {field!r} is not applied.',file=PROJECT_FILE)
        if tool_settings.get('execution','native') not in ('native','wsl'):
            issues.add('CONFIG.TOOL_EXECUTION','ERROR','CONFIG','load','tools.execution must be native or wsl.',file=PROJECT_FILE)
    verification=config.get('verification',{}) or {}
    if not isinstance(verification,dict):
        issues.add('CONFIG.VERIFICATION_FORMAT','ERROR','CONFIG','load',
                   'verification must be a mapping.',file=PROJECT_FILE)
    else:
        for field in verification:
            if field not in ('native_c','external_rtl','rtl_vectors'):
                issues.add('CONFIG.VERIFICATION_UNKNOWN','ERROR','CONFIG','load',
                           f'Unknown verification directive {field!r} is not applied.',file=PROJECT_FILE)
        for field in ('native_c','external_rtl'):
            if field in verification and type(verification[field])!=bool:
                issues.add('CONFIG.VERIFICATION_FLAG','ERROR','CONFIG','load',
                           f'verification.{field} must be true or false.',file=PROJECT_FILE)
        vectors=verification.get('rtl_vectors',64)
        if type(vectors)!=int or not 1<=vectors<=256:
            issues.add('CONFIG.RTL_VECTORS','ERROR','CONFIG','load',
                       'verification.rtl_vectors must be an integer between 1 and 256.',file=PROJECT_FILE)
    mcd=load_yaml(root,config.get('mcd','design.mcd'),issues,'MCD')
    co_path=config.get('co')
    co=load_yaml(root,co_path,issues,'CO',required=True) if co_path else {}
    src=config.get('source') or mcd.get('source') or ''
    try:
        source_file=safe_path(root,src) if src else root/'<missing-source>'
        if source_file.is_file(): text=source_file.read_text(encoding='utf-8')
        else:
            text='';issues.add('SOURCE.NOT_FOUND','ERROR','SOURCE','load',f'Source file not found: {src}',file=src,
                              remedy='Provide source in chip.yaml and ensure the file exists.')
    except (OSError,ValueError,UnicodeError) as exc:
        source_file=root/'<invalid-source>';text=''
        issues.add('SOURCE.READ','ERROR','SOURCE','load',str(exc),file=src)
    known_arch={'adder':('auto','prefix','ripple')}
    allocation=co.get('allocation',{})
    if not isinstance(allocation,dict):
        issues.add('CO.ALLOCATION_FORMAT','ERROR','CO','load','allocation must be a mapping.',file=co_path)
        allocation={}
    else:
        for key in allocation:
            if key not in ('sharing','max_instances'):
                issues.add('CO.ALLOCATION_UNKNOWN','ERROR','CO','load',f'Unknown allocation key {key!r}.',file=co_path)
        if allocation.get('sharing','auto') not in ('auto','off','force'):
            issues.add('CO.SHARING','ERROR','CO','load','allocation.sharing must be auto, off or force.',file=co_path)
        limits=allocation.get('max_instances',{})
        if not isinstance(limits,dict):
            issues.add('CO.LIMIT_FORMAT','ERROR','CO','load','allocation.max_instances must map operator types to positive integers.',file=co_path)
        else:
            for kind,count in limits.items():
                if kind not in ('ADD','SUB','MUL','AND','OR','XOR') or type(count)!=int or count<1:
                    issues.add('CO.INVALID_LIMIT','ERROR','CO','load',f'Invalid resource limit {kind!r}: {count!r}.',file=co_path)

    arch=co.get('architecture',{})
    if not isinstance(arch,dict):
        issues.add('CO.BAD_ARCH','ERROR','CO','load','architecture must be a mapping.',file=co_path);arch={}
    scheduling=co.get('schedule',{})
    if not isinstance(scheduling,dict):
        issues.add('CO.SCHEDULE_TYPE','ERROR','CO','load','schedule must be a mapping.',file=co_path)
    else:
        for field in scheduling:
            if field not in ('pipeline_stages','mode','latencies','ready_types'):
                issues.add('CO.SCHEDULE_UNKNOWN','ERROR','CO','load',f'Unsupported schedule directive {field!r}; not applied.',file=co_path)
        if scheduling.get('mode','spatial') not in ('spatial','time_share','transactional','concurrent_fabric'):
            issues.add('CO.SCHEDULE_MODE','ERROR','CO','load',
                       'schedule.mode must be spatial, time_share, transactional or concurrent_fabric.',file=co_path)
        count=scheduling.get('pipeline_stages',0)
        if scheduling.get('mode') in ('time_share','transactional','concurrent_fabric') and count:
            issues.add('CO.SCHEDULE_CONFLICT','ERROR','CO','load',
                       'Time-shared/transactional modes do not accept pipeline_stages.',file=co_path,
                       remedy='Use schedule.mode: time_share without pipeline_stages, or spatial pipelining.')
        if type(count)!=int or not 0<=count<=32:
            issues.add('CO.PIPELINE_STAGES','ERROR','CO','load',
                       'schedule.pipeline_stages must be an integer in [0, 32].',file=co_path,
                       cause='Invalid scheduling configuration.',
                       remedy='Use 0 to disable pipelining, 1 for a registered output, or 2..32 for staged logic.')
    modules_config=co.get('modules',{})
    if not isinstance(modules_config,dict):
        issues.add('CO.MODULES_TYPE','ERROR','CO','load','modules must be a mapping.',file=co_path)
    else:
        for field in modules_config:
            if field not in ('hierarchy','naming'):
                issues.add('CO.MODULE_UNKNOWN','ERROR','CO','load',f'Unknown CO module setting {field!r}.',file=co_path)
        if modules_config.get('hierarchy','flatten') not in ('flatten','preserve'):
            issues.add('CO.HIERARCHY','ERROR','CO','load',
                       'modules.hierarchy must be flatten or preserve.',file=co_path)
        if modules_config.get('naming','function') not in ('function','mcd'):
            issues.add('CO.MODULE_NAMING','ERROR','CO','load',
                       'modules.naming must be function or mcd.',file=co_path)
        if modules_config.get('naming')=='mcd' and modules_config.get('hierarchy')!='preserve':
            issues.add('CO.NAMING_REQUIRES_HIERARCHY','ERROR','CO','load',
                       'modules.naming: mcd requires modules.hierarchy: preserve.',file=co_path,
                       remedy='Enable hierarchy preservation to expose named module instances.')
    if isinstance(modules_config,dict) and isinstance(scheduling,dict):
        if modules_config.get('hierarchy')=='preserve' and (scheduling.get('pipeline_stages',0) or scheduling.get('mode') in ('time_share','transactional','concurrent_fabric')):
            issues.add('CO.SCHEDULE_HIERARCHY','ERROR','CO','load',
                       'Automatic logic pipelining with preserved module instances is not yet supported.',file=co_path,
                       cause='The stage allocator does not retime across hierarchical module boundaries.',
                       remedy='Use hierarchy: flatten for pipelining, or pipeline_stages: 0 with preserve mode.')
    memory=co.get('memory',{})
    if not isinstance(memory,dict):
        issues.add('CO.MEMORY_FORMAT','ERROR','CO','load','memory must be a mapping.',file=co_path)
    elif memory:
        if scheduling.get('mode')!='transactional':
            issues.add('CO.MEMORY_MODE','ERROR','CO','load',
                       'Explicit memory settings require schedule.mode: transactional.',file=co_path)
        for key in memory:
            if key not in ('depth','data_width'):
                issues.add('CO.MEMORY_UNKNOWN','ERROR','CO','load',f'Unknown memory setting {key!r}.',file=co_path)
        if type(memory.get('depth'))!=int or not 1<=memory.get('depth',0)<=32 or type(memory.get('data_width'))!=int or not 1<=memory.get('data_width',0)<=64:
            issues.add('CO.MEMORY_SPEC','ERROR','CO','load',
                       'memory.depth must be 1..32 and data_width must be 1..64.',file=co_path)
    if isinstance(scheduling,dict):
        if scheduling.get('mode')!='transactional' and (scheduling.get('latencies') or scheduling.get('ready_types')):
            issues.add('CO.SCHEDULE_OPTIONS_MODE','ERROR','CO','load',
                       'latencies and ready_types are only supported in transactional mode.',file=co_path)
        if scheduling.get('mode')=='transactional':
            lat=scheduling.get('latencies',{})
            ready=scheduling.get('ready_types',[])
            valid={'ADD','SUB','MUL','AND','OR','XOR','EQ','NE','LT','LE','GT','GE','NOT','INV','NEG','BOOL_AND','BOOL_OR','READ','WRITE','MOVE','RETURN'}
            if not isinstance(lat,dict) or any(k not in valid or type(v)!=int or not 1<=v<=16 for k,v in lat.items()):
                issues.add('CO.SCHEDULE_LATENCY','ERROR','CO','load','latencies must map supported operation names to integer 1..16.',file=co_path)
            if not isinstance(ready,list) or any(not isinstance(v,str) or v not in valid for v in ready) or len(set(ready))!=len(ready):
                issues.add('CO.SCHEDULE_READY','ERROR','CO','load','ready_types must contain unique supported operation names.',file=co_path)
            limits=allocation.get('max_instances',{}) if isinstance(allocation,dict) else {}
            if isinstance(limits,dict) and any(x!=1 for x in limits.values()):
                issues.add('CO.CFG_RESOURCE_LIMIT','ERROR','CO','load',
                           'Transactional mode currently implements exactly one shared operator of each used type.',
                           file=co_path,remedy='Set each max_instances value to 1 or omit the limits.')
    fabric=co.get('fabric',{})
    if scheduling.get('mode')=='concurrent_fabric':
        from .concurrent import FabricConfig
        if not isinstance(fabric,dict):
            issues.add('CO.FABRIC_FORMAT','ERROR','CO','load',
                       'fabric must be a mapping.',file=co_path)
        else:
            for field in fabric:
                if field not in ('clients','width','depth','operator'):
                    issues.add('CO.FABRIC_UNKNOWN','ERROR','CO','load',
                               f'Unknown fabric setting {field!r}.',file=co_path)
            if not set(fabric)-{'clients','width','depth','operator'}:
                try:FabricConfig(**fabric).validate()
                except (ValueError,TypeError) as exc:
                    issues.add('CO.FABRIC_CONFIG','ERROR','CO','load',str(exc),file=co_path)
            if allocation.get('max_instances') or allocation.get('sharing') not in (None,'auto'):
                issues.add('CO.FABRIC_ALLOCATION','ERROR','CO','load',
                    'concurrent_fabric defines one operator and one memory port; generic allocation directives are not supported.',file=co_path)
            if modules_config.get('hierarchy','flatten')!='flatten' or modules_config.get('naming','function')!='function':
                issues.add('CO.FABRIC_HIERARCHY','ERROR','CO','load',
                    'concurrent_fabric cannot be combined with source module hierarchy settings.',file=co_path)
            if memory:
                issues.add('CO.FABRIC_MEMORY','ERROR','CO','load',
                    'Set fabric.depth and fabric.width, not memory, for concurrent_fabric.',file=co_path)
            if scheduling.get('latencies') or scheduling.get('ready_types'):
                issues.add('CO.FABRIC_LATENCY','ERROR','CO','load',
                    'Use the external operator ready/valid protocol, not reservation latency settings.',file=co_path)
    elif fabric:
        issues.add('CO.FABRIC_MODE','ERROR','CO','load',
                   'fabric settings require schedule.mode: concurrent_fabric.',file=co_path)
    for field in co:
        if field not in ('architecture','allocation','schedule','modules','memory','fabric'):
            issues.add('CO.UNSUPPORTED_DIRECTIVE','WARNING','CO','load',
                       f'CO directive {field!r} is not implemented and will NOT affect the generated circuit.',
                       file=co_path,remedy='Remove this directive or add an adapter that interprets and validates it.')
    for key,value in arch.items():
        if key not in known_arch:
            issues.add('CO.UNKNOWN_KEY','WARNING','CO','load',f'Unknown architecture override {key!r} (not applied).',file=co_path,
                       remedy='Remove or implement the setting; it has no effect.')
        elif value not in known_arch[key]:
            issues.add('CO.BAD_VALUE','ERROR','CO','load',f'Invalid {key} setting: {value!r}',file=co_path,
                       remedy=f'Use one of {known_arch[key]}')
    original_text=text
    source_kind='python'
    translation=None
    suffix=source_file.suffix.lower()
    if text and suffix in ('.c','.cpp','.cc','.cxx'):
        source_kind='c-subset' if suffix=='.c' else 'cpp-c-compatible-subset'
        try:
            from .cfrontend import translate_c,CFrontendError
            translated=translate_c(text,suffix)
            text=translated.source
            translation={'origin':str(source_file),'functions':translated.functions,
                         'line_map':translated.line_map,
                         'semantics':translated.subset,'source_line_mapping':'mapped statements (expressions inherit their statement)',
                         'original_sha256':hashlib.sha256(original_text.encode()).hexdigest()}
            issues.add('C.SEMANTICS','WARNING','SOURCE','load',
                'C/C++-compatible syntax translated to ChipCompiler bitvector semantics, not full ISO C/C++. ',
                file=str(source_file),cause='Implicit integer promotions and advanced C/C++ features are intentionally unsupported.',
                remedy='Inspect normalized_source.py and check equivalent behavior with native C/C++ tests when required.')
        except CFrontendError as exc:
            issues.add(exc.code,'ERROR','SOURCE','parse',str(exc),file=str(source_file),line=exc.line,
                       cause='C/C++ source uses unsupported syntax or invalid declarations.',
                       remedy='Use fixed-width pure functions in the documented C-compatible subset.')
            text=''
    elif text and suffix!='.py':
        issues.add('SOURCE.FRONTEND_UNSUPPORTED','ERROR','SOURCE','load',
                   f'Unsupported source extension {source_file.suffix!r}.',file=str(source_file),
                   remedy='Use .py, .c or a C-compatible .cpp/.cc/.cxx source file.')
    if text and suffix in ('.py','.c','.cpp','.cc','.cxx'):
        try: ast.parse(text,filename=str(source_file))
        except SyntaxError as exc:
            issues.add('SOURCE.SYNTAX','ERROR','SOURCE','parse',exc.msg,file=str(source_file),
                       line=exc.lineno,column=exc.offset,remedy='Fix the syntax at the indicated source line.')
    if mcd:
        if mcd.get('top') and not isinstance(mcd['top'],str):
            issues.add('MCD.BAD_TOP','ERROR','MCD','load','top must be a function name.',file=config.get('mcd'))
        modules=mcd.get('modules',[])
        if not isinstance(modules,list):
            issues.add('MCD.BAD_MODULES','ERROR','MCD','load','modules must be a list.',file=config.get('mcd'))
        else:
            for index,module in enumerate(modules):
                if not isinstance(module,dict) or not isinstance(module.get('name'),str):
                    issues.add('MCD.BAD_MODULE','ERROR','MCD','load',
                               f'modules[{index}] must be a mapping with a string name.',file=config.get('mcd'))
        for module in modules if isinstance(modules,list) else []:
            if not isinstance(module,dict):continue
            for field in module:
                if field not in ('name','purpose','function','inputs','outputs'):
                    issues.add('MCD.MODULE_FIELD','WARNING','MCD','load',
                               f'Unsupported module field {field!r} in {module.get("name","?")!r}; not applied.',file=config.get('mcd'))
            for direction in ('inputs','outputs'):
                if direction not in module:continue
                ports=module[direction]
                if not isinstance(ports,dict) or any(not isinstance(k,str) or type(v)!=int or not 1<=v<=4096 for k,v in ports.items()):
                    issues.add('MCD.PORTS_FORMAT','ERROR','MCD','load',
                        f'Module {module.get("name")!r} {direction} must map signal names to bit widths.',
                        file=config.get('mcd'))
            if module.get('function') is not None and not isinstance(module.get('function'),str):
                issues.add('MCD.FUNCTION_TYPE','ERROR','MCD','load',
                           f'Module {module.get("name")!r} has non-string function binding.',file=config.get('mcd'))
            if isinstance(module.get('function'),str) and text:
                try:
                    funcs={n.name for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
                    if module['function'] not in funcs:
                        issues.add('MCD.FUNCTION_NOT_FOUND','ERROR','MCD','load',
                                   f'MCD module {module["name"]!r} references missing function {module["function"]!r}.',
                                   file=config.get('mcd'),remedy='Correct the module function binding or provide the implementation.')
                except SyntaxError:pass

        if 'network' in mcd and not isinstance(mcd['network'],dict):
            issues.add('MCD.NETWORK_TYPE','ERROR','MCD','load',
                       'MCD network must be a mapping with instances and outputs.',file=config.get('mcd'))
        required=mcd.get('requires',[])
        if not isinstance(required,list):
            issues.add('MCD.REQUIRES','ERROR','MCD','load','requires must be a list.',file=config.get('mcd'))
        else:
            for index,requirement in enumerate(required):
                if isinstance(requirement,str) and requirement:
                    continue
                if (isinstance(requirement,dict) and
                    set(requirement).issubset({'function','module','min_instances'}) and
                    bool(set(requirement)&{'function','module'}) and
                    not ('function' in requirement and 'module' in requirement) and
                    isinstance(requirement.get('function',requirement.get('module')),str) and
                    bool(requirement.get('function',requirement.get('module'))) and
                    type(requirement.get('min_instances',1))==int and requirement.get('min_instances',1)>=1):
                    continue
                issues.add('MCD.REQUIRES_FORMAT','ERROR','MCD','load',
                    f'Invalid requires[{index}]: expected module/function name or '
                    '{function: name, min_instances: positive_integer}.',
                    file=config.get('mcd'),
                    evidence={'requirement':requirement},
                    remedy='Specify a valid and unambiguous mandatory source function.')
        # Unsupported declarations are visible, never secretly interpreted as implemented.
        for key in mcd:
            if key not in ('top','description','modules','source','requires','interface','network'):
                issues.add('MCD.UNKNOWN_KEY','WARNING','MCD','load',f'Unrecognized MCD field {key!r} was not applied.',file=config.get('mcd'))
    return ChipProject(root,config,mcd,co,source_file,text,source_kind,original_text,translation)

def atomic_write(path:Path,contents:str|bytes):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.part',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(contents.encode('utf-8') if isinstance(contents,str) else contents)
            f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def snapshot(root:Path,label:str='autosave', max_versions:int=30)->dict:
    """Only working source/config snapshots, no huge generated physical build outputs."""
    root=Path(root).resolve()
    if not (root/PROJECT_FILE).is_file():raise FileNotFoundError('Not a Chip Compiler project')
    tag=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    backup_dir=root/'.chipcompiler'/'snapshots';backup_dir.mkdir(parents=True,exist_ok=True)
    destination=backup_dir/(tag+'.zip')
    temporary=backup_dir/(tag+'.pending')
    tracked=[];excluded=[]
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in sorted(root.rglob('*')):
                if not p.is_file() or '.chipcompiler' in p.relative_to(root).parts or 'build' in p.relative_to(root).parts or '.git' in p.relative_to(root).parts:continue
                rel=p.relative_to(root).as_posix()
                if p.is_symlink():excluded.append({'path':rel,'reason':'symbolic link not followed'});continue
                if p.stat().st_size>16*1024*1024:
                    excluded.append({'path':rel,'reason':'file exceeds 16 MiB snapshot limit'});continue
                z.write(p,rel);tracked.append(rel)
            z.writestr('_snapshot_manifest.json',json.dumps({'label':label,'created_utc':tag,'files':tracked,'excluded':excluded}))
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    hashes={r:hashlib.sha256((root/r).read_bytes()).hexdigest() for r in tracked}
    atomic_write(backup_dir/(tag+'.json'),json.dumps({'snapshot':destination.name,'files':hashes,'excluded':excluded,'label':label},indent=2))
    versions=sorted(backup_dir.glob('*.zip'),key=lambda p:p.name)
    for old in versions[:-max_versions]:
        old.unlink();old.with_suffix('.json').unlink(missing_ok=True)
    return {'file':str(destination),'count':len(tracked),'excluded':excluded,'label':label}

def restore(root:Path,archive:Path,confirm=False)->dict:
    """Safe restore creates pre-restore snapshot and rejects Zip Slip paths."""
    if not confirm:raise ValueError('Restore requires explicit confirm=True')
    root=Path(root).resolve();archive=Path(archive).resolve()
    if not archive.is_file():raise FileNotFoundError(str(archive))
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name=='_snapshot_manifest.json':continue
            safe_path(root,name)
        pre=snapshot(root,'pre-restore')
        restored=[]
        for name in z.namelist():
            if name=='_snapshot_manifest.json' or name.endswith('/'):continue
            target=safe_path(root,name)
            atomic_write(target,z.read(name));restored.append(name)
    return {'restored':restored,'pre_restore_snapshot':pre['file']}
