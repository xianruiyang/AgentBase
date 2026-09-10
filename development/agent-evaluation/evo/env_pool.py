"""Bounded reusable writable slots for Evo subjects."""
from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

from .spec import EvoError
from .store import canonical


class EnvironmentPool:
    """Own writable slots; evidence lives in state, while slots remain rebuildable."""

    def __init__(self, work_root: Path, state_root: Path, project_root: Path | None = None):
        self.work_root = work_root.resolve()
        self.state_root = state_root.resolve()
        self.slots_root = self.work_root
        self.project_root = project_root.resolve() if project_root is not None else None

    def _managed_skill_references(self, workspace: Path, *, content: bool = False) -> list[dict]:
        manifest = workspace / '.agentbase' / 'evo-codex-projection.json'
        if not manifest.is_file() or manifest.is_symlink():
            return []
        value = json.loads(manifest.read_text(encoding='utf-8'))
        references = value.get('result', {}).get('skill_references', [])
        if not references:
            return []
        if self.project_root is None or not isinstance(references, list):
            raise EvoError('managed skill references require their Evo project owner')
        from .skill_cache import SkillCache
        cache = SkillCache(self.project_root, self.state_root)
        cache.validate_workspace_references(workspace, references, content=content)
        return references

    def _meta(self, slot: int) -> Path:
        return self.slots_root / f'slot-{slot:04d}' / '.evo-slot.json'

    def acquire(self, slot: int, job: dict, desired: set[str], desired_prefixes: set[str] | None = None) -> Path:
        workspace = self._meta(slot).parent
        workspace.mkdir(parents=True, exist_ok=True)
        meta_path = self._meta(slot)
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if meta.get('state') == 'quarantined':
                raise EvoError(f'writable slot {slot} is quarantined: {meta.get("reason", "unknown state")}')
            prior = meta.get('job')
            if prior != job['id'] or meta.get('state') == 'reusable':
                receipt = self.state_root / 'jobs' / f'j{prior}' / 'receipt.json'
                if not receipt.is_file() and meta.get('state') != 'reusable':
                    raise EvoError(f'writable slot {slot} has no archived final receipt; recovery must reconcile it')
                self._archive_and_reset(workspace, prior, meta, desired, desired_prefixes or set())
        meta = {'schema': 'agentbase-evo-slot/v1', 'slot': slot, 'job': job['id'], 'attempt': job.get('attempt_seq', 1),
                'execution_identity': job['identity'], 'state': 'leased', 'baseline': {}}
        meta_path.write_text(canonical(meta) + '\n', encoding='utf-8')
        return workspace

    def record_baseline(self, workspace: Path, job: dict) -> None:
        meta_path = workspace / '.evo-slot.json'
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        meta['baseline'] = self._inventory(workspace)
        meta_path.write_text(canonical(meta) + '\n', encoding='utf-8')

    def restore_projection_owner(self, workspace: Path) -> bool:
        """Restore an archived projection manifest only after its live references validate."""
        manifest = workspace / '.agentbase' / 'evo-codex-projection.json'
        if manifest.exists() or manifest.is_symlink():
            return False
        if self.project_root is None:
            raise EvoError('projection owner recovery requires its Evo project owner')
        from .skill_cache import SkillCache
        candidates = []
        jobs_root = self.state_root / 'jobs'
        for job_root in jobs_root.glob('j*'):
            archived = job_root / 'workspace-diff' / '.agentbase' / manifest.name
            receipt = job_root / 'receipt.json'
            intent = job_root / 'intent.json'
            if not archived.is_file() or archived.is_symlink() or not receipt.is_file() or not intent.is_file():
                continue
            try:
                if Path(json.loads(intent.read_text(encoding='utf-8'))['workspace']).resolve() != workspace.resolve():
                    continue
                value = json.loads(archived.read_text(encoding='utf-8'))
                references = value.get('result', {}).get('skill_references', [])
                recorded = json.loads(receipt.read_text(encoding='utf-8')).get('projection', {}).get('skill_references', [])
                if references and references == recorded:
                    candidates.append((archived, references))
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                continue
        identities = {canonical(references) for _, references in candidates}
        if len(identities) > 1:
            raise EvoError('multiple archived projection owners match the writable slot')
        if not candidates:
            return False
        archived, references = candidates[-1]
        SkillCache(self.project_root, self.state_root).validate_workspace_references(workspace, references, content=True)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archived, manifest)
        return True

    def quarantine(self, workspace: Path, reason: str) -> None:
        meta_path = workspace / '.evo-slot.json'
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        meta.update(state='quarantined', reason=reason[:800])
        meta_path.write_text(canonical(meta) + '\n', encoding='utf-8')

    def release(self, workspace: Path) -> None:
        """Permit reset after a terminal outcome with no live owned process."""
        meta_path = workspace / '.evo-slot.json'
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        meta['state'] = 'reusable'
        meta_path.write_text(canonical(meta) + '\n', encoding='utf-8')

    @staticmethod
    def _digest(path: Path) -> str:
        value = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                value.update(block)
        return value.hexdigest()

    def _inventory(self, workspace: Path) -> dict[str, dict]:
        result = {}
        references = self._managed_skill_references(workspace)
        lexical_references = {Path(reference['link']).absolute(): reference for reference in references}
        for path in workspace.rglob('*'):
            if path.name == '.evo-slot.json':
                continue
            lexical = path.absolute()
            owner = next((link for link in lexical_references if lexical == link or lexical.is_relative_to(link)), None)
            if owner is not None and lexical != owner:
                continue
            if path.is_symlink() or path.is_junction():
                reference = lexical_references.get(lexical)
                if reference is None or path.resolve() != Path(reference['target']).resolve():
                    raise EvoError('writable slot contains an unmanaged link')
                result[path.relative_to(workspace).as_posix()] = {
                    'kind': 'skill-reference', 'identity_sha256': reference['identity_sha256'],
                    'target': reference['target']}
                continue
            if path.is_file():
                result[path.relative_to(workspace).as_posix()] = {
                    'bytes': path.stat().st_size, 'sha256': self._digest(path)}
        return result

    def _archive_and_reset(self, workspace: Path, prior: int, meta: dict, desired: set[str],
                           desired_prefixes: set[str]) -> None:
        current = self._inventory(workspace)
        baseline = meta.get('baseline', {})
        changed = [name for name, value in current.items() if baseline.get(name) != value]
        ordinary_changed = [name for name in changed if current[name].get('kind') != 'skill-reference']
        archive = self.state_root / 'jobs' / f'j{prior}' / 'workspace-diff'
        total = sum(current[name]['bytes'] for name in ordinary_changed)
        if total > 64 * 1024 * 1024:
            self.quarantine(workspace, 'workspace difference exceeds 64 MiB archive bound')
            raise EvoError('workspace difference exceeds archive bound; slot quarantined')
        for name in ordinary_changed:
            source = workspace / Path(name)
            target = archive / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # Preserve unchanged assets selected again. Changed/new outputs are
        # archived, and retired source assets leave the slot.
        retained = lambda name: name in desired or any(name == prefix or name.startswith(prefix + '/') for prefix in desired_prefixes)
        references = self._managed_skill_references(workspace)
        from .skill_cache import SkillCache
        cache = SkillCache(self.project_root, self.state_root) if references else None
        retained_references = []
        for reference in references:
            relative = Path(reference['link']).relative_to(workspace).as_posix()
            if not retained(relative):
                cache.remove_reference(reference)
                current.pop(relative, None)
                baseline.pop(relative, None)
            else:
                retained_references.append(reference)
        if retained_references and len(retained_references) != len(references):
            manifest_path = workspace / '.agentbase' / 'evo-codex-projection.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            removed_links = {
                Path(reference['link']).relative_to(workspace).as_posix()
                for reference in references if reference not in retained_references
            }
            def retained_file(entry: dict) -> bool:
                name = entry.get('path')
                return isinstance(name, str) and not any(
                    name == link or name.startswith(link + '/') for link in removed_links)
            files = [entry for entry in manifest.get('files', []) if retained_file(entry)]
            result = manifest.get('result', {})
            result['files'] = [entry for entry in result.get('files', []) if retained_file(entry)]
            result['skill_files'] = [entry for entry in result.get('skill_files', []) if retained_file(entry)]
            result['skill_references'] = retained_references
            payload = {'schema': 'agentbase.evo-codex-projection/v1', 'files': result['files']}
            result['identity_sha256'] = hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()
            manifest['files'] = files
            manifest_path.write_text(canonical(manifest) + '\n', encoding='utf-8')
        # The projection manifest is the authority that makes retained junctions
        # distinguishable from unknown links during the next baseline inventory.
        # It is still archived as changed evidence, but must live as long as all
        # of the references it identifies are retained.
        projection_owner = '.agentbase/evo-codex-projection.json'
        preserved_owner = projection_owner if retained_references else None
        remove = (set(ordinary_changed) | {name for name in baseline if not retained(name)})
        if preserved_owner is not None:
            remove.discard(preserved_owner)
        for name in sorted(remove, key=lambda value: len(Path(value).parts), reverse=True):
            path = workspace / Path(name)
            if path.is_file():
                path.unlink()
        retained_links = {Path(reference['link']).absolute() for reference in retained_references}
        for path in sorted((p for p in workspace.rglob('*') if p.is_dir()
                            and not p.is_junction()
                            and not any(p.absolute().is_relative_to(link) for link in retained_links)),
                           key=lambda value: len(value.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
