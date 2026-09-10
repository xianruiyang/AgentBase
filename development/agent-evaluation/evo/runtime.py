"""Local run lifecycle for Evo. Only explicit run invokes subject processes."""
from __future__ import annotations

import json
import os
import platform
import hashlib
import copy
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Any

from evaluation_core import CaseLock, EvaluationError
from .selection import build_plan
from .spec import ARTIFACT_SCHEMA, EvoError, load_spec, read_json
from .store import ACTIVE, RESOURCE_HELD, Store, canonical, fingerprint, positive


class RetryLater(EvoError):
    """A recoverable capacity wait which must leave the job queued."""


EXECUTION_RECIPE_VERSION = '3'


def inside(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or '..' in candidate.parts:
        raise EvoError(f'expected a relative managed path: {relative}')
    target = (root / candidate).resolve()
    if not target.is_relative_to(root.resolve()):
        raise EvoError(f'path leaves managed root: {relative}')
    cursor = root
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.is_symlink() or (cursor.exists() and cursor.is_junction()):
            raise EvoError(f'managed paths must not traverse links: {relative}')
    return target


def check_roots(project: Path, state: Path, work: Path, codex: Path | None = None) -> None:
    roots = [project.resolve(), state.resolve(), work.resolve()]
    if codex is not None:
        roots.append(codex.resolve())
    for index, a in enumerate(roots):
        for b in roots[index + 1:]:
            if a.is_relative_to(b) or b.is_relative_to(a):
                raise EvoError('project, state, work and installed Codex roots must be disjoint')
    for path in (state, work):
        cursor = path.resolve().anchor
        for part in path.resolve().parts[1:]:
            cursor = Path(cursor) / part
            if cursor.exists() and (cursor.is_symlink() or cursor.is_junction()):
                raise EvoError('state/work roots must not traverse links')


def file_inventory(path: Path, max_bytes: int = 64 * 1024 * 1024) -> list[dict]:
    """Hash selected assets only, with a bound before materialization."""
    import hashlib
    if not path.exists() or path.is_symlink() or path.is_junction():
        raise EvoError(f'source is unavailable or linked: {path}')
    files = [path] if path.is_file() else path.rglob('*')
    result, total = [], 0
    for entry in files:
        if entry.is_symlink() or entry.is_junction():
            raise EvoError(f'source contains a link: {entry}')
        if entry.is_dir():
            continue
        total += entry.stat().st_size
        if total > max_bytes or len(result) >= 4096:
            raise EvoError('selected source exceeds 64 MiB/4096 files; narrow the component')
        result.append({'path': entry.relative_to(path).as_posix() if path.is_dir() else entry.name,
                       'bytes': entry.stat().st_size, 'sha256': hashlib.sha256(entry.read_bytes()).hexdigest()})
    return sorted(result, key=lambda row: row['path'])


def candidate_roots(store: Store, runtime: dict, project: Path, work: Path,
                    installed_codex_root: Path | None = None) -> list[Path]:
    raw_roots = runtime.get('candidate_source_roots', [])
    if not isinstance(raw_roots, list) or any(not isinstance(value, str) or not value for value in raw_roots):
        raise EvoError('runtime.candidate_source_roots must be an array of paths')
    owner = (store.root / 'candidates').resolve()
    roots = []
    for raw in raw_roots:
        raw_path = Path(raw)
        if not raw_path.is_absolute() or '..' in raw_path.parts:
            raise EvoError('candidate source roots must be absolute paths without parent traversal')
        lexical = raw_path.absolute()
        resolved = lexical.resolve()
        if not lexical.is_relative_to(owner) or not resolved.is_relative_to(owner) or not resolved.is_dir():
            raise EvoError('candidate source roots must be existing directories under state-root/candidates')
        cursor = owner
        for part in lexical.relative_to(owner).parts:
            cursor = cursor / part
            if cursor.is_symlink() or (cursor.exists() and cursor.is_junction()):
                raise EvoError('candidate source roots must not traverse links')
        for other in (project.resolve(), work.resolve(), installed_codex_root.resolve() if installed_codex_root else None):
            if other is not None and (resolved.is_relative_to(other) or other.is_relative_to(resolved)):
                raise EvoError('candidate source roots must be disjoint from project, work and installed Codex roots')
        roots.append(resolved)
    if len(roots) != len(set(roots)):
        raise EvoError('candidate source roots must be unique')
    return roots


def execution_sources(spec: dict, job: dict, project: Path, roots: list[Path]) -> dict:
    import agentbase_codex
    combo = next(c for c in spec['combinations'] if c['id'] == job['combination'])
    sources = {}
    for kind, members in combo['members'].items():
        for member in members:
            entry = next(c for c in spec['components'][kind] if c['id'] == member)
            try:
                source = agentbase_codex.resolve_component_source(project, entry['source'], roots)
            except EvaluationError as exc:
                raise EvoError(str(exc)) from exc
            if kind == 'skills' and job.get('runtime', {}).get('adapter') == 'codex':
                from .skill_cache import payload_manifest
                sources[f'{kind}:{member}'] = payload_manifest(project, source)['files']
            else:
                sources[f'{kind}:{member}'] = file_inventory(source)
    for entry in job['runtime'].get('files', []):
        sources['file:' + entry['source']] = file_inventory(inside(project, entry['source']))
    return sources


def execution_recipe(adapter: str, project: Path, *, swe: bool = False, code_reading: bool = False) -> dict:
    paths = [Path(__file__).with_name('env_pool.py')]
    if adapter == 'codex':
        evaluation_root = Path(__file__).resolve().parent.parent
        paths.extend([Path(__file__).with_name('codex_adapter.py'),
                      Path(__file__).with_name('runtime_home.py'),
                      Path(__file__).with_name('skill_cache.py'), Path(__file__).with_name('manage_skill_cache.ps1'),
                      evaluation_root / 'agentbase_codex.py', evaluation_root / 'invoke_candidate.ps1',
                      evaluation_root.parent / 'common' / 'get_payload_manifest.ps1',
                      evaluation_root.parent / 'common' / 'payload_contract.ps1'])
        if swe:
            paths.extend([Path(__file__).with_name('swe_adapter.py'), evaluation_root / 'evaluation_core.py',
                          evaluation_root / 'windows_verifier.py', evaluation_root / 'agent_eval.py'])
        if code_reading:
            paths.extend([Path(__file__).with_name('code_reading_adapter.py'),
                          Path(__file__).with_name('code_reading_catalog.py')])
    files = []
    for path in paths:
        if not path.is_file():
            raise EvoError(f'execution recipe source is unavailable: {path}')
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(block)
        files.append({'name': path.name, 'sha256': digest.hexdigest()})
    return {'schema': 'agentbase-evo-execution-recipe/v1', 'version': EXECUTION_RECIPE_VERSION, 'adapter': adapter,
            'python': platform.python_implementation() + '-' + platform.python_version(), 'files': files}


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def submit(store: Store, spec_path: Path, project: Path, work: Path) -> int:
    project, work = project.resolve(), work.resolve()
    check_roots(project, store.root, work)
    if not project.is_dir():
        raise EvoError('project root must exist')
    spec = load_spec(spec_path)
    jobs = build_plan(spec)['jobs']
    items = {item['id']: item for item in spec['evaluations']['items']}
    for job in jobs:
        item = items[job['item']]
        runtime = {**spec.get('runtime', {}), **item.get('runtime', {})}
        if runtime.get('adapter') not in ('command', 'codex'):
            raise EvoError('runtime.adapter must be command or codex')
        runtime.setdefault('timeout_seconds', 300)
        positive(runtime['timeout_seconds'], 'timeout_seconds', 14400)
        runtime.setdefault('max_agents', 1)
        runtime.setdefault('token_reservation', 100_000)
        if runtime['adapter'] == 'command':
            validate_argv(runtime.get('argv'))
        elif not all(isinstance(runtime.get(k), str) and runtime[k] for k in ('model', 'reasoning_effort')):
            raise EvoError('Codex model and reasoning_effort must be explicitly selected in runtime')
        if runtime.get('swe') is not None and runtime.get('code_reading') is not None:
            raise EvoError('runtime cannot combine SWE and code-reading domain bindings')
        if runtime.get('swe') is not None:
            if runtime['adapter'] != 'codex':
                raise EvoError('runtime.swe requires runtime.adapter=codex')
            from .swe_adapter import validate_runtime as validate_swe_runtime
            runtime['swe'] = validate_swe_runtime(runtime, project_root=project, evo_state_root=store.root,
                                                   evo_work_root=work)
        if runtime.get('code_reading') is not None:
            if runtime['adapter'] != 'codex':
                raise EvoError('runtime.code_reading requires runtime.adapter=codex')
            from .code_reading_adapter import validate_binding as validate_code_reading
            runtime['code_reading'] = validate_code_reading(runtime)
            from .code_reading_adapter import validate_roots as validate_code_reading_roots
            validate_code_reading_roots(runtime['code_reading'], state_root=store.root, work_root=work)
        files = runtime.get('files', [])
        if not isinstance(files, list):
            raise EvoError('runtime.files must be an array')
        targets = set()
        for entry in files:
            if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ('source', 'target')):
                raise EvoError('runtime.files entries require source and target')
            target = inside(work, entry['target'])
            if target == work or target in targets or any(target.is_relative_to(p) or p.is_relative_to(target) for p in targets):
                raise EvoError('runtime file targets overlap')
            targets.add(target)
        job['runtime'] = runtime
        roots = candidate_roots(store, runtime, project, work)
        job['source_inventory'] = execution_sources(spec, job, project, roots)
        job['execution_recipe'] = execution_recipe(runtime['adapter'], project, swe=runtime.get('swe') is not None,
                                                   code_reading=runtime.get('code_reading') is not None)
        job['execution_identity'] = job_identity(spec, job, item)
    return store.submit(spec, jobs, project, work)


def job_identity(spec: dict, job: dict, item: dict) -> str:
    combo = next(c for c in spec['combinations'] if c['id'] == job['combination'])
    # Formula and group membership do not participate in execution identity.
    return fingerprint({'item': item, 'combination': combo,
                        'components': {k: [e for e in spec['components'][k] if e['id'] in combo['members'].get(k, [])] for k in spec['components']},
                        'runtime': job['runtime'], 'sources': job['source_inventory'],
                        'execution_recipe': job['execution_recipe'], 'replicate': job['replicate']})


def validate_argv(argv: Any) -> list[str]:
    if not isinstance(argv, list) or not argv or len(argv) > 256 or any(not isinstance(a, str) or '\x00' in a for a in argv):
        raise EvoError('argv must be a bounded nonempty array of strings')
    return argv


def immutable_json(path: Path, value: dict) -> None:
    payload = canonical(value) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding='utf-8') != payload:
            raise EvoError(f'cannot overwrite an immutable receipt: {path.name}')
        return
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(payload)


def _swe_codex_inputs(study: dict, job: dict, swe_state: dict) -> tuple[dict, dict]:
    spec = copy.deepcopy(study['spec'])
    plan = copy.deepcopy(job['plan'])
    prompt = swe_state['task_prompt']
    item = next(item for item in spec['evaluations']['items'] if item['id'] == plan['item'])
    item.pop('prompt', None)
    item.setdefault('runtime', {})['prompt'] = prompt
    return spec, plan


def _persisted_model_invoked(attempt: Path, known: bool) -> bool:
    raw_path = attempt / 'codex-result.json'
    if raw_path.is_file():
        try:
            return known or read_json(raw_path).get('model_invoked') is True
        except Exception:
            pass
    return known or (attempt / 'codex-rollout-before.json').is_file()


def disk_bytes(*roots: Path, allowed_links: set[Path] | None = None) -> int:
    total = 0
    allowed = {path.absolute() for path in (allowed_links or set())}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob('*'):
            lexical = path.absolute()
            owner = next((link for link in allowed if lexical == link or lexical.is_relative_to(link)), None)
            if owner is not None:
                if lexical == owner and not path.is_junction():
                    raise EvoError('managed skill reference is no longer a junction')
                continue
            if path.is_symlink() or path.is_junction():
                raise EvoError('managed storage contains a link')
            if path.is_file():
                total += path.stat().st_size
    return total


def managed_skill_links(store: Store) -> set[Path]:
    """Validate and enumerate only links registered by the fixed skill cache owner."""
    jobs = {job['id']: job for job in store.jobs()}
    result: set[Path] = set()
    manifests: list[tuple[Path, Path]] = []
    for work_root in store.work_roots():
        for manifest_path in work_root.glob('slot-*/.agentbase/evo-codex-projection.json'):
            slot_meta = manifest_path.parents[1] / '.evo-slot.json'
            if not slot_meta.is_file():
                raise EvoError('workspace projection has no owned slot identity')
            job = jobs.get(read_json(slot_meta).get('job'))
            if job is None:
                raise EvoError('workspace skill reference has no persisted Evo job')
            manifests.append((manifest_path, Path(store.study(job['study'])['project'])))
    for job in jobs.values():
        if job.get('runtime', {}).get('swe') is None:
            continue
        state_path = store.root / 'jobs' / f"j{job['id']}" / 'swe-state.json'
        if state_path.is_file():
            workspace = Path(read_json(state_path).get('workspace', ''))
            manifest_path = workspace / '.agentbase' / 'evo-codex-projection.json'
            if manifest_path.is_file():
                manifests.append((manifest_path, Path(store.study(job['study'])['project'])))
    for manifest_path, project in manifests:
        references = read_json(manifest_path).get('result', {}).get('skill_references', [])
        if not references:
            continue
        from .skill_cache import SkillCache
        cache = SkillCache(project, store.root)
        cache.validate_workspace_references(manifest_path.parents[1], references, content=False)
        result.update(Path(reference['link']).absolute() for reference in references)
    return result


def managed_storage_roots(store: Store, study: int | None = None) -> list[Path]:
    """Return Evo-owned roots; legacy SWE state and cold sources stay external/read-only."""
    roots = [store.root, *store.work_roots()]
    for job in store.jobs():
        swe = job.get('runtime', {}).get('swe')
        if isinstance(swe, dict) and isinstance(swe.get('work_root'), str):
            namespace = swe.get('owner_namespace')
            if isinstance(namespace, str) and namespace:
                roots.append(Path(swe['work_root']) / 'evo' / namespace)
    unique_roots: list[Path] = []
    for root in sorted({path.resolve() for path in roots}, key=lambda path: len(path.parts)):
        if not any(root.is_relative_to(parent) for parent in unique_roots):
            unique_roots.append(root)
    return unique_roots


def resources(store: Store, study: int | None = None) -> dict:
    """Scan managed storage only when explicitly requested; capacity remains global."""
    if study is not None:
        store.study(study)
    unique_roots = managed_storage_roots(store)
    managed_error = None
    try:
        managed = disk_bytes(*unique_roots, allowed_links=managed_skill_links(store))
    except (OSError, EvoError) as exc:
        managed = None
        managed_error = str(exc)[:500]
    volumes = []
    seen_volumes: set[str] = set()
    for root in unique_roots:
        volume = os.path.normcase(root.anchor or str(root))
        if volume in seen_volumes:
            continue
        seen_volumes.add(volume)
        try:
            usage = shutil.disk_usage(root if root.exists() else root.anchor)
            volumes.append({'volume': volume, 'total_bytes': usage.total, 'free_bytes': usage.free,
                            'available': True, 'error': None})
        except OSError as exc:
            volumes.append({'volume': volume, 'total_bytes': None, 'free_bytes': None,
                            'available': False, 'error': str(exc)[:500]})
    all_jobs = store.jobs()
    selected = store.jobs(study)
    held = [job for job in all_jobs if job['state'] in RESOURCE_HELD]
    config = store.config()
    reserved = sum(job['disk_reservation'] for job in held)
    return {'schema': 'agentbase-evo-resources/v1', 'study': f's{study}' if study else None,
            'managed_storage': {'roots': [str(root) for root in unique_roots], 'used_bytes': managed,
                                'complete': managed_error is None, 'error': managed_error,
                                'max_bytes': config['max_disk_mb'] * 1024**2,
                                'min_free_bytes': config['min_free_mb'] * 1024**2,
                                'reserved_bytes': reserved,
                                'used_plus_reserved_bytes': managed + reserved if managed is not None else None},
            'volumes': volumes,
            'capacity': {'active_jobs': len(held), 'job_limit': config['concurrency'],
                         'active_slots': len({job['workspace_slot'] for job in held if job['workspace_slot'] is not None}),
                         'model_slots_used': sum(job['model_slots'] for job in held),
                         'model_slots_limit': config['model_capacity']},
            'reuse': {'jobs': sum(job.get('reused_from') is not None for job in selected),
                      'selected_jobs': len(selected)}}


def prepare_workspace(store: Store, study: dict, job: dict) -> Path:
    project, work = Path(study['project']), Path(study['work'])
    config = store.config()
    from .env_pool import EnvironmentPool
    # Reuse a bounded slot only after the prior receipt and changed evidence are archived.
    work.mkdir(parents=True, exist_ok=True)
    needed = sum(e['bytes'] for entries in job['plan']['source_inventory'].values() for e in entries)
    active_reservations = sum(j['disk_reservation'] for j in store.jobs() if j['state'] in RESOURCE_HELD)
    if disk_bytes(store.root, *store.work_roots(), allowed_links=managed_skill_links(store)) + active_reservations > config['max_disk_mb'] * 1024**2:
        raise RetryLater('managed disk budget is waiting for capacity; preserve evidence or free a cold asset')
    if shutil.disk_usage(work).free - needed < config['min_free_mb'] * 1024**2:
        raise RetryLater('minimum free disk reserve is waiting for capacity')
    roots = candidate_roots(store, job['runtime'], project, work)
    if execution_sources(study['spec'], job['plan'], project, roots) != job['plan']['source_inventory']:
        raise EvoError('selected source changed since submit; create a new frozen study')
    desired: set[str] = set()
    for entry in job['runtime'].get('files', []):
        inventory = job['plan']['source_inventory']['file:' + entry['source']]
        source = inside(project, entry['source'])
        if source.is_dir():
            desired.update((Path(entry['target']) / item['path']).as_posix() for item in inventory)
        else:
            desired.add(Path(entry['target']).as_posix())
    desired_prefixes: set[str] = set()
    if job['runtime']['adapter'] == 'codex':
        slot_root = work / f'slot-{job["workspace_slot"]:04d}'
        meta_path = slot_root / '.evo-slot.json'
        if meta_path.is_file():
            prior = read_json(meta_path).get('job')
            prior_receipt = store.root / 'jobs' / f'j{prior}' / 'receipt.json'
            if prior_receipt.is_file():
                projection = read_json(prior_receipt).get('projection', {})
                desired_prefixes = {path.strip('/') for path in projection.get('managed_paths', [])
                                    if isinstance(path, str) and path and not Path(path).is_absolute() and '..' not in Path(path).parts}
    workspace = EnvironmentPool(work, store.root, project).acquire(job['workspace_slot'], job, desired, desired_prefixes)
    for entry in job['runtime'].get('files', []):
        source, target = inside(project, entry['source']), inside(workspace, entry['target'])
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            for item in job['plan']['source_inventory']['file:' + entry['source']]:
                source_file, target_file = source / Path(item['path']), target / Path(item['path'])
                target_file.parent.mkdir(parents=True, exist_ok=True)
                if not target_file.is_file() or file_digest(target_file) != item['sha256']:
                    shutil.copy2(source_file, target_file)
        else:
            expected = job['plan']['source_inventory']['file:' + entry['source']][0]['sha256']
            if not target.is_file() or file_digest(target) != expected:
                shutil.copy2(source, target)
    EnvironmentPool(work, store.root, project).record_baseline(workspace, job)
    return workspace


def _kill_owned(process: subprocess.Popen) -> None:
    if process.poll() is None:
        if os.name != 'nt':
            raise EvoError('Evo process termination requires Windows')
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20, check=False)
        process.wait(timeout=20)


def run_command(argv: list[str], workspace: Path, attempt: Path, timeout: int, cancel_check,
                *, stem: str = 'command', input_text: str | None = None) -> dict:
    validate_argv(argv)
    stdout, stderr = attempt / f'{stem}.stdout', attempt / f'{stem}.stderr'
    start = time.monotonic()
    attempt.mkdir(parents=True, exist_ok=True)
    # Pipe stdin only for bounded grader inputs; command runners otherwise cannot wait for user input.
    input_path = attempt / f'{stem}.stdin'
    if input_text is not None:
        input_path.write_text(input_text, encoding='utf-8')
    with stdout.open('wb') as out, stderr.open('wb') as err:
        with (input_path.open('rb') if input_text is not None else open(os.devnull, 'rb')) as inp:
            process = subprocess.Popen(argv, cwd=workspace, stdin=inp, stdout=out, stderr=err,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                while process.poll() is None:
                    if cancel_check():
                        raise EvoError('cancelled while running')
                    if time.monotonic() - start > timeout:
                        raise EvoError('process timed out')
                    if stdout.stat().st_size > 8 * 1024**2 or stderr.stat().st_size > 2 * 1024**2:
                        raise EvoError('process log budget exceeded')
                    time.sleep(.05)
            finally:
                _kill_owned(process)
    if process.returncode:
        raise EvoError(f'{stem} exited {process.returncode}; see {stderr.name}')
    if stdout.stat().st_size > 8 * 1024**2:
        raise EvoError('process output exceeded limit')
    try:
        value = json.loads(stdout.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError) as exc:
        raise EvoError(f'{stem} must output one JSON object') from exc
    if not isinstance(value, dict):
        raise EvoError(f'{stem} must output a JSON object')
    return {'value': value, 'duration_seconds': time.monotonic() - start, 'stdout': str(stdout), 'stderr': str(stderr)}


def _facts(study: dict, job: dict, receipt: dict, lifecycle: dict | None = None) -> list[dict]:
    fields = study['spec']['fields']
    dim = {k: job['plan'][k] for k in ('combination', 'item', 'replicate')}
    dim['job'] = f'j{job["id"]}'
    dim['study'] = f's{job["study"]}'
    dim['groups'] = job['plan']['groups']
    value = dict(receipt.get('values', {}))
    value['timing.subject_seconds'] = receipt['subject_seconds']
    value.update(lifecycle or {})
    raw = receipt.get('codex', {})
    usage = raw.get('usage', {})
    if job['runtime']['adapter'] == 'command':
        usage = {'total_tokens': 0, 'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}
    for name, count in usage.items():
        value['usage.' + name] = count
    request_count = raw.get('api_equivalent_cost', {}).get('request_count')
    if request_count is not None:
        value['usage.request_count'] = request_count
    trace_streams = (receipt.get('trace') or {}).get('observed', [])
    event_counts = Counter(event.get('kind') for stream in trace_streams for event in stream.get('events', []))
    for kind, count in event_counts.items():
        if kind:
            value[f'events.{kind}_count'] = count
    value['tools.attempts'] = event_counts.get('tool_call') if trace_streams else None
    rows = []
    declared = {f['id'] for f in fields if f['grain'] == 'attempt'}
    attempt_usage = {**usage, 'request_count': request_count}
    attempt_source = {'usage': attempt_usage, 'timing': {key.removeprefix('timing.'): item for key, item in
                      {'timing.subject_seconds': receipt['subject_seconds'], **(lifecycle or {})}.items()},
                      'events': {f'{key}_count': count for key, count in event_counts.items()},
                      'tools': {'attempts': event_counts.get('tool_call') if trace_streams else None},
                      'values': receipt.get('values', {})}
    selected = _extract_fields(fields, 'attempt', attempt_source, value)
    attempt_observation_fields = [field for field in fields if field['grain'] == 'attempt' and
                                  _observation_field(field)]
    trace_complete = (len(trace_streams) == len(raw.get('agent_usage', [])) and
                      all(stream.get('coverage', {}).get('complete_scan') is True for stream in trace_streams))
    receipt_location = job.get('receipt') or f'jobs/j{job["id"]}/receipt.json'
    attempt_source_record = {'kind': 'evo-receipt', 'location': receipt_location}
    if receipt.get('_usage_projected') is True:
        attempt_source_record = {
            'kind': 'evo-usage-projection', 'location': receipt_location,
            'inputs': [receipt_location, f'jobs/j{job["id"]}/codex-result.json'],
        }
    rows.append({'id': f'j{job["id"]}:attempt', 'grain': 'attempt', 'dimensions': dim, 'values': selected,
                 'source': attempt_source_record,
                 'completeness': 'complete' if all(v is not None for v in selected.values()) and
                 (not attempt_observation_fields or trace_complete) else 'partial'})
    agents = raw.get('agent_usage', [])
    aliases = {agent.get('thread_id'): f'a{number}' for number, agent in enumerate(agents, 1)}
    for number, agent in enumerate(agents, 1):
        pricing = agent.get('pricing_groups', [])
        models = sorted({group.get('model') for group in pricing if group.get('model')})
        actual_model = models[0] if len(models) == 1 else 'mixed' if len(models) > 1 else None
        agent_source = dict(agent.get('usage', {}))
        agent_source['request_count'] = agent.get('request_count')
        stream = trace_streams[number - 1] if number <= len(trace_streams) else None
        counts = Counter(event.get('kind') for event in stream.get('events', [])) if stream else Counter()
        for event_kind, count in counts.items():
            if event_kind:
                agent_source[f'events.{event_kind}_count'] = count
        agent_source['tools.attempts'] = counts.get('tool_call') if stream is not None else None
        structured_agent = {**agent, 'events': {f'{key}_count': count for key, count in counts.items()},
                            'tools': {'attempts': counts.get('tool_call') if stream is not None else None}}
        agent_values = _extract_fields(fields, 'agent', structured_agent, agent_source)
        agent_observation_fields = [field for field in fields if field['grain'] == 'agent' and _observation_field(field)]
        rows.append({'id': f'j{job["id"]}:agent{number}', 'grain': 'agent',
                     'dimensions': {**dim, 'agent': f'a{number}', 'model': actual_model,
                                    'models': models, 'role': agent.get('agent_role'),
                                    'parent_agent': aliases.get(agent.get('parent_thread_id')),
                                    'agent_path': agent.get('agent_path')},
                     'values': agent_values, 'source': {'kind': 'codex-usage', 'location': f'jobs/j{job["id"]}/codex-result.json#agent_usage/{number-1}'},
                     'completeness': 'complete' if agent.get('usage_complete') and all(v is not None for v in agent_values.values()) and
                     (not agent_observation_fields or bool(stream and stream.get('coverage', {}).get('complete_scan') is True)) else 'partial'})
        event_fields = [field for field in fields if field['grain'] == 'event']
        if event_fields and stream:
            for event_number, event in enumerate(stream.get('events', []), 1):
                event_values = _extract_fields(fields, 'event', event, event)
                rows.append({'id': f'j{job["id"]}:agent{number}:event{event_number}', 'grain': 'event',
                             'dimensions': {**dim, 'agent': f'a{number}', 'model': actual_model,
                                            'role': agent.get('agent_role'),
                                            'parent_agent': aliases.get(agent.get('parent_thread_id')),
                                            'event_kind': event.get('kind')},
                             'values': event_values,
                             'source': {'kind': 'codex-trace', 'location': f'jobs/j{job["id"]}/receipt.json#trace/observed/{number-1}/events/{event_number-1}'},
                             'completeness': 'complete' if stream.get('coverage', {}).get('complete_scan') is True and
                             all(item is not None for item in event_values.values()) else 'partial'})
    return rows


def _extract_fields(fields: list[dict], grain: str, source: dict, legacy: dict) -> dict:
    result = {}
    for field in fields:
        if field['grain'] != grain:
            continue
        extract = field.get('extract')
        if extract is None:
            key = field['id']
            result[key] = legacy.get(key)
            if result[key] is None and key.startswith('usage.'):
                result[key] = legacy.get(key.removeprefix('usage.'))
            continue
        if not isinstance(extract, dict) or extract.get('from') != grain:
            raise EvoError(f'field {field["id"]} has an invalid extract contract')
        raw_path = extract.get('path')
        parts = raw_path.split('.') if isinstance(raw_path, str) else raw_path if isinstance(raw_path, list) else []
        if not 1 <= len(parts) <= 16 or any(not isinstance(part, str) or not part or len(part) > 128 for part in parts):
            raise EvoError(f'field {field["id"]} extract path is invalid')
        value: Any = source
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        result[field['id']] = value
    return result


def _observation_field(field: dict) -> bool:
    extract = field.get('extract')
    path = extract.get('path') if isinstance(extract, dict) else field.get('id')
    head = path[0] if isinstance(path, list) and path else path.split('.', 1)[0] if isinstance(path, str) else None
    return head in ('events', 'tools')


def _complete_from_raw(store: Store, study: dict, job: dict, installed_codex_root: Path | None) -> bool:
    """Finish only post-model work from an immutable Codex owner receipt."""
    attempt = store.root / 'jobs' / f'j{job["id"]}'
    raw_path = attempt / 'codex-result.json'
    if not raw_path.is_file():
        return False
    if installed_codex_root is not None or (attempt / 'codex-runtime-home.json').is_file():
        from .codex_adapter import recover_codex_artifacts
        recovered = recover_codex_artifacts(project_root=Path(study['project']), attempt_root=attempt,
                                             installed_codex_root=installed_codex_root)
        raw = recovered['raw_receipt']
        recovered_trace = recovered['trace']
    else:
        raw = read_json(raw_path)
        recovered_trace = None
    if (raw.get('schema') == 'agentbase.evo-codex-run/v1'
            and raw.get('status') == 'precondition_failed'
            and raw.get('model_invoked') is False
            and raw.get('process_started') is True
            and raw.get('root_thread_id') in (None, '')
            and raw.get('thread_started_count', 0) == 0
            and raw.get('event_count', 0) == 0
            and raw.get('exit_code') not in (None, 0)):
        diagnostic = str(raw.get('diagnostic') or 'Codex process rejected configuration before opening a session')[:500]
        store.reconcile_not_invoked(job['study'], job['id'],
                                    f'adapter raw receipt proves no session/model request: {diagnostic}')
        intent = attempt / 'intent.json'
        if intent.is_file():
            workspace = Path(read_json(intent)['workspace']).resolve()
            work = Path(study['work']).resolve()
            if workspace.is_relative_to(work) and (workspace / '.evo-slot.json').is_file():
                from .env_pool import EnvironmentPool
                EnvironmentPool(work, store.root).release(workspace)
        if job['runtime'].get('swe') is not None:
            from .swe_adapter import cleanup_job as cleanup_swe_job
            cleanup_swe_job(job['runtime'], attempt, project_root=Path(study['project']), evo_state_root=store.root)
        return True
    if raw.get('schema') != 'agentbase.evo-codex-run/v1' or raw.get('model_invoked') is not True:
        store.finish(job['id'], 'uncertain', usage=raw.get('usage', {}).get('total_tokens'),
                     usage_complete=bool(raw.get('usage_complete')),
                     error='Raw Codex receipt is incomplete; recovery will not repeat the model call')
        return True
    if raw.get('status') != 'completed':
        store.finish(job['id'], 'uncertain', usage=raw.get('usage', {}).get('total_tokens'),
                     usage_complete=bool(raw.get('usage_complete')),
                     error=f'Raw Codex receipt status is {raw.get("status", "unknown")}; recovery will not repeat it')
        return True
    cache_invalid_path = attempt / 'skill-cache-invalid.json'
    if cache_invalid_path.is_file():
        invalid = read_json(cache_invalid_path)
        if invalid.get('schema') != 'agentbase-evo-skill-cache-invalid/v1' or invalid.get('model_invoked') is not True:
            raise EvoError('post-model skill cache invalidation record is malformed')
        store.finish(job['id'], 'uncertain', usage=raw.get('usage', {}).get('total_tokens'),
                     usage_complete=bool(raw.get('usage_complete')),
                     error=f"Post-model skill input was invalid: {str(invalid.get('error', 'unknown'))[:600]}")
        return True
    if job['runtime'].get('swe') is not None:
        from .swe_adapter import finalize_job
        intent = read_json(attempt / 'intent.json')
        swe_result = finalize_job(
            project_root=Path(study['project']), runtime=job['runtime'], study_id=job['study'], job_id=job['id'],
            attempt_root=attempt, environment=os.environ, raw_receipt=raw,
        )
        receipt = {
            'schema': 'agentbase-evo-run/v1', 'execution_identity': job['identity'],
            'attempt': job.get('attempt_seq', 1), 'job': job['id'], 'study': job['study'],
            'codex': raw, 'swe': swe_result, 'subject_seconds': raw.get('duration_seconds', 0),
            'values': swe_result['values'], 'usage': raw.get('usage', {}).get('total_tokens'),
            'usage_complete': bool(raw.get('usage_complete')), 'projection': intent.get('projection'),
        }
        receipt['trace'] = recovered_trace if recovered_trace is not None else {
            'schema': 'agentbase.evo-codex-trace/v1', 'capability': 'unavailable', 'observed': [],
            'missing': ['recover requires installed Codex root to rebuild trace'], 'private_reasoning_archived': False,
        }
        receipt['awaiting_human'] = bool(job['runtime'].get('rubric'))
        receipt['facts'] = _facts(study, job, receipt)
        immutable_json(attempt / 'receipt.json', receipt)
        settle(store, job, receipt)
        return True
    if job['runtime'].get('code_reading') is not None:
        from .code_reading_adapter import grade_attempt
        item = next(item for item in study['spec']['evaluations']['items'] if item['id'] == job['plan']['item'])
        graded = grade_attempt(item, job['runtime']['code_reading'], attempt / 'codex-logs' / 'last-message.txt')
        receipt = {
            'schema': 'agentbase-evo-run/v1', 'execution_identity': job['identity'],
            'attempt': job.get('attempt_seq', 1), 'job': job['id'], 'study': job['study'],
            'codex': raw, 'code_reading': graded['score'], 'subject_seconds': raw.get('duration_seconds', 0),
            'values': graded['values'], 'usage': raw.get('usage', {}).get('total_tokens'),
            'usage_complete': bool(raw.get('usage_complete')),
        }
        receipt['trace'] = recovered_trace if recovered_trace is not None else {
            'schema': 'agentbase.evo-codex-trace/v1', 'capability': 'unavailable', 'observed': [],
            'missing': ['recover requires installed Codex root to rebuild trace'], 'private_reasoning_archived': False,
        }
        receipt['awaiting_human'] = bool(job['runtime'].get('rubric'))
        receipt['facts'] = _facts(study, job, receipt)
        immutable_json(attempt / 'receipt.json', receipt)
        settle(store, job, receipt)
        return True
    receipt: dict[str, Any] = {
        'schema': 'agentbase-evo-run/v1', 'execution_identity': job['identity'],
        'job': job['id'], 'study': job['study'], 'codex': raw,
        'subject_seconds': raw.get('duration_seconds', 0), 'values': {},
        'usage': raw.get('usage', {}).get('total_tokens'),
        'usage_complete': bool(raw.get('usage_complete')),
    }
    if recovered_trace is not None:
        receipt['trace'] = recovered_trace
    else:
        receipt['trace'] = {'schema': 'agentbase.evo-codex-trace/v1', 'capability': 'unavailable',
                            'observed': [], 'missing': ['recover requires installed Codex root to rebuild trace'],
                            'private_reasoning_archived': False}
    runtime = job['runtime']
    cancelled = lambda: store.study(job['study'])['state'] == 'cancelled'
    store.phase(job['id'], 'verifying')
    verifier = runtime.get('verifier')
    if verifier:
        argv = [a.replace('{answer}', str(attempt / 'codex-logs' / 'last-message.txt'))
                .replace('{workspace}', str(Path(json.loads((attempt / 'intent.json').read_text(encoding='utf-8'))['workspace'])))
                for a in validate_argv(verifier['argv'])]
        receipt['values'] = run_command(argv, attempt, attempt, runtime['timeout_seconds'], cancelled, stem='verifier')['value']
    elif runtime.get('answer_contains'):
        answer = (attempt / 'codex-logs' / 'last-message.txt').read_text(encoding='utf-8')
        receipt['values'] = {'quality.reward': int(all(s in answer for s in runtime['answer_contains']))}
    receipt['awaiting_human'] = bool(runtime.get('rubric'))
    receipt['facts'] = _facts(study, job, receipt)
    immutable_json(attempt / 'receipt.json', receipt)
    settle(store, job, receipt)
    return True


def _raw_matches_subject(receipt: dict, intent: dict, job: dict, raw: dict) -> bool:
    """Bind a mutable usage owner to the immutable subject snapshot that created it."""
    receipt_raw = receipt.get('codex')
    if (not isinstance(receipt_raw, dict)
            or receipt.get('job') != job['id'] or receipt.get('study') != job['study']
            or receipt.get('execution_identity') != job['identity']
            or intent.get('execution_identity') != job['identity']):
        return False
    root_thread_id = raw.get('root_thread_id')
    if (not isinstance(root_thread_id, str) or not root_thread_id
            or receipt_raw.get('root_thread_id') != root_thread_id):
        return False
    receipt_cli = receipt_raw.get('codex')
    raw_cli = raw.get('codex')
    if isinstance(receipt_cli, dict) and isinstance(raw_cli, dict):
        for field in ('path', 'version', 'sha256'):
            if field in receipt_cli or field in raw_cli:
                if receipt_cli.get(field) != raw_cli.get(field):
                    return False
    return True


def _usage_projection_from_raw(store: Store, study: dict, job: dict,
                               installed_codex_root: Path | None) -> dict | None:
    """Read refreshed usage from its raw owner without replacing the final subject receipt."""
    if job['state'] not in ('completed', 'awaiting_human') or job['usage_complete']:
        return None
    attempt = store.root / 'jobs' / f'j{job["id"]}'
    receipt_path = attempt / 'receipt.json'
    raw_path = attempt / 'codex-result.json'
    intent_path = attempt / 'intent.json'
    if not receipt_path.is_file() or not raw_path.is_file() or not intent_path.is_file():
        return None
    receipt = read_json(receipt_path)
    intent = read_json(intent_path)
    if (receipt.get('schema') != 'agentbase-evo-run/v1'
            or receipt.get('job') != job['id'] or receipt.get('study') != job['study']
            or receipt.get('execution_identity') != job['identity']
            or intent.get('execution_identity') != job['identity']):
        raise EvoError('settled usage recovery binding does not match its immutable subject receipt')
    persisted_raw = read_json(raw_path)
    if not _raw_matches_subject(receipt, intent, job, persisted_raw):
        raise EvoError('raw Codex usage owner does not match its immutable subject receipt')
    from .codex_adapter import recover_codex_artifacts
    recovered = recover_codex_artifacts(
        project_root=Path(study['project']), attempt_root=attempt,
        installed_codex_root=installed_codex_root,
    )
    raw = recovered['raw_receipt']
    usage = raw.get('usage', {})
    if (not _raw_matches_subject(receipt, intent, job, raw)
            or raw.get('schema') != 'agentbase.evo-codex-run/v1'
            or raw.get('status') != 'completed' or raw.get('model_invoked') is not True
            or raw.get('usage_complete') is not True
            or type(usage.get('total_tokens')) is not int or usage['total_tokens'] < 0):
        return None
    return {'raw': raw, 'trace': recovered['trace'], 'receipt': receipt}


def _project_current_usage(store: Store, job: dict, receipt: dict) -> dict:
    """Project a complete, same-subject raw usage owner into facts at read time."""
    if job['runtime']['adapter'] != 'codex':
        return receipt
    attempt = store.root / 'jobs' / f'j{job["id"]}'
    raw_path = attempt / 'codex-result.json'
    intent_path = attempt / 'intent.json'
    if not raw_path.is_file() or not intent_path.is_file():
        return receipt
    raw = read_json(raw_path)
    intent = read_json(intent_path)
    if (not _raw_matches_subject(receipt, intent, job, raw)
            or raw.get('schema') != 'agentbase.evo-codex-run/v1'
            or raw.get('status') != 'completed' or raw.get('model_invoked') is not True
            or raw.get('usage_complete') is not True):
        return receipt
    projected = copy.deepcopy(receipt)
    projected['codex'] = raw
    projected['usage'] = raw.get('usage', {}).get('total_tokens')
    projected['usage_complete'] = True
    projected['_usage_projected'] = True
    return projected


def execute(store: Store, job: dict, installed_codex_root: Path | None) -> None:
    study = store.study(job['study'])
    attempt = store.root / 'jobs' / f'j{job["id"]}'
    receipt_path = attempt / 'receipt.json'
    invoked = False
    try:
        check_roots(Path(study['project']), store.root, Path(study['work']), installed_codex_root)
        roots = candidate_roots(store, job['runtime'], Path(study['project']), Path(study['work']), installed_codex_root)
        if receipt_path.exists():
            settle(store, job, read_json(receipt_path))
            return
        if job['runtime']['adapter'] == 'codex' and _complete_from_raw(store, study, job, installed_codex_root):
            return
        attempt.mkdir(parents=True, exist_ok=True)
        runtime = job['runtime']
        cancelled = lambda: store.study(job['study'])['state'] == 'cancelled'
        if cancelled():
            raise EvoError('cancelled before subject preparation')
        if runtime.get('swe') is not None:
            if installed_codex_root is None:
                raise EvoError('Codex run requires --installed-codex-root')
            from .swe_adapter import validate_runtime as validate_swe_runtime
            current_swe = validate_swe_runtime(
                runtime, project_root=Path(study['project']), evo_state_root=store.root,
                evo_work_root=Path(study['work']), installed_codex_root=installed_codex_root,
            )
            if current_swe != runtime['swe']:
                raise EvoError('frozen SWE binding changed since submit')
            if execution_sources(study['spec'], job['plan'], Path(study['project']), roots) != job['plan']['source_inventory']:
                raise EvoError('selected source changed since submit; create a new frozen study')
            from .swe_adapter import prepare_job as prepare_swe_job
            config = store.config()
            active_reservations = sum(j['disk_reservation'] for j in store.jobs() if j['state'] in RESOURCE_HELD)
            if disk_bytes(*managed_storage_roots(store), allowed_links=managed_skill_links(store)) + active_reservations > config['max_disk_mb'] * 1024**2:
                raise RetryLater('managed disk budget is waiting for SWE workspace capacity')
            if shutil.disk_usage(Path(runtime['swe']['work_root']).anchor).free - job['disk_reservation'] < config['min_free_mb'] * 1024**2:
                raise RetryLater('minimum free disk reserve is waiting for SWE workspace capacity')
            swe_state = prepare_swe_job(
                project_root=Path(study['project']), runtime=runtime, study_id=job['study'], job_id=job['id'],
                attempt_root=attempt, environment=os.environ,
            )
            workspace = Path(swe_state['workspace'])
        else:
            workspace = prepare_workspace(store, study, job)
            if runtime.get('code_reading') is not None:
                from .code_reading_adapter import validate_binding as validate_code_reading, validate_roots as validate_code_reading_roots
                if validate_code_reading(runtime) != runtime['code_reading']:
                    raise EvoError('frozen code-reading snapshot changed since submit')
                validate_code_reading_roots(runtime['code_reading'], state_root=store.root,
                                            work_root=Path(study['work']), installed_codex_root=installed_codex_root)
        store.phase(job['id'], 'running')
        if cancelled():
            raise EvoError('cancelled before subject launch')
        immutable_json(attempt / 'intent.json', {'execution_identity': job['identity'], 'attempt': job.get('attempt_seq', 1),
                                                 'workspace': str(workspace), 'runtime': runtime})
        receipt: dict[str, Any] = {'schema': 'agentbase-evo-run/v1', 'execution_identity': job['identity'],
                                   'attempt': job.get('attempt_seq', 1), 'job': job['id'], 'study': job['study']}
        if runtime['adapter'] == 'command':
            invoked = True
            argv = [arg.replace('{workspace}', str(workspace)) for arg in runtime['argv']]
            result = run_command(argv, workspace, attempt, runtime['timeout_seconds'], cancelled)
            receipt.update(values=result['value'], subject_seconds=result['duration_seconds'], usage=0, usage_complete=True)
        else:
            if installed_codex_root is None:
                raise EvoError('Codex run requires --installed-codex-root')
            from .codex_adapter import run_codex_job
            try:
                codex_plan = job['plan']
                codex_spec = study['spec']
                task_options = {}
                if runtime.get('swe') is not None:
                    codex_spec, codex_plan = _swe_codex_inputs(study, job, swe_state)
                    task_options['task_runtime_bin'] = Path(swe_state['task_runtime']['bin_directory'])
                elif runtime.get('code_reading') is not None:
                    from .code_reading_adapter import subject_prompt
                    codex_spec = copy.deepcopy(study['spec'])
                    item = next(item for item in codex_spec['evaluations']['items'] if item['id'] == job['plan']['item'])
                    # The Codex adapter gives an item prompt precedence over a runtime prompt.
                    item['prompt'] = subject_prompt(item, runtime['code_reading'])
                result = run_codex_job(project_root=Path(study['project']), workspace=workspace, attempt_root=attempt,
                                       installed_codex_root=installed_codex_root, spec=codex_spec, job=codex_plan,
                                       process_environment=os.environ, timeout_seconds=runtime['timeout_seconds'],
                                       cancel_check=cancelled, skill_cache_root=store.root / 'skill-cache', **task_options)
            except Exception as exc:
                marker = getattr(exc, 'model_invoked', None)
                invoked = False if marker is False else (attempt / 'codex-rollout-before.json').exists()
                raise
            raw = result.get('raw_receipt', result)
            invoked = bool(result.get('model_invoked'))
            if isinstance(raw, str):
                raw = read_json(Path(raw))
            if result.get('status') != 'completed':
                state = ('uncertain' if runtime.get('swe') is not None and invoked else
                         result.get('status') if result.get('status') in ('failed', 'cancelled', 'uncertain') else 'uncertain')
                store.finish(job['id'], state, usage=raw.get('usage', {}).get('total_tokens') if isinstance(raw, dict) else None,
                             usage_complete=bool(isinstance(raw, dict) and raw.get('usage_complete')),
                             error=f'Codex adapter ended as {result.get("status", "unknown")}')
                if runtime.get('swe') is not None:
                    if not invoked:
                        from .swe_adapter import cleanup_job as cleanup_swe_job
                        cleanup_swe_job(runtime, attempt, project_root=Path(study['project']), evo_state_root=store.root)
                elif state == 'uncertain':
                    from .env_pool import EnvironmentPool
                    EnvironmentPool(Path(study['work']), store.root).quarantine(workspace, 'Codex outcome is uncertain')
                else:
                    from .env_pool import EnvironmentPool
                    EnvironmentPool(Path(study['work']), store.root).release(workspace)
                return
            receipt.update(codex=raw, trace=result.get('trace'), projection=result.get('projection'), subject_seconds=raw.get('duration_seconds', 0),
                           values={}, usage=raw.get('usage', {}).get('total_tokens'), usage_complete=raw.get('usage_complete', False))
            store.phase(job['id'], 'verifying')
            if runtime.get('swe') is not None:
                from .swe_adapter import finalize_job as finalize_swe_job
                swe_result = finalize_swe_job(
                    project_root=Path(study['project']), runtime=runtime, study_id=job['study'], job_id=job['id'],
                    attempt_root=attempt, environment=os.environ, raw_receipt=raw,
                )
                receipt['swe'] = swe_result
                receipt['values'] = swe_result['values']
            elif runtime.get('code_reading') is not None:
                from .code_reading_adapter import grade_attempt
                item = next(item for item in study['spec']['evaluations']['items'] if item['id'] == job['plan']['item'])
                graded = grade_attempt(item, runtime['code_reading'], attempt / 'codex-logs' / 'last-message.txt')
                receipt['code_reading'] = graded['score']
                receipt['values'] = graded['values']
            elif (verifier := runtime.get('verifier')):
                argv = validate_argv(verifier['argv'])
                answer = attempt / 'codex-logs' / 'last-message.txt'
                argv = [a.replace('{answer}', str(answer)).replace('{workspace}', str(workspace)) for a in argv]
                verified = run_command(argv, attempt, attempt, runtime['timeout_seconds'], cancelled, stem='verifier')
                receipt['values'] = verified['value']
            elif runtime.get('answer_contains'):
                answer = (attempt / 'codex-logs' / 'last-message.txt').read_text(encoding='utf-8')
                receipt['values'] = {'quality.reward': int(all(s in answer for s in runtime['answer_contains']))}
        receipt['awaiting_human'] = bool(runtime.get('rubric'))
        receipt['facts'] = _facts(study, job, receipt)
        immutable_json(receipt_path, receipt)
        settle(store, job, receipt)
    except RetryLater as exc:
        store.defer(job['id'], str(exc))
        return
    except (Exception,) as exc:
        if job['runtime']['adapter'] == 'codex':
            invoked = _persisted_model_invoked(attempt, invoked)
        failure_usage = None
        failure_usage_complete = False
        if invoked and job['runtime']['adapter'] == 'codex':
            try:
                persisted_raw = read_json(attempt / 'codex-result.json')
                failure_usage = persisted_raw.get('usage', {}).get('total_tokens')
                failure_usage_complete = bool(persisted_raw.get('usage_complete'))
            except Exception:
                pass
        # A started model with unknown outcome is never automatically resubmitted.
        state = 'uncertain' if invoked and job['runtime']['adapter'] == 'codex' else 'failed'
        if store.study(job['study'])['state'] == 'cancelled' and not (
            job['runtime'].get('swe') is not None and invoked
        ):
            state = 'cancelled'
        store.finish(job['id'], state,
                     usage_complete=(failure_usage_complete if invoked and job['runtime']['adapter'] == 'codex'
                                     else not invoked or job['runtime']['adapter'] == 'command'),
                     usage=(failure_usage if invoked and job['runtime']['adapter'] == 'codex'
                            else 0 if not invoked or job['runtime']['adapter'] == 'command' else None),
                     error=str(exc)[:800])
        if 'workspace' in locals():
            if job['runtime'].get('swe') is not None:
                if not invoked:
                    from .swe_adapter import cleanup_job as cleanup_swe_job
                    cleanup_swe_job(job['runtime'], attempt, project_root=Path(study['project']), evo_state_root=store.root)
            else:
                from .env_pool import EnvironmentPool
                pool = EnvironmentPool(Path(study['work']), store.root)
                if state == 'uncertain':
                    pool.quarantine(workspace, str(exc))
                else:
                    pool.release(workspace)


def settle(store: Store, job: dict, receipt: dict) -> None:
    if receipt.get('execution_identity') != job['identity'] or receipt.get('job') != job['id']:
        raise EvoError('receipt identity does not match the persisted attempt')
    if receipt.get('attempt', job.get('attempt_seq', 1)) != job.get('attempt_seq', 1):
        raise EvoError('receipt attempt does not match the persisted attempt')
    if job['runtime'].get('swe') is not None:
        from .swe_adapter import cleanup_job as cleanup_swe_job
        cleanup_swe_job(job['runtime'], store.root / 'jobs' / f'j{job["id"]}',
                        project_root=Path(store.study(job['study'])['project']), evo_state_root=store.root)
    store.finish(job['id'], 'awaiting_human' if receipt.get('awaiting_human') else 'completed',
                 receipt=f'jobs/j{job["id"]}/receipt.json', usage=receipt.get('usage'),
                 usage_complete=bool(receipt.get('usage_complete')))


def run(store: Store, *, study: int | None = None, installed_codex_root: Path | None = None) -> dict:
    if os.name != 'nt':
        raise EvoError('Evo runs on Windows only')
    if os.environ.get('AGENTBASE_AGENT_EVALUATOR_DISABLED') == '1':
        selected = store.jobs(study)
        if any(j['runtime']['adapter'] == 'codex' and j['state'] == 'queued' for j in selected):
            raise EvoError('model evaluator is disabled')
    config = store.config()
    with CaseLock(store.root, 'evo-scheduler'):
        with ThreadPoolExecutor(max_workers=config['concurrency']) as pool:
            pending = set()
            deferred: set[int] = set()
            while True:
                job = store.claim(study, deferred)
                if job:
                    future = pool.submit(execute, store, job, installed_codex_root)
                    future.job_id = job['id']
                    pending.add(future)
                    continue
                if not pending:
                    break
                finished, pending = wait(pending, timeout=.2, return_when=FIRST_COMPLETED)
                for future in finished:
                    future.result()
                    current = next(j for j in store.jobs() if j['id'] == future.job_id)
                    if current['state'] == 'queued' and current['reason']:
                        deferred.add(current['id'])
    return store.status(study)


def recover(store: Store, study: int, installed_codex_root: Path | None = None, *,
            confirm_not_invoked: int | None = None, evidence: str | None = None,
            retry_not_invoked: int | None = None, confirm_stopped: int | None = None) -> dict:
    with CaseLock(store.root, 'evo-scheduler'):
        if confirm_stopped is not None:
            prior = store.reconcile_stopped(study, confirm_stopped, evidence or '')
            work = Path(store.study(study)['work']).resolve()
            if prior['workspace_slot']:
                workspace = work / f'slot-{prior["workspace_slot"]:04d}'
                if (workspace / '.evo-slot.json').is_file():
                    from .env_pool import EnvironmentPool
                    EnvironmentPool(work, store.root).release(workspace)
        if confirm_not_invoked is not None:
            raw = store.root / 'jobs' / f'j{confirm_not_invoked}' / 'codex-result.json'
            if raw.exists():
                raise EvoError('raw Codex receipt exists; use normal recovery instead of confirming no invocation')
            prior = next((job for job in store.jobs(study) if job['id'] == confirm_not_invoked), None)
            store.reconcile_not_invoked(study, confirm_not_invoked, evidence or '')
            intent = store.root / 'jobs' / f'j{confirm_not_invoked}' / 'intent.json'
            work = Path(store.study(study)['work']).resolve()
            workspace = (Path(read_json(intent)['workspace']).resolve() if intent.is_file()
                         else work / f'slot-{prior["workspace_slot"]:04d}' if prior and prior['workspace_slot'] else None)
            if workspace is not None and workspace.is_relative_to(work) and (workspace / '.evo-slot.json').is_file():
                from .env_pool import EnvironmentPool
                EnvironmentPool(work, store.root).release(workspace)
        if retry_not_invoked is not None:
            store.require_retryable_not_invoked(study, retry_not_invoked)
            prior = next(job for job in store.jobs(study) if job['id'] == retry_not_invoked)
            if prior.get('workspace_slot'):
                work = Path(store.study(study)['work']).resolve()
                workspace = work / f'slot-{prior["workspace_slot"]:04d}'
                if (workspace / '.evo-slot.json').is_file():
                    from .env_pool import EnvironmentPool
                    EnvironmentPool(work, store.root, Path(store.study(study)['project'])).restore_projection_owner(
                        workspace)
            refreshed = dict(prior['plan'])
            refreshed['execution_recipe'] = execution_recipe(
                prior['runtime']['adapter'], Path(store.study(study)['project']),
                swe=prior['runtime'].get('swe') is not None,
                code_reading=prior['runtime'].get('code_reading') is not None)
            item = next(item for item in store.study(study)['spec']['evaluations']['items'] if item['id'] == refreshed['item'])
            refreshed['execution_identity'] = job_identity(store.study(study)['spec'], refreshed, item)
            attempt_root = store.root / 'jobs' / f'j{retry_not_invoked}'
            archive = attempt_root / 'attempts' / f'a{prior.get("attempt_seq", 1)}'
            archive.mkdir(parents=True, exist_ok=True)
            for path in list(attempt_root.iterdir()):
                if path.name == 'attempts':
                    continue
                target = archive / path.name
                if target.exists():
                    raise EvoError(f'prior attempt archive conflicts at {path.name}; inspect before retrying')
                path.replace(target)
            store.retry_not_invoked(study, retry_not_invoked, evidence or '',
                                    identity=refreshed['execution_identity'], plan=refreshed)
        for job in store.jobs(study):
            raw_path = store.root / 'jobs' / f'j{job["id"]}' / 'codex-result.json'
            if (job['runtime']['adapter'] == 'codex'
                    and job['state'] in ('completed', 'awaiting_human')
                    and not job['usage_complete']):
                projection = _usage_projection_from_raw(
                    store, store.study(study), job, installed_codex_root)
                if projection is not None:
                    usage = projection['raw']['usage']['total_tokens']
                    store.finish(
                        job['id'], job['state'], receipt=job['receipt'], usage=usage,
                        usage_complete=True, error=job.get('error'))
                continue
            failed_precondition_candidate = False
            if job['state'] == 'failed' and job['runtime']['adapter'] == 'codex' and raw_path.is_file():
                raw_candidate = read_json(raw_path)
                failed_precondition_candidate = (
                    raw_candidate.get('root_thread_id') in (None, '')
                    and raw_candidate.get('thread_started_count', 0) == 0
                    and raw_candidate.get('event_count', 0) == 0
                    and raw_candidate.get('exit_code') not in (None, 0))
            if job['state'] not in (*ACTIVE, 'uncertain') and not failed_precondition_candidate:
                continue
            receipt_path = store.root / 'jobs' / f'j{job["id"]}' / 'receipt.json'
            if receipt_path.is_file():
                settle(store, job, read_json(receipt_path))
            elif job['runtime']['adapter'] == 'codex':
                try:
                    if not _complete_from_raw(store, store.study(study), job, installed_codex_root):
                        store.finish(job['id'], 'uncertain', error='No final receipt; inspect owned process and raw artifacts. Recovery does not launch a model.')
                except Exception as exc:
                    usage = None
                    usage_complete = False
                    try:
                        persisted_raw = read_json(raw_path)
                        if persisted_raw.get('model_invoked') is True:
                            usage = persisted_raw.get('usage', {}).get('total_tokens')
                            usage_complete = bool(persisted_raw.get('usage_complete'))
                    except Exception:
                        pass
                    store.finish(job['id'], 'uncertain', usage=usage, usage_complete=usage_complete,
                                 error=f'Post-model recovery failed without rerunning the model: {str(exc)[:700]}')
            else:
                store.finish(job['id'], 'uncertain', error='No final receipt; inspect owned process and raw artifacts. Recovery does not launch a model.')
    return store.status(study)


def validate_analysis_spec(frozen: dict, analysis: dict) -> None:
    def execution_contract(value: dict) -> dict:
        projected = copy.deepcopy(value)
        projected.pop('id', None)
        projected.pop('version', None)
        projected.pop('fields', None)
        projected.pop('scoring', None)
        projected.get('evaluations', {}).pop('groups', None)
        projected.get('selection', {}).pop('groups', None)
        return projected
    if execution_contract(frozen) != execution_contract(analysis):
        raise EvoError('analysis spec changes an execution input, protocol, observation, component, runtime or replicate')


def artifacts(store: Store, study: int, projection_spec: dict | None = None) -> dict:
    frozen = store.study(study)['spec']
    selected_spec = projection_spec or frozen
    if projection_spec is not None:
        validate_analysis_spec(frozen, projection_spec)
    selected_groups = set(selected_spec.get('selection', {}).get('groups', [
        group['id'] for group in selected_spec['evaluations']['groups'] if group.get('active', False)]))
    group_membership = {item['id']: [group['id'] for group in selected_spec['evaluations']['groups']
                                     if group['id'] in selected_groups and item['id'] in group['items']]
                        for item in selected_spec['evaluations']['items']}
    rows = []
    for job in store.jobs(study):
        projected_job = {**job, 'plan': {**job['plan'], 'groups': group_membership.get(job['plan']['item'], [])}}
        if job['receipt']:
            receipt = read_json(inside(store.root, job['receipt']))
            receipt = _project_current_usage(store, job, receipt)
            derived_trace = store.root / 'jobs' / f'j{job["id"]}' / 'codex-trace.json'
            if derived_trace.is_file():
                receipt = {**receipt, 'trace': read_json(derived_trace)}
            rows.extend(_facts({'spec': selected_spec}, projected_job, receipt, store.lifecycle(job['id'])))
        elif job['state'] in ('failed', 'uncertain', 'cancelled'):
            values = {f['id']: None for f in selected_spec['fields'] if f['grain'] == 'attempt'}
            rows.append({'id': f'j{job["id"]}:attempt', 'grain': 'attempt',
                         'dimensions': {**{k: job['plan'][k] for k in ('combination','item','replicate')},
                                        'groups': group_membership.get(job['plan']['item'], [])}, 'values': values,
                         'source': {'kind':'evo-state','location':f'evo.sqlite3#job={job["id"]}'}, 'completeness':'missing'})
    return {'schema': ARTIFACT_SCHEMA, 'projection': 'agentbase-evo-facts/v2',
            'id': f's{study}', 'version': fingerprint(rows),
            'analysis_spec': {'id': selected_spec['id'], 'version': selected_spec['version']},
            'execution_source': {'study': f's{study}', 'frozen_spec': {'id': frozen['id'], 'version': frozen['version']}},
            'rows': rows}


def trace(store: Store, study: int, *, job: int | None = None, source: str = 'schedule',
          agent: str | None = None, kind: str | None = None, offset: int = 0, limit: int = 50,
          snapshot: str | None = None, refresh: bool = False,
          installed_codex_root: Path | None = None) -> dict:
    """Read one bounded, immutable scheduling or native-action projection."""
    positive(limit, 'trace limit', 500)
    if type(offset) is not int or offset < 0:
        raise EvoError('offset must be nonnegative')
    if source == 'schedule':
        summary = store.trace_summary(study, job, kind)
        current_snapshot = fingerprint({'study': study, 'job': job, 'kind': kind, 'summary': summary})
        if offset and snapshot is None:
            raise EvoError('trace pagination requires --snapshot from the previous page')
        if snapshot is not None and not _snapshot_matches(snapshot, current_snapshot):
            raise EvoError('trace source changed; restart at offset 0')
        selected = store.trace(study, job, offset, limit, kind)
        return {'schema': 'agentbase-evo-trace/v1', 'study': f's{study}', 'source': source,
                'snapshot': current_snapshot, 'summary': summary,
                'events': selected, 'page': {'offset': offset, 'returned': len(selected), 'total': summary['total'],
                'next_offset': offset + len(selected) if offset + len(selected) < summary['total'] else None}}
    if source != 'native':
        raise EvoError('trace source must be schedule or native')
    if refresh and installed_codex_root is None:
        raise EvoError('native trace --refresh requires --installed-codex-root')
    if refresh and offset:
        raise EvoError('refresh starts a new trace snapshot at offset 0')
    jobs = [value for value in store.jobs(study) if job is None or value['id'] == job]
    events, coverage, snapshots = [], [], []
    for value in jobs:
        if not value['receipt']:
            continue
        receipt_path = inside(store.root, value['receipt'])
        receipt = read_json(receipt_path)
        derived_path = store.root / 'jobs' / f'j{value["id"]}' / 'codex-trace.json'
        if refresh:
            from .codex_adapter import refresh_codex_trace
            refreshed = refresh_codex_trace(project_root=Path(store.study(study)['project']),
                                             attempt_root=derived_path.parent,
                                             installed_codex_root=installed_codex_root)
            trace_value = refreshed['trace']
        elif derived_path.is_file():
            trace_value = read_json(derived_path)
        else:
            trace_value = receipt.get('trace') or {}
        source_path = derived_path if derived_path.is_file() else receipt_path
        before = {'bytes': source_path.stat().st_size, 'modified_ns': source_path.stat().st_mtime_ns}
        observed = trace_value.get('observed', [])
        for number, stream in enumerate(observed, 1):
            alias = f'a{number}'
            identity = stream.get('identity', {})
            if agent and agent not in (alias, identity.get('agent_path'), identity.get('role')):
                continue
            coverage.append({'job': f'j{value["id"]}', 'agent': alias, **stream.get('coverage', {})})
            for event in stream.get('events', []):
                if kind and event.get('kind') != kind:
                    continue
                events.append({'job': f'j{value["id"]}', 'agent': alias,
                               'role': identity.get('role'), **event})
        after = {'bytes': source_path.stat().st_size, 'modified_ns': source_path.stat().st_mtime_ns}
        if before != after:
            raise EvoError('trace receipt changed during pagination; restart from offset 0')
        snapshots.append({'job': f'j{value["id"]}', **before})
    events.sort(key=lambda event: (event.get('time') or '', event['job'], event['agent'], event.get('line', 0)))
    current_snapshot = fingerprint(snapshots)
    if offset and snapshot is None:
        raise EvoError('trace pagination requires --snapshot from the previous page')
    if snapshot is not None and not _snapshot_matches(snapshot, current_snapshot):
        raise EvoError('trace source changed; restart at offset 0')
    selected = events[offset:offset + limit]
    return {'schema': 'agentbase-evo-trace/v1', 'study': f's{study}', 'source': source,
            'snapshot': current_snapshot, 'coverage': coverage,
            'summary': {'event_counts': dict(Counter(event['kind'] for event in events))},
            'events': selected, 'page': {'offset': offset, 'returned': len(selected), 'total': len(events),
            'next_offset': offset + len(selected) if offset + len(selected) < len(events) else None}}


def _snapshot_matches(provided: str, current: str) -> bool:
    if provided == current:
        return True
    return provided.startswith('snapshot-') and len(provided) == 17 and current.startswith(provided.removeprefix('snapshot-'))
