"""Structured, causally-aware issues. A blocked stage is NOT an independent error."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable
from pathlib import Path
import json, datetime, traceback, uuid

VALID_SEVERITY = {'ERROR', 'WARNING', 'INFO', 'BLOCKED'}
VALID_ORIGIN = {'SOURCE', 'MCD', 'CO', 'DLS', 'GENERATOR', 'SIMULATOR', 'VERIFIER', 'CONFIG', 'DEPENDENCY', 'TOOL', 'PHYSICAL', 'FILESYSTEM', 'INTERNAL'}

@dataclass
class Issue:
    code: str
    severity: str
    origin: str
    stage: str
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    cause: str = ''
    remedy: str = ''
    evidence: dict[str, Any] = field(default_factory=dict)
    blocked_by: list[str] = field(default_factory=list)
    issue_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        if self.severity not in VALID_SEVERITY: raise ValueError('invalid severity')
        if self.origin not in VALID_ORIGIN: raise ValueError('invalid origin')
        if self.severity == 'BLOCKED' and not self.blocked_by:
            raise ValueError('BLOCKED diagnostic must identify an upstream issue')

    def as_dict(self) -> dict: return asdict(self)
    def __str__(self) -> str:
        location = f' {self.file}:{self.line or "?"}' if self.file else ''
        link = f' [blocked by {", ".join(self.blocked_by)}]' if self.blocked_by else ''
        return f'[{self.severity}] {self.code} [{self.origin}/{self.stage}]{location}: {self.message}{link}'

class IssueCollector:
    def __init__(self):
        self.issues: list[Issue] = []
        self._keys: set[tuple] = set()

    def add(self, code: str, severity: str, origin: str, stage: str, message: str, **kwargs) -> Issue:
        key = (code, origin, stage, kwargs.get('file'), kwargs.get('line'), message)
        if key in self._keys:
            return next(i for i in self.issues if (i.code,i.origin,i.stage,i.file,i.line,i.message) == key)
        i = Issue(code, severity, origin, stage, message, **kwargs)
        self._keys.add(key)
        self.issues.append(i)
        return i

    def blocked(self, stage: str, parents: Iterable[Issue | str], message='Stage skipped because a required input failed') -> Issue:
        ids = [i.issue_id if isinstance(i, Issue) else i for i in parents]
        return self.add('PIPELINE.BLOCKED', 'BLOCKED', 'DEPENDENCY', stage, message, blocked_by=ids,
                        cause='Prerequisite stage did not produce trustworthy output.',
                        remedy='Resolve the referenced upstream issues, then rerun this stage.')

    @property
    def errors(self): return [i for i in self.issues if i.severity == 'ERROR']
    @property
    def warnings(self): return [i for i in self.issues if i.severity == 'WARNING']
    def as_dict(self) -> list[dict]: return [i.as_dict() for i in self.issues]

    def internal_exception(self, stage: str, exc: BaseException) -> Issue:
        return self.add('INTERNAL.UNEXPECTED', 'ERROR', 'INTERNAL', stage,
                        f'{type(exc).__name__}: {exc}',
                        cause='Unexpected implementation exception; not classified as a user source error.',
                        remedy='Preserve the diagnostic bundle and report the traceback.',
                        evidence={'traceback': ''.join(traceback.format_exception(exc))})

class DiagnosticException(Exception):
    def __init__(self, issue: Issue):
        self.issue = issue
        super().__init__(str(issue))

class EventLog:
    """Append-only JSONL diagnostic trace. Every event includes a stage and correlation ID."""
    def __init__(self, path: Path, run_id: str | None = None):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex[:12]
    def emit(self, stage: str, action: str, **fields):
        event = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 'run_id': self.run_id, 'stage': stage, 'action': action, **fields}
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str, sort_keys=True) + '\n')
        return event
