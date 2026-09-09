"""Frozen, task-only code-reading catalogs backed by prepared source snapshots."""
from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any

from .spec import EvoError, read_json


SOURCE_SCHEMA = 'agentbase.code-reading-source/v1'
CATALOG_SCHEMA = 'agentbase-evo-code-reading-catalog/v1'
MAX_SNAPSHOT_FILES = 200_000
MAX_SNAPSHOT_BYTES = 8 * 1024**3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def snapshot_inventory(root: Path) -> dict[str, Any]:
    if root.is_symlink() or root.is_junction():
        raise EvoError(f'snapshot workspace must not be a link: {root.absolute()}')
    resolved = root.resolve()
    if not resolved.is_dir() or resolved.is_symlink() or resolved.is_junction():
        raise EvoError(f'snapshot workspace must be a regular directory: {resolved}')
    entries, total = [], 0
    for path in sorted(resolved.rglob('*'), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink() or path.is_junction():
            raise EvoError(f'snapshot workspace contains a link: {path}')
        if path.is_dir():
            continue
        total += path.stat().st_size
        if len(entries) >= MAX_SNAPSHOT_FILES or total > MAX_SNAPSHOT_BYTES:
            raise EvoError('snapshot workspace exceeds 200000 files or 8 GiB')
        entries.append({'path': path.relative_to(resolved).as_posix(), 'bytes': path.stat().st_size,
                        'sha256': _sha256(path)})
    payload = '\n'.join(f"{e['path']}\0{e['bytes']}\0{e['sha256']}" for e in entries).encode('utf-8')
    return {'files': entries, 'file_count': len(entries), 'bytes': total,
            'tree_sha256': hashlib.sha256(payload).hexdigest()}


def _location(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) not in ({'path'}, {'path', 'line'}, {'path', 'start_line', 'end_line'},
                                                          {'path', 'label'},
                                                          {'path', 'line', 'label'}, {'path', 'start_line', 'end_line', 'label'}):
        raise EvoError(f'{where} must be a path, path+line, or path+inclusive-range location')
    path = value.get('path')
    if not isinstance(path, str) or not path or Path(path).is_absolute() or '..' in Path(path).parts:
        raise EvoError(f'{where}.path must be a safe snapshot-relative path')
    if 'line' in value:
        if isinstance(value['line'], bool) or not isinstance(value['line'], int) or value['line'] < 1:
            raise EvoError(f'{where}.line must be a positive integer')
    elif 'start_line' in value and (
        any(isinstance(value[key], bool) or not isinstance(value[key], int) for key in ('start_line', 'end_line'))
        or value['start_line'] < 1 or value['end_line'] < value['start_line']
    ):
        raise EvoError(f'{where} range must be 1-based inclusive')
    if 'label' in value and (not isinstance(value['label'], str) or not value['label']):
        raise EvoError(f'{where}.label must be nonempty')
    return {**value, 'path': Path(path).as_posix()}


def import_catalog(source_path: Path, snapshot_root: Path) -> dict[str, Any]:
    source = read_json(source_path)
    if source.get('schema') != SOURCE_SCHEMA or set(source) != {'schema', 'id', 'version', 'items', 'groups'}:
        raise EvoError(f'code-reading source must use {SOURCE_SCHEMA} and contain only its declared fields')
    declared_root = snapshot_root.absolute()
    if declared_root.is_symlink() or declared_root.is_junction():
        raise EvoError('prepared snapshot root must not be a link')
    root = declared_root.resolve()
    if not root.is_dir():
        raise EvoError('prepared snapshot root is unavailable')
    seen, snapshots, items = set(), {}, []
    for index, item in enumerate(source['items']):
        where = f'items[{index}]'
        required = {'id', 'family', 'workspace', 'prompt', 'answer_max_lines', 'required_locations'}
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - {*required, 'supporting'}:
            raise EvoError(f'{where} fields differ from the code-reading task contract')
        identity = item['id']
        if not isinstance(identity, str) or not identity or identity in seen:
            raise EvoError(f'{where}.id is invalid or duplicate')
        seen.add(identity)
        workspace = item['workspace']
        if not isinstance(workspace, str) or not workspace or Path(workspace).is_absolute() or '..' in Path(workspace).parts:
            raise EvoError(f'{where}.workspace must be snapshot-root relative')
        workspace = Path(workspace).as_posix()
        raw_target = declared_root / workspace
        cursor = raw_target
        while cursor != declared_root:
            if cursor.is_symlink() or cursor.is_junction():
                raise EvoError(f'{where}.workspace crosses a link inside snapshot root')
            cursor = cursor.parent
        target = raw_target.resolve()
        if not target.is_relative_to(root):
            raise EvoError(f'{where}.workspace leaves snapshot root')
        if workspace not in snapshots:
            snapshots[workspace] = snapshot_inventory(target)
        locations = [_location(value, f'{where}.required_locations[{i}]')
                     for i, value in enumerate(item['required_locations'])]
        if not locations:
            raise EvoError(f'{where}.required_locations must not be empty')
        semantic_locations = [tuple((key, location[key]) for key in ('path', 'line', 'start_line', 'end_line') if key in location)
                              for location in locations]
        if len(set(semantic_locations)) != len(semantic_locations):
            raise EvoError(f'{where}.required_locations contains a duplicate location')
        line_counts: dict[str, int] = {}
        for location in locations:
            if location['path'] not in {entry['path'] for entry in snapshots[workspace]['files']}:
                raise EvoError(f"{where} answer path is absent from the frozen workspace: {location['path']}")
            if 'line' in location or 'end_line' in location:
                if location['path'] not in line_counts:
                    # Source snapshots may contain legacy encodings. Line identity is byte-delimiter based;
                    # importing must not transcode or require UTF-8 source text.
                    line_counts[location['path']] = len((target / location['path']).read_bytes().splitlines())
                last = location.get('line', location.get('end_line'))
                if last > line_counts[location['path']]:
                    raise EvoError(f"{where} answer line is outside the frozen source: {location['path']}")
        if not isinstance(item['family'], str) or not item['family'] or not isinstance(item['prompt'], str) \
                or not item['prompt'] or isinstance(item['answer_max_lines'], bool) \
                or not isinstance(item['answer_max_lines'], int) or item['answer_max_lines'] < 1:
            raise EvoError(f'{where} family/prompt/answer_max_lines is invalid')
        supporting = item.get('supporting', [])
        if not isinstance(supporting, list) or any(not isinstance(value, str) or not value for value in supporting):
            raise EvoError(f'{where}.supporting must contain strings')
        items.append({**item, 'workspace': workspace, 'required_locations': locations,
                      **({'supporting': supporting} if supporting else {})})
    groups = source['groups']
    if not isinstance(groups, list) or any(not isinstance(group, dict) or set(group) != {'id', 'items'} for group in groups):
        raise EvoError('groups must contain only id/items')
    if any(task not in seen for group in groups for task in group['items']):
        raise EvoError('group references an unknown code-reading item')
    return {'schema': CATALOG_SCHEMA, 'id': source['id'], 'version': source['version'],
            'source_sha256': _sha256(source_path.resolve()), 'snapshots': snapshots,
            'items': items, 'groups': copy.deepcopy(groups)}


def load_catalog(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    if expected_sha256 is not None and _sha256(path.resolve()) != expected_sha256:
        raise EvoError('code-reading catalog changed from its explicit binding')
    value = read_json(path)
    if value.get('schema') != CATALOG_SCHEMA or set(value) != {'schema', 'id', 'version', 'source_sha256', 'snapshots', 'items', 'groups'}:
        raise EvoError(f'invalid {CATALOG_SCHEMA} catalog')
    if not isinstance(value.get('id'), str) or not value['id'] or not isinstance(value.get('version'), str) \
            or not value['version'] or not re.fullmatch(r'[0-9a-f]{64}', str(value.get('source_sha256'))):
        raise EvoError('code-reading catalog identity/source hash is invalid')
    if not isinstance(value['snapshots'], dict) or not value['snapshots']:
        raise EvoError('code-reading catalog snapshots must be a nonempty object')
    snapshot_paths: dict[str, set[str]] = {}
    for workspace, snapshot in value['snapshots'].items():
        if not isinstance(workspace, str) or not workspace or Path(workspace).is_absolute() or '..' in Path(workspace).parts \
                or not isinstance(snapshot, dict) or set(snapshot) != {'files', 'file_count', 'bytes', 'tree_sha256'}:
            raise EvoError('code-reading catalog snapshot shape is invalid')
        files = snapshot['files']
        if not isinstance(files, list) or snapshot['file_count'] != len(files):
            raise EvoError('code-reading catalog snapshot file count is invalid')
        seen_paths, byte_total = set(), 0
        for entry in files:
            if not isinstance(entry, dict) or set(entry) != {'path', 'bytes', 'sha256'} \
                    or not isinstance(entry['path'], str) or not entry['path'] \
                    or Path(entry['path']).is_absolute() or '..' in Path(entry['path']).parts \
                    or entry['path'] in seen_paths or isinstance(entry['bytes'], bool) \
                    or not isinstance(entry['bytes'], int) or entry['bytes'] < 0 \
                    or not re.fullmatch(r'[0-9a-f]{64}', str(entry['sha256'])):
                raise EvoError('code-reading catalog snapshot file identity is invalid')
            seen_paths.add(entry['path']); byte_total += entry['bytes']
        payload = '\n'.join(f"{e['path']}\0{e['bytes']}\0{e['sha256']}" for e in files).encode('utf-8')
        if snapshot['bytes'] != byte_total or snapshot['tree_sha256'] != hashlib.sha256(payload).hexdigest():
            raise EvoError('code-reading catalog snapshot aggregate identity is invalid')
        snapshot_paths[workspace] = seen_paths
    if not isinstance(value['items'], list) or not value['items']:
        raise EvoError('code-reading catalog items must be nonempty')
    ids = set()
    for index, item in enumerate(value['items']):
        required = {'id', 'family', 'workspace', 'prompt', 'answer_max_lines', 'required_locations'}
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - {*required, 'supporting'} \
                or not isinstance(item['id'], str) or not item['id'] or item['id'] in ids \
                or item['workspace'] not in snapshot_paths:
            raise EvoError(f'code-reading catalog item {index} is invalid')
        ids.add(item['id'])
        locations = [_location(row, f'items[{index}].required_locations') for row in item['required_locations']]
        semantic = [tuple((key, row[key]) for key in ('path', 'line', 'start_line', 'end_line') if key in row)
                    for row in locations]
        if not locations or len(semantic) != len(set(semantic)) \
                or any(row['path'] not in snapshot_paths[item['workspace']] for row in locations):
            raise EvoError(f'code-reading catalog item {index} answer locations are invalid')
        if not isinstance(item['family'], str) or not item['family'] or not isinstance(item['prompt'], str) \
                or not item['prompt'] or isinstance(item['answer_max_lines'], bool) \
                or not isinstance(item['answer_max_lines'], int) or item['answer_max_lines'] < 1:
            raise EvoError(f'code-reading catalog item {index} family/prompt contract is invalid')
        supporting = item.get('supporting', [])
        if not isinstance(supporting, list) or any(not isinstance(row, str) or not row for row in supporting):
            raise EvoError(f'code-reading catalog item {index} supporting answers are invalid')
    if not isinstance(value['groups'], list) or not value['groups']:
        raise EvoError('code-reading catalog groups must be nonempty')
    group_ids = set()
    for group in value['groups']:
        if not isinstance(group, dict) or set(group) != {'id', 'items'} or not isinstance(group['id'], str) \
                or not group['id'] or group['id'] in group_ids or not isinstance(group['items'], list) \
                or not group['items'] or len(group['items']) != len(set(group['items'])) \
                or any(item_id not in ids for item_id in group['items']):
            raise EvoError('code-reading catalog group is invalid')
        group_ids.add(group['id'])
    return value


def resolve_catalog(spec: dict[str, Any], spec_path: Path) -> dict[str, Any]:
    evaluations = spec.get('evaluations')
    if not isinstance(evaluations, dict) or 'catalog' not in evaluations:
        return spec
    if set(evaluations) - {'catalog', 'observations'}:
        raise EvoError('evaluations.catalog cannot coexist with inline items/groups')
    binding = evaluations['catalog']
    if not isinstance(binding, dict) or set(binding) != {'source', 'sha256'}:
        raise EvoError('evaluations.catalog requires source and sha256')
    path = (spec_path.parent / binding['source']).resolve()
    if read_json(path).get('schema') != CATALOG_SCHEMA:
        return spec
    catalog = load_catalog(path, binding['sha256'])
    runtime = spec.get('runtime', {})
    code_runtime = runtime.get('code_reading') if isinstance(runtime, dict) else None
    if code_runtime is not None and (not isinstance(code_runtime, dict) or set(code_runtime) != {'snapshot_root'}):
        raise EvoError('research runtime.code_reading requires only snapshot_root')
    snapshot_root = Path(str(code_runtime['snapshot_root'])) if code_runtime is not None else None
    if snapshot_root is not None and not snapshot_root.is_absolute():
        raise EvoError('runtime.code_reading.snapshot_root must be absolute')
    result = copy.deepcopy(spec)
    result['evaluations'] = {'items': [], 'groups': copy.deepcopy(catalog['groups'])}
    observations = copy.deepcopy(evaluations.get('observations', []))
    for item in catalog['items']:
        snapshot = catalog['snapshots'][item['workspace']]
        result['evaluations']['items'].append({
            'id': item['id'], 'family': item['family'], 'input_version': snapshot['tree_sha256'],
            'protocol': 'code-reading-locations/v1', 'observations': observations,
            'prompt': item['prompt'], 'answer_max_lines': item['answer_max_lines'],
            'required_locations': copy.deepcopy(item['required_locations']),
            'runtime': {'code_reading': {**({'snapshot_root': str(snapshot_root.resolve())} if snapshot_root else {}),
                                         'workspace': item['workspace'], 'snapshot': copy.deepcopy(snapshot)}},
        })
    result['catalog_source'] = {'source': str(path), 'sha256': binding['sha256']}
    return result
