"""CLI handlers for explicitly scheduled local work; status never starts processes."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import runtime
from .scoring import score_artifacts
from .spec import EvoError, load_spec
from .store import Store

ACTIONS = {'init', 'submit', 'run', 'resume', 'recover', 'status', 'resources', 'watch', 'pause', 'cancel', 'results', 'trace'}


def study_id(value: str) -> int:
    value = value.removeprefix('s')
    if not value.isdecimal() or int(value) < 1:
        raise EvoError('study must be s followed by a positive integer')
    return int(value)


def job_id(value: str) -> int:
    value = value.removeprefix('j')
    if not value.isdecimal() or int(value) < 1:
        raise EvoError('job must be j followed by a positive integer')
    return int(value)


def add_commands(commands) -> None:
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AgentBase' / 'evo'
    for name in sorted(ACTIONS):
        parser = commands.add_parser(name, help={
            'init': 'initialize persistent global resource limits',
            'submit': 'freeze a specification and enqueue selected jobs without running them',
            'run': 'execute queued local jobs with bounded concurrency',
            'resume': 'resume dispatch of a paused study',
            'recover': 'reconcile persisted receipts without rerunning subjects',
            'status': 'show current queue and usage', 'watch': 'monitor progress without a model',
            'resources': 'scan managed disk use and show global execution capacity',
            'pause': 'stop new dispatch; let in-flight jobs settle', 'cancel': 'cancel queued and owned running jobs',
            'results': 'calculate scores from a study snapshot and its receipts',
            'trace': 'read a bounded page of scheduling events',
        }[name])
        parser.add_argument('--state-root', type=Path, default=base / 'state')
        if name == 'init':
            parser.add_argument('--max-concurrency', type=int, default=1)
            parser.add_argument('--model-capacity', type=int, default=4)
            parser.add_argument('--max-disk-mb', type=int, default=4096)
            parser.add_argument('--min-free-mb', type=int, default=1024)
        if name == 'submit':
            parser.add_argument('--spec', type=Path, required=True)
            parser.add_argument('--project-root', type=Path, required=True)
            parser.add_argument('--work-root', type=Path, default=base / 'work')
        if name not in ('init','submit'):
            parser.add_argument('--study', required=name not in ('run','status','resources','watch'))
        if name in ('run', 'resume', 'recover', 'trace'):
            parser.add_argument('--installed-codex-root', type=Path)
        if name == 'recover':
            parser.add_argument('--confirm-not-invoked', type=job_id)
            parser.add_argument('--confirm-stopped', type=job_id,
                                help='attest owned processes have stopped; cancel without claiming complete usage or quality')
            parser.add_argument('--evidence')
            parser.add_argument('--retry-not-invoked', type=job_id)
        if name == 'watch':
            parser.add_argument('--interval', type=float, default=2)
            parser.add_argument('--count', type=int, default=30)
        if name == 'trace':
            parser.add_argument('--job', type=job_id)
            parser.add_argument('--source', choices=('schedule', 'native'), default='schedule')
            parser.add_argument('--agent')
            parser.add_argument('--kind')
            parser.add_argument('--snapshot')
            parser.add_argument('--refresh', action='store_true')
            parser.add_argument('--offset', type=int, default=0)
            parser.add_argument('--limit', type=int, default=50)
        if name == 'status':
            parser.add_argument('--offset', type=int, default=0)
            parser.add_argument('--limit', type=int, default=100)
        if name == 'results':
            parser.add_argument('--artifacts-only', action='store_true')
            parser.add_argument('--spec', type=Path, help='compatible analysis spec for new fields and scoring without rerunning')


def handle(args) -> dict | None:
    store = Store(args.state_root)
    action = args.action
    if action != 'init':
        store.migrate()
    ident = study_id(args.study) if getattr(args, 'study', None) else None
    if action == 'init':
        return {'limits': store.initialize(concurrency=args.max_concurrency, model_capacity=args.model_capacity,
                                          max_disk_mb=args.max_disk_mb, min_free_mb=args.min_free_mb)}
    if action == 'submit':
        return {'study': f's{runtime.submit(store, args.spec, args.project_root, args.work_root)}'}
    if action in ('pause', 'cancel', 'resume'):
        store.control(ident, {'pause':'paused','cancel':'cancelled','resume':'ready'}[action])
    if action in ('run', 'resume'):
        return runtime.run(store, study=ident, installed_codex_root=args.installed_codex_root)
    if action == 'recover':
        confirm_stopped = getattr(args, 'confirm_stopped', None)
        actions = sum(value is not None for value in (args.confirm_not_invoked, args.retry_not_invoked, confirm_stopped))
        if actions > 1 or (actions == 0 and args.evidence is not None) or (actions == 1 and args.evidence is None):
            raise EvoError('choose one reconciliation action and provide --evidence with it')
        return runtime.recover(store, ident, args.installed_codex_root,
                               confirm_not_invoked=args.confirm_not_invoked, evidence=args.evidence,
                               retry_not_invoked=args.retry_not_invoked, confirm_stopped=confirm_stopped)
    if action == 'results':
        from .grading import study_artifacts_with_model_grades
        from .runtime_review import study_artifacts_with_reviews, sync_study_reviews
        sync_study_reviews(store, ident)
        analysis_path = getattr(args, 'spec', None)
        analysis_spec = load_spec(analysis_path) if analysis_path else store.study(ident)['spec']
        facts = runtime.artifacts(store, ident, analysis_spec)
        reviewed = study_artifacts_with_reviews(store, ident)
        if analysis_path is None:
            facts = reviewed
        else:
            assessment_ids = {field['id'] for field in analysis_spec['fields'] if field['grain'] == 'assessment'}
            assessment_rows = []
            for row in reviewed['rows']:
                if row['grain'] != 'assessment':
                    continue
                values = {key: value for key, value in row['values'].items() if key in assessment_ids}
                if values:
                    assessment_rows.append({**row, 'values': values})
            facts = {**facts, 'rows': [*facts['rows'], *assessment_rows]}
            facts['version'] = runtime.fingerprint(facts['rows'])
        facts = study_artifacts_with_model_grades(store, ident, artifacts=facts)
        return facts if args.artifacts_only else score_artifacts(analysis_spec, facts)
    if action == 'resources':
        return runtime.resources(store, ident)
    if action == 'trace':
        return runtime.trace(store, ident, job=args.job, source=args.source, agent=args.agent,
                             kind=args.kind, offset=args.offset, limit=args.limit, snapshot=args.snapshot,
                             refresh=args.refresh, installed_codex_root=args.installed_codex_root)
    if action == 'watch':
        if not .2 <= args.interval <= 60 or not 1 <= args.count <= 10000:
            raise EvoError('watch interval must be .2..60 seconds and count 1..10000')
        previous = None
        from .view import render_model
        for _ in range(args.count):
            value = store.status(ident)
            encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True) if args.view == 'machine'
                       else render_model(value, limit=args.model_token_budget))
            if encoded != previous:
                print(encoded, flush=True)
                previous = encoded
            time.sleep(args.interval)
        return None
    return store.status(ident, offset=getattr(args, 'offset', 0), limit=getattr(args, 'limit', 100))
