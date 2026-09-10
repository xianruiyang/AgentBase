from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALUATION_ROOT.parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.skill_cache import CACHE_SCHEMA, SkillCache, _bundle_identity, _manage, payload_manifest
from evo.env_pool import EnvironmentPool
from evo.swe_adapter import cleanup_job
from evo.cli import main
import agentbase_codex


class EvoSkillCacheTests(unittest.TestCase):
    def test_cache_lock_waits_for_same_bundle_instead_of_failing_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'; state.mkdir()
            first = SkillCache(PROJECT_ROOT, state, wait_seconds=5)
            second = SkillCache(PROJECT_ROOT, state, wait_seconds=5)
            entered, release = threading.Event(), threading.Event()
            def hold():
                with first._lock('a' * 64):
                    entered.set(); release.wait(3)
            with ThreadPoolExecutor(max_workers=2) as pool:
                owner = pool.submit(hold); self.assertTrue(entered.wait(2))
                context = second._lock('a' * 64)
                started = time.monotonic(); waiter = pool.submit(context.__enter__)
                time.sleep(.2); self.assertFalse(waiter.done()); release.set(); owner.result()
                waiter.result(); self.assertGreaterEqual(time.monotonic() - started, .2)
                context.__exit__(None, None, None)

    def test_staging_recovery_uses_early_intent_and_waits_for_bundle_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'sample-skill'; source.mkdir()
            (source / 'SKILL.md').write_text('# Sample\n', encoding='utf-8')
            skills = {'sample-skill': payload_manifest(PROJECT_ROOT, source)}
            identity = _bundle_identity(skills); alias = 'v-' + identity[:12]
            cache = SkillCache(PROJECT_ROOT, root / 'state', wait_seconds=5); cache._initialize()
            stage = cache.staging / f'{alias}.999999'; stage.mkdir()
            (stage / 'recovery.json').write_text(json.dumps({
                'schema': CACHE_SCHEMA, 'identity_sha256': identity,
                'version_alias': alias, 'skills': skills,
            }), encoding='utf-8')
            (stage / 'payload').mkdir(); (stage / 'payload' / 'partial.tmp').write_text('partial')
            entered, release = threading.Event(), threading.Event()
            def hold():
                with cache._lock(identity):
                    entered.set(); release.wait(3)
            with ThreadPoolExecutor(max_workers=2) as pool:
                owner = pool.submit(hold); self.assertTrue(entered.wait(2))
                waiter = pool.submit(cache.recover_staging, alias)
                time.sleep(.2); self.assertFalse(waiter.done())
                release.set(); owner.result(); self.assertEqual(waiter.result(), identity)
            self.assertFalse(stage.exists())

    def test_filtered_payload_is_content_addressed_reused_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sample-skill'
            (source / 'references').mkdir(parents=True)
            (source / 'tests').mkdir()
            (source / 'SKILL.md').write_text('# Sample\n', encoding='utf-8')
            (source / 'references' / 'fact.md').write_text('one\n', encoding='utf-8')
            (source / 'tests' / 'ignored.py').write_text('raise AssertionError\n', encoding='utf-8')
            manifest = payload_manifest(PROJECT_ROOT, source)
            self.assertEqual({row['path'] for row in manifest['files']}, {'SKILL.md', 'references/fact.md'})
            cache = SkillCache(PROJECT_ROOT, root / 'state')
            first = cache.materialize_bundle({'sample-skill': source})
            second = cache.materialize_bundle({'sample-skill': source})
            self.assertEqual((first['disposition'], second['disposition']), ('created', 'reused'))
            self.assertEqual(first['payload'], second['payload'])
            self.assertFalse((Path(first['payload']) / 'sample-skill' / 'tests').exists())
            (source / 'references' / 'fact.md').write_text('two\n', encoding='utf-8')
            changed = cache.materialize_bundle({'sample-skill': source})
            self.assertNotEqual(changed['identity_sha256'], first['identity_sha256'])
            self.assertEqual((Path(first['payload']) / 'sample-skill' / 'references' / 'fact.md').read_text(encoding='utf-8'), 'one\n')
            self.assertEqual(json.loads((cache.root / 'owner.json').read_text(encoding='utf-8'))['schema'],
                             'agentbase-evo-skill-cache/v1')
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['skill-cache-status', '--project-root', str(PROJECT_ROOT),
                                       '--state-root', str(root / 'state')]), 0)
            self.assertEqual(len(json.loads(output.getvalue())['versions']), 2)
            for version in (changed['version_alias'], first['version_alias']):
                with redirect_stdout(StringIO()):
                    self.assertEqual(main(['skill-cache-prune', '--project-root', str(PROJECT_ROOT),
                                           '--state-root', str(root / 'state'), '--version', version]), 0)

    def test_projection_shares_one_fixed_skill_version_across_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'candidate' / 'sample-skill'; source.mkdir(parents=True)
            peer = root / 'candidate' / 'peer-skill'; peer.mkdir(parents=True)
            (source / 'references').mkdir(); (peer / 'references').mkdir()
            (source / 'SKILL.md').write_text('# Shared\nvalue one\n', encoding='utf-8')
            (source / 'references' / 'link.md').write_text('../../peer-skill/references/fact.md', encoding='utf-8')
            (peer / 'SKILL.md').write_text('# Peer\n', encoding='utf-8')
            (peer / 'references' / 'fact.md').write_text('peer fact\n', encoding='utf-8')
            state = root / 'state'; cache_root = state / 'skill-cache'
            state.mkdir()
            pool = EnvironmentPool(root / 'work', state, PROJECT_ROOT)
            jobs = [{'id': number, 'identity': f'job-{number}', 'attempt_seq': 1} for number in range(1, 6)]
            workspaces = [pool.acquire(index, jobs[index - 1], set()) for index in (1, 2)]
            selected = {'skills': [{'id': 'stable-skill-id', 'source': str(source)},
                                   {'id': 'stable-peer-id', 'source': str(peer)}]}
            projections = [agentbase_codex.stage_codex_component_projection(
                project_root=PROJECT_ROOT, workspace=workspace, selected=selected,
                candidate_source_roots=[source.parent], skill_cache_root=cache_root)
                for workspace in workspaces]
            for index, workspace in enumerate(workspaces):
                pool.record_baseline(workspace, jobs[index])
                pool.release(workspace)
            first_ref, second_ref = (next(ref for ref in projection['skill_references'] if ref['name'] == 'sample-skill')
                                     for projection in projections)
            self.assertEqual(first_ref['identity_sha256'], second_ref['identity_sha256'])
            self.assertEqual(Path(first_ref['target']).parent, Path(second_ref['target']).parent)
            self.assertTrue((workspaces[0] / '.agents' / 'skills' / 'sample-skill').is_junction())
            self.assertIn('value one', (workspaces[1] / '.agents' / 'skills' / 'sample-skill' / 'SKILL.md').read_text())
            link_text = (workspaces[0] / '.agents' / 'skills' / 'sample-skill' / 'references' / 'link.md').read_text()
            linked = (workspaces[0] / '.agents' / 'skills' / 'sample-skill' / 'references' / link_text).resolve()
            self.assertEqual(linked.read_text(encoding='utf-8'), 'peer fact\n')
            self.assertNotIn(first_ref['identity_sha256'], first_ref['target'])
            cache = SkillCache(PROJECT_ROOT, state)
            extra = workspaces[0] / '.agents' / 'skills' / 'unregistered'
            extra.mkdir()
            with self.assertRaisesRegex(Exception, 'unregistered entry'):
                agentbase_codex.stage_codex_component_projection(
                    project_root=PROJECT_ROOT, workspace=workspaces[0], selected=selected,
                    candidate_source_roots=[source.parent], skill_cache_root=cache_root)
            extra.rmdir()
            first_registry = cache.versions / first_ref['version_alias'] / 'references' / f"{first_ref['reference_id']}.json"
            first_registry.unlink()
            bundle = cache.materialize_bundle({'sample-skill': source, 'peer-skill': peer})
            cache.create_reference(workspaces[0], 'sample-skill', bundle)
            link = Path(first_ref['link']); link.rmdir()
            cache.create_reference(workspaces[0], 'sample-skill', bundle)
            (source / 'SKILL.md').write_text('# Shared\nvalue two\n', encoding='utf-8')
            workspaces[0] = pool.acquire(1, jobs[2], set(), set(projections[0]['managed_paths']))
            changed = agentbase_codex.stage_codex_component_projection(
                project_root=PROJECT_ROOT, workspace=workspaces[0], selected=selected,
                candidate_source_roots=[source.parent], skill_cache_root=cache_root)
            changed_ref = next(ref for ref in changed['skill_references'] if ref['name'] == 'sample-skill')
            self.assertNotEqual(changed_ref['identity_sha256'], second_ref['identity_sha256'])
            self.assertIn('value one', (workspaces[1] / '.agents' / 'skills' / 'sample-skill' / 'SKILL.md').read_text())
            self.assertIn('value two', (workspaces[0] / '.agents' / 'skills' / 'sample-skill' / 'SKILL.md').read_text())
            pool.record_baseline(workspaces[0], jobs[2]); pool.release(workspaces[0])
            reused = pool.acquire(1, jobs[3], set(), {'.agents/skills'})
            pool.record_baseline(reused, jobs[3])
            pool.release(reused)
            pool.acquire(1, {'id': 6, 'identity': 'job-6', 'attempt_seq': 1}, set())
            pool.acquire(2, jobs[4], set())
            old_version = cache.versions / second_ref['version_alias']
            old_manifest = json.loads((old_version / 'manifest.json').read_text(encoding='utf-8'))
            _manage(PROJECT_ROOT, 'Restore', old_version / 'payload', sddl=old_manifest['restore_sddl'])
            (old_version / 'payload' / 'tests').mkdir()
            (old_version / 'payload' / 'tests' / 'injected.py').write_text('excluded but physical\n', encoding='utf-8')
            _manage(PROJECT_ROOT, 'Protect', old_version / 'payload')
            with self.assertRaisesRegex(Exception, 'changed after publication'):
                cache.status()
            cache.remove_unreferenced_version(second_ref['identity_sha256'])
            self.assertTrue(Path(changed_ref['target']).is_dir())
            cache.remove_unreferenced_version(changed_ref['identity_sha256'])

    def test_slot_reuse_updates_projection_owner_when_only_one_skill_reference_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); candidate = root / 'candidate'
            first, second = candidate / 'first-skill', candidate / 'second-skill'
            first.mkdir(parents=True); second.mkdir(parents=True)
            (first / 'SKILL.md').write_text('# First\n', encoding='utf-8')
            (second / 'SKILL.md').write_text('# Second\n', encoding='utf-8')
            state, work = root / 'state', root / 'work'; state.mkdir()
            pool = EnvironmentPool(work, state, PROJECT_ROOT)
            jobs = [{'id': number, 'identity': f'job-{number}', 'attempt_seq': 1} for number in (1, 2)]
            workspace = pool.acquire(1, jobs[0], set())
            projection = agentbase_codex.stage_codex_component_projection(
                project_root=PROJECT_ROOT, workspace=workspace,
                selected={'skills': [{'id': 'first', 'source': str(first)}, {'id': 'second', 'source': str(second)}]},
                candidate_source_roots=[candidate], skill_cache_root=state / 'skill-cache')
            pool.record_baseline(workspace, jobs[0]); pool.release(workspace)
            retained_link = '.agents/skills/first-skill'
            reused = pool.acquire(1, jobs[1], set(), {retained_link})
            pool.record_baseline(reused, jobs[1])
            manifest = json.loads((reused / '.agentbase' / 'evo-codex-projection.json').read_text(encoding='utf-8'))
            references = manifest['result']['skill_references']
            self.assertEqual([Path(reference['link']).name for reference in references], ['first-skill'])
            self.assertTrue((reused / retained_link).is_junction())
            self.assertFalse((reused / '.agents' / 'skills' / 'second-skill').exists())
            self.assertFalse(any(entry['path'].startswith('.agents/skills/second-skill/')
                                 for entry in manifest['result']['files']))
            cache = SkillCache(PROJECT_ROOT, state)
            for reference in references:
                cache.remove_reference(reference)
            cache.remove_unreferenced_version(projection['skill_references'][0]['identity_sha256'])

    def test_archived_projection_owner_recovers_real_junction_before_slot_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'candidate' / 'sample-skill'; source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('# Shared\n', encoding='utf-8')
            state, work = root / 'state', root / 'work'; state.mkdir()
            pool = EnvironmentPool(work, state, PROJECT_ROOT)
            job = {'id': 1, 'identity': 'job-1', 'attempt_seq': 1}
            workspace = pool.acquire(1, job, set())
            projection = agentbase_codex.stage_codex_component_projection(
                project_root=PROJECT_ROOT, workspace=workspace,
                selected={'skills': [{'id': 'stable', 'source': str(source)}]},
                candidate_source_roots=[source.parent], skill_cache_root=state / 'skill-cache')
            pool.record_baseline(workspace, job)
            attempt = state / 'jobs' / 'j1'; (attempt / 'workspace-diff' / '.agentbase').mkdir(parents=True)
            manifest = workspace / '.agentbase' / 'evo-codex-projection.json'
            shutil.copy2(manifest, attempt / 'workspace-diff' / '.agentbase' / manifest.name)
            (attempt / 'intent.json').write_text(json.dumps({'workspace': str(workspace)}), encoding='utf-8')
            (attempt / 'receipt.json').write_text(json.dumps({'projection': projection}), encoding='utf-8')
            manifest.unlink()
            self.assertTrue((workspace / '.agents' / 'skills' / 'sample-skill').is_junction())
            with self.assertRaisesRegex(Exception, 'unmanaged link'):
                pool.record_baseline(workspace, job)
            self.assertTrue(pool.restore_projection_owner(workspace))
            pool.record_baseline(workspace, job)
            self.assertFalse(pool.restore_projection_owner(workspace))
            cache = SkillCache(PROJECT_ROOT, state)
            for reference in projection['skill_references']:
                cache.remove_reference(reference)
            cache.remove_unreferenced_version(projection['skill_references'][0]['identity_sha256'])

    def test_swe_cleanup_detaches_reference_without_deleting_shared_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'candidate' / 'sample-skill'; source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('# Shared\n', encoding='utf-8')
            state, work, attempt = root / 'state', root / 'swe-work', root / 'attempt'
            state.mkdir(); work.mkdir(); attempt.mkdir()
            workspace = work / 'evo' / 'owner' / 'study' / 'job'; workspace.mkdir(parents=True)
            projection = agentbase_codex.stage_codex_component_projection(
                project_root=PROJECT_ROOT, workspace=workspace,
                selected={'skills': [{'id': 'stable', 'source': str(source)}]},
                candidate_source_roots=[source.parent], skill_cache_root=state / 'skill-cache')
            target = Path(projection['skill_references'][0]['target'])
            (attempt / 'swe-state.json').write_text(json.dumps({'workspace': str(workspace)}), encoding='utf-8')
            result = cleanup_job({'swe': {'work_root': str(work)}}, attempt,
                                 project_root=PROJECT_ROOT, evo_state_root=state)
            self.assertEqual(result, {'removed': True})
            self.assertFalse(workspace.exists()); self.assertTrue(target.is_dir())
            cache = SkillCache(PROJECT_ROOT, state)
            cache.remove_unreferenced_version(projection['skill_references'][0]['identity_sha256'])

    def test_cache_root_reparse_chain_is_rejected_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); real = root / 'real-state'; real.mkdir()
            link = root / 'linked-state'
            made = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(real)],
                                  capture_output=True, text=True)
            if made.returncode != 0:
                self.skipTest('junction fixture unavailable')
            try:
                with self.assertRaisesRegex(Exception, 'must not traverse a reparse point'):
                    SkillCache(PROJECT_ROOT, link)
            finally:
                link.rmdir()


if __name__ == '__main__':
    unittest.main()
