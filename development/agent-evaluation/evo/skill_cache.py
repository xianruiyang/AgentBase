"""Content-addressed Evo skill payload cache using the deployment payload owner."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from evaluation_core import CaseLock, EvaluationError, write_json_atomic
from .spec import EvoError
from .store import canonical


CACHE_SCHEMA = 'agentbase-evo-skill-cache/v1'
PAYLOAD_SCHEMA = 'agentbase-payload-manifest/v1'
MAX_PAYLOAD_FILES = 4096
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


def _reject_reparse_chain(path: Path, label: str) -> Path:
    lexical = path.absolute()
    cursor = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        cursor /= part
        if cursor.exists() and (cursor.is_symlink() or cursor.is_junction()):
            raise EvoError(f'{label} must not traverse a reparse point')
    return lexical


def _managed_child(root: Path, child: Path, label: str) -> Path:
    root = _reject_reparse_chain(root, label)
    child = child.absolute()
    try:
        relative = child.relative_to(root)
    except ValueError as exc:
        raise EvoError(f'{label} leaves its managed root') from exc
    cursor = root
    for part in relative.parts[:-1]:
        cursor /= part
        if cursor.exists() and (cursor.is_symlink() or cursor.is_junction()):
            raise EvoError(f'{label} traverses a reparse point')
    return child


def physical_manifest(root: Path) -> dict[str, Any]:
    root = _reject_reparse_chain(root, 'skill cache payload')
    if not root.is_dir():
        raise EvoError('skill cache payload is unavailable')
    files, total = [], 0
    for path in sorted(root.rglob('*'), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink() or path.is_junction():
            raise EvoError('skill cache payload contains a reparse point')
        if path.is_dir():
            continue
        total += path.stat().st_size
        if len(files) >= MAX_PAYLOAD_FILES or total > MAX_PAYLOAD_BYTES:
            raise EvoError('skill cache payload exceeds its file or byte bound')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest})
    identity = hashlib.sha256(canonical({'files': files}).encode('utf-8')).hexdigest()
    return {'schema': PAYLOAD_SCHEMA, 'identity_sha256': identity, 'files': files}


def _require_regular_tree(root: Path, label: str) -> None:
    _reject_reparse_chain(root, label)
    for path in root.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise EvoError(f'{label} contains an unmanaged reparse point')


def _bundle_manifests(payload: Path) -> dict[str, dict[str, Any]]:
    if not payload.is_dir() or any(not path.is_dir() or path.is_junction() for path in payload.iterdir()):
        raise EvoError('skill cache bundle members must be real directories')
    return {path.name: physical_manifest(path) for path in sorted(payload.iterdir(), key=lambda item: item.name.casefold())}


def _bundle_identity(skills: dict[str, dict[str, Any]]) -> str:
    descriptor = {'skills': [{'name': name, 'manifest': skills[name]} for name in sorted(skills)]}
    return hashlib.sha256(canonical(descriptor).encode('utf-8')).hexdigest()


def _bridge(project_root: Path, action: str, source: Path, destination: Path | None = None) -> dict[str, Any]:
    script = project_root.resolve() / 'development' / 'common' / 'get_payload_manifest.ps1'
    argv = ['pwsh.exe', '-NoProfile', '-NonInteractive', '-File', str(script),
            '-Action', action, '-SourcePath', str(source)]
    if destination is not None:
        argv.extend(['-DestinationPath', str(destination)])
    completed = subprocess.run(argv, cwd=str(project_root.resolve()), capture_output=True, text=True,
                               encoding='utf-8', timeout=120, check=False)
    if completed.returncode != 0:
        raise EvoError(f'skill payload owner failed: {(completed.stderr or completed.stdout).strip()[:700]}')
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EvoError('skill payload owner returned invalid JSON') from exc
    if not isinstance(value, dict) or value.get('schema') != PAYLOAD_SCHEMA or not isinstance(value.get('files'), list):
        raise EvoError('skill payload owner returned an invalid manifest')
    return value


def payload_manifest(project_root: Path, source: Path) -> dict[str, Any]:
    value = _bridge(project_root, 'Manifest', source.resolve())
    seen = set()
    for entry in value['files']:
        if not isinstance(entry, dict) or set(entry) != {'path', 'bytes', 'sha256'}:
            raise EvoError('skill payload manifest file shape is invalid')
        path = entry['path']
        if not isinstance(path, str) or not path or Path(path).is_absolute() or '..' in Path(path).parts \
                or path in seen or type(entry['bytes']) is not int or entry['bytes'] < 0 \
                or not isinstance(entry['sha256'], str) or len(entry['sha256']) != 64:
            raise EvoError('skill payload manifest file identity is invalid')
        seen.add(path)
    if len(value['files']) > MAX_PAYLOAD_FILES or sum(entry['bytes'] for entry in value['files']) > MAX_PAYLOAD_BYTES:
        raise EvoError('skill payload manifest exceeds its file or byte bound')
    identity = hashlib.sha256(canonical({'files': value['files']}).encode('utf-8')).hexdigest()
    return {'schema': PAYLOAD_SCHEMA, 'identity_sha256': identity, 'files': value['files']}


def _manage(project_root: Path, action: str, path: Path, *, target: Path | None = None,
            sddl: str | None = None) -> dict[str, Any]:
    script = project_root.resolve() / 'development' / 'agent-evaluation' / 'evo' / 'manage_skill_cache.ps1'
    argv = ['pwsh.exe', '-NoProfile', '-NonInteractive', '-File', str(script),
            '-Action', action, '-Path', str(path)]
    if target is not None:
        argv.extend(['-Target', str(target)])
    if sddl is not None:
        argv.extend(['-Sddl', sddl])
    completed = subprocess.run(argv, cwd=str(project_root.resolve()), capture_output=True, text=True,
                               encoding='utf-8', timeout=120, check=False)
    if completed.returncode != 0:
        raise EvoError(f'skill cache lifecycle owner failed: {(completed.stderr or completed.stdout).strip()[:700]}')
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EvoError('skill cache lifecycle owner returned invalid JSON') from exc


class SkillCache:
    def __init__(self, project_root: Path, state_root: Path, *, cancel_check=None, wait_seconds: int = 120):
        self.project_root = project_root.resolve()
        self.state_root = _reject_reparse_chain(state_root, 'Evo state root').resolve()
        self.root = self.state_root / 'skill-cache'
        self.versions = self.root / 'versions'
        self.staging = self.root / 'staging'
        self.cancel_check = cancel_check
        self.wait_seconds = wait_seconds

    @contextmanager
    def _lock(self, identity: str):
        deadline = time.monotonic() + self.wait_seconds
        while True:
            lock = CaseLock(self.state_root, f'evo-skill-cache:{identity}')
            try:
                lock.__enter__()
                break
            except EvaluationError as exc:
                if self.cancel_check is not None and self.cancel_check():
                    raise EvoError('cancelled while waiting for a shared skill cache version') from exc
                if time.monotonic() >= deadline:
                    raise EvoError('timed out waiting for a shared skill cache version') from exc
                time.sleep(.1)
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def _initialize(self) -> None:
        _reject_reparse_chain(self.root, 'skill cache root')
        self.versions.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        marker = self.root / 'owner.json'
        expected = {'schema': CACHE_SCHEMA, 'state_root': str(self.state_root)}
        if marker.exists():
            try:
                if json.loads(marker.read_text(encoding='utf-8')) != expected:
                    raise EvoError('skill cache owner marker does not match this Evo state root')
            except json.JSONDecodeError as exc:
                raise EvoError('skill cache owner marker is invalid') from exc
        else:
            write_json_atomic(marker, expected)

    def materialize_bundle(self, sources: dict[str, Path]) -> dict[str, Any]:
        if not sources:
            raise EvoError('skill cache bundle requires at least one selected skill')
        if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) for name in sources):
            raise EvoError('skill cache bundle contains an invalid stable skill name')
        skill_manifests = {name: payload_manifest(self.project_root, source) for name, source in sorted(sources.items())}
        identity = _bundle_identity(skill_manifests)
        with self._lock(identity):
            self._initialize()
            alias = 'v-' + identity[:12]
            version = self.versions / alias
            payload = version / 'payload'
            manifest_path = version / 'manifest.json'
            if version.exists():
                if not manifest_path.is_file() or not payload.is_dir():
                    raise EvoError('skill cache version is incomplete; remove it through cache recovery')
                cached = json.loads(manifest_path.read_text(encoding='utf-8'))
                if cached.get('skills') != skill_manifests:
                    raise EvoError('skill cache short version alias collides with a different full identity')
                if set(path.name for path in payload.iterdir()) != set(skill_manifests) \
                        or any(physical_manifest(payload / name) != manifest for name, manifest in skill_manifests.items()):
                    raise EvoError('shared skill cache version changed after publication')
                if _manage(self.project_root, 'Inspect', payload).get('sddl') != cached.get('protected_sddl'):
                    raise EvoError('shared skill cache write protection changed after publication')
                return {'identity_sha256': identity, 'payload': str(payload), 'disposition': 'reused',
                        'skills': skill_manifests, 'version_alias': alias}
            stage = self.staging / f'{alias}.{os.getpid()}'
            _managed_child(self.staging, stage, 'skill cache staging path')
            if stage.exists():
                raise EvoError('skill cache staging path is already owned')
            try:
                stage.mkdir(parents=True)
                recovery = {'schema': CACHE_SCHEMA, 'identity_sha256': identity, 'version_alias': alias,
                            'skills': skill_manifests}
                write_json_atomic(stage / 'recovery.json', recovery)
                for name, source in sorted(sources.items()):
                    _bridge(self.project_root, 'Copy', source.resolve(), stage / 'payload' / name)
                    if physical_manifest(stage / 'payload' / name) != skill_manifests[name]:
                        raise EvoError('materialized skill payload differs from its filtered source')
                recovery['restore_sddl'] = _manage(self.project_root, 'Inspect', stage / 'payload')['sddl']
                write_json_atomic(stage / 'recovery.json', recovery)
                protection = _manage(self.project_root, 'Protect', stage / 'payload')
                write_json_atomic(stage / 'manifest.json', {
                    'schema': CACHE_SCHEMA, 'identity_sha256': identity, 'version_alias': alias,
                    'skills': skill_manifests, 'restore_sddl': recovery['restore_sddl'],
                    'protected_sddl': protection['protected_sddl'],
                })
                stage.replace(version)
            except Exception:
                if stage.exists():
                    recovery_path = stage / 'recovery.json'
                    if recovery_path.is_file():
                        cached = json.loads(recovery_path.read_text(encoding='utf-8'))
                        if 'restore_sddl' in cached:
                            _manage(self.project_root, 'Restore', stage / 'payload', sddl=cached['restore_sddl'])
                    shutil.rmtree(_managed_child(self.staging, stage, 'skill cache staging cleanup'))
                raise
            return {'identity_sha256': identity, 'payload': str(payload), 'disposition': 'created',
                    'skills': skill_manifests, 'version_alias': alias}

    def create_reference(self, workspace: Path, skill_name: str, version: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(skill_name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', skill_name):
            raise EvoError('managed skill reference name is invalid')
        identity = version.get('identity_sha256')
        alias = version.get('version_alias')
        if not isinstance(identity, str) or not isinstance(alias, str) or alias != 'v-' + identity[:12]:
            raise EvoError('managed skill cache version identity is invalid')
        bundle_root = _managed_child(self.versions, self.versions / alias / 'payload', 'skill cache version payload')
        if Path(str(version.get('payload'))).absolute() != bundle_root or skill_name not in version.get('skills', {}):
            raise EvoError('managed skill cache payload leaves its fixed version')
        target = _managed_child(bundle_root, bundle_root / skill_name, 'skill cache bundle member')
        workspace = _reject_reparse_chain(workspace, 'Evo workspace').resolve()
        link = workspace / '.agents' / 'skills' / skill_name
        _managed_child(workspace, link, 'managed skill reference path')
        reference_id = hashlib.sha256(f'{workspace}\0{skill_name}'.encode('utf-8')).hexdigest()
        reference_path = self.versions / alias / 'references' / f'{reference_id}.json'
        _managed_child(self.versions, reference_path, 'managed skill reference registry')
        value = {'schema': CACHE_SCHEMA, 'identity_sha256': identity, 'version_alias': alias,
                 'workspace': str(workspace), 'name': skill_name,
                 'link': str(link), 'target': str(target), 'reference_id': reference_id}
        with self._lock(identity):
            if reference_path.exists():
                if json.loads(reference_path.read_text(encoding='utf-8')) != value:
                    raise EvoError('managed skill reference registry conflicts')
                if not link.exists():
                    _manage(self.project_root, 'CreateJunction', link, target=target)
                self.validate_reference(value)
                return value
            reference_path.parent.mkdir(exist_ok=True)
            if link.exists():
                if not link.is_junction() or link.resolve() != target.resolve():
                    raise EvoError('unregistered skill reference occupies the managed path')
                write_json_atomic(reference_path, value)
                return value
            write_json_atomic(reference_path, value)
            try:
                _manage(self.project_root, 'CreateJunction', link, target=target)
            except Exception:
                reference_path.unlink(missing_ok=True)
                raise
        return value

    def _reference_binding(self, reference: dict[str, Any], *, require_registry: bool = True) -> tuple[Path, Path, Path]:
        required = {'schema', 'identity_sha256', 'version_alias', 'workspace', 'name',
                    'link', 'target', 'reference_id'}
        if not isinstance(reference, dict) or set(reference) != required or reference.get('schema') != CACHE_SCHEMA:
            raise EvoError('managed skill reference shape is invalid')
        identity, alias, name = reference['identity_sha256'], reference['version_alias'], reference['name']
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity) \
                or alias != 'v-' + identity[:12] \
                or not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) \
                or any(not isinstance(reference[key], str) for key in ('workspace', 'link', 'target', 'reference_id')):
            raise EvoError('managed skill reference identity is invalid')
        workspace = _reject_reparse_chain(Path(reference['workspace']), 'managed skill reference workspace').resolve()
        link = workspace / '.agents' / 'skills' / name
        if Path(reference['link']).absolute() != link.absolute():
            raise EvoError('managed skill reference link is outside its workspace binding')
        bundle_root = _managed_child(self.versions, self.versions / alias / 'payload', 'managed skill reference target')
        target = _managed_child(bundle_root, bundle_root / name, 'managed skill reference target')
        if Path(reference['target']).absolute() != target:
            raise EvoError('managed skill reference target is outside its cache version')
        expected_ref = hashlib.sha256(f'{workspace}\0{name}'.encode('utf-8')).hexdigest()
        if reference['reference_id'] != expected_ref:
            raise EvoError('managed skill reference id differs from workspace/name binding')
        registry = _managed_child(self.versions, self.versions / alias / 'references' / f'{expected_ref}.json',
                                  'managed skill reference registry')
        if require_registry and (not registry.is_file() or json.loads(registry.read_text(encoding='utf-8')) != reference):
            raise EvoError('managed skill reference is absent from its cache registry')
        return link, target, registry

    def validate_reference(self, reference: dict[str, Any]) -> None:
        link, target, registry = self._reference_binding(reference)
        if not link.is_junction() or link.resolve() != target:
            raise EvoError('managed skill reference differs from its fixed cache target')
        manifest = json.loads((self.versions / reference['version_alias'] / 'manifest.json').read_text(encoding='utf-8'))
        bundle_root = target.parent
        if manifest.get('identity_sha256') != reference['identity_sha256'] \
                or _bundle_manifests(bundle_root) != manifest.get('skills') \
                or _manage(self.project_root, 'Inspect', bundle_root).get('sddl') != manifest.get('protected_sddl'):
            raise EvoError('managed skill cache version changed after publication')

    def validate_workspace_references(self, workspace: Path, references: list[dict[str, Any]], *, content: bool = True) -> None:
        workspace = workspace.resolve()
        root = workspace / '.agents' / 'skills'
        expected = {reference['name']: reference for reference in references}
        if len(expected) != len(references):
            raise EvoError('workspace skill projection contains duplicate managed names')
        actual = {path.name: path for path in root.iterdir()} if root.is_dir() else {}
        if set(actual) != set(expected):
            raise EvoError('workspace skill projection contains an unregistered entry')
        validated_versions = set()
        for name, reference in expected.items():
            bound_link, bound_target, _registry = self._reference_binding(reference)
            if Path(reference['workspace']).resolve() != workspace or bound_link.absolute() != (root / name).absolute():
                raise EvoError('workspace skill reference belongs to a different workspace')
            link = actual[name]
            if not link.is_junction() or link.resolve() != bound_target:
                raise EvoError('workspace skill projection reference target changed')
            identity = reference['identity_sha256']
            if content and identity not in validated_versions:
                self.validate_reference(reference)
                validated_versions.add(identity)

    def references_for_workspace(self, workspace: Path) -> list[dict[str, Any]]:
        workspace = str(workspace.resolve())
        result = []
        if not self.versions.is_dir():
            return result
        for path in self.versions.glob('v-*/references/*.json'):
            reference = json.loads(path.read_text(encoding='utf-8'))
            if reference.get('workspace') == workspace:
                result.append(reference)
        return result

    def recover_workspace_references(self, workspace: Path) -> int:
        """Detach registry-backed junctions even when projection/cache content is polluted."""
        references = self.references_for_workspace(workspace)
        if not references:
            return 0
        workspace = workspace.resolve()
        root = workspace / '.agents' / 'skills'
        expected = {reference['name']: reference for reference in references}
        actual = {path.name: path for path in root.iterdir()} if root.is_dir() else {}
        if set(actual) - set(expected):
            raise EvoError('workspace skill recovery contains an unregistered entry')
        for name, link in actual.items():
            _bound_link, target, _registry = self._reference_binding(expected[name])
            if not link.is_junction() or link.resolve() != target:
                raise EvoError('workspace skill recovery reference target changed')
        for reference in references:
            self.remove_reference(reference)
        return len(references)

    def remove_reference(self, reference: dict[str, Any]) -> None:
        link, target, registry = self._reference_binding(reference)
        identity = reference['identity_sha256']
        with self._lock(identity):
            if link.exists() or link.is_junction():
                if not link.is_junction() or link.resolve() != target:
                    raise EvoError('managed skill reference target changed; removal refused')
                _manage(self.project_root, 'RemoveJunction', link, target=target)
            registry.unlink(missing_ok=True)

    def remove_unreferenced_version(self, identity: str) -> None:
        alias = 'v-' + identity[:12]
        with self._lock(identity):
            version = _managed_child(self.versions, self.versions / alias, 'skill cache version removal')
            manifest_path = version / 'manifest.json'
            recovery_path = version / 'recovery.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
            recovery = json.loads(recovery_path.read_text(encoding='utf-8')) if recovery_path.is_file() else manifest
            if manifest.get('identity_sha256') != identity:
                raise EvoError('skill cache version identity does not match its removal request')
            references = version / 'references'
            if references.is_dir() and any(references.iterdir()):
                raise EvoError('skill cache version still has managed references')
            _require_regular_tree(version, 'skill cache version removal')
            _manage(self.project_root, 'Restore', version / 'payload', sddl=recovery['restore_sddl'])
            shutil.rmtree(version)

    def remove_unreferenced_alias(self, alias: str) -> str:
        if not re.fullmatch(r'v-[0-9a-f]{12}', alias):
            raise EvoError('skill cache version alias must be v- plus 12 lowercase hex digits')
        version = _managed_child(self.versions, self.versions / alias, 'skill cache version removal')
        if not version.exists():
            recovered = self.recover_staging(alias)
            if recovered is None:
                raise EvoError('skill cache version alias is unavailable')
            return recovered
        manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
        identity = manifest.get('identity_sha256')
        if not isinstance(identity, str) or alias != 'v-' + identity[:12]:
            raise EvoError('skill cache alias does not bind a valid full identity')
        self.remove_unreferenced_version(identity)
        return identity

    def recover_staging(self, alias: str) -> str | None:
        if not re.fullmatch(r'v-[0-9a-f]{12}', alias):
            raise EvoError('skill cache version alias must be v- plus 12 lowercase hex digits')
        stages = list(self.staging.glob(alias + '.*')) if self.staging.is_dir() else []
        if not stages:
            return None
        identities = set()
        for stage in stages:
            stage = _managed_child(self.staging, stage, 'skill cache staging recovery')
            recovery_path = stage / 'recovery.json'
            if not recovery_path.is_file():
                raise EvoError('skill cache staging intent is unavailable; recovery refused')
            recovery = json.loads(recovery_path.read_text(encoding='utf-8'))
            identity = recovery.get('identity_sha256')
            if recovery.get('schema') != CACHE_SCHEMA or recovery.get('version_alias') != alias \
                    or not isinstance(identity, str) or alias != 'v-' + identity[:12] \
                    or not isinstance(recovery.get('skills'), dict) \
                    or _bundle_identity(recovery['skills']) != identity:
                raise EvoError('skill cache staging recovery identity is invalid')
            with self._lock(identity):
                if not stage.exists():
                    continue
                current = json.loads(recovery_path.read_text(encoding='utf-8'))
                if current != recovery:
                    raise EvoError('skill cache staging intent changed during recovery')
                identities.add(identity)
                _require_regular_tree(stage, 'skill cache staging recovery')
                if 'restore_sddl' in recovery:
                    _manage(self.project_root, 'Restore', stage / 'payload', sddl=recovery['restore_sddl'])
                shutil.rmtree(stage)
        if len(identities) != 1:
            raise EvoError('skill cache staging alias contains conflicting full identities')
        return identities.pop()

    def status(self) -> dict[str, Any]:
        if not self.root.exists():
            return {'schema': CACHE_SCHEMA, 'root': str(self.root), 'versions': [], 'staging': [], 'used_bytes': 0}
        marker = self.root / 'owner.json'
        expected = {'schema': CACHE_SCHEMA, 'state_root': str(self.state_root)}
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')) != expected:
            raise EvoError('skill cache owner marker does not match this Evo state root')
        versions, used = [], 0
        for version in sorted(self.versions.glob('v-*')):
            manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
            identity = manifest.get('identity_sha256')
            if version.name != 'v-' + str(identity)[:12]:
                raise EvoError('skill cache version alias differs from its full identity')
            if _bundle_manifests(version / 'payload') != manifest.get('skills') \
                    or _manage(self.project_root, 'Inspect', version / 'payload').get('sddl') != manifest.get('protected_sddl'):
                raise EvoError('shared skill cache version changed after publication')
            references = sorted((version / 'references').glob('*.json')) if (version / 'references').is_dir() else []
            for reference_path in references:
                link, target, _registry = self._reference_binding(json.loads(reference_path.read_text(encoding='utf-8')))
                if not link.is_junction() or link.resolve() != target:
                    raise EvoError('managed skill reference differs from its fixed cache target')
            version_bytes = sum(path.stat().st_size for path in version.rglob('*') if path.is_file())
            used += version_bytes
            versions.append({'alias': version.name, 'identity_sha256': identity,
                             'skill_count': len(manifest['skills']),
                             'file_count': sum(len(skill['files']) for skill in manifest['skills'].values()),
                             'bytes': version_bytes, 'references': len(references)})
        staging = []
        if self.staging.is_dir():
            for path in sorted(self.staging.iterdir()):
                match = re.fullmatch(r'(v-[0-9a-f]{12})\.[0-9]+', path.name)
                if not match or not path.is_dir() or path.is_junction():
                    raise EvoError('skill cache staging entry is invalid')
                staging.append({'alias': match.group(1), 'entry': path.name})
        return {'schema': CACHE_SCHEMA, 'root': str(self.root), 'versions': versions,
                'staging': staging, 'used_bytes': used}
