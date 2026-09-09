from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evaluation_core import sha256_file
from evo import cli
from evo.selection import build_plan
from evo.spec import EvoError, load_spec
from evo.swe_catalog import import_corpus, load_catalog
from evo.view import model_text_cost, render_model


class SweCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.corpus_path = EVALUATION_ROOT / 'tests/fixtures/synthetic-corpus.json'
        self.template = load_spec(EVALUATION_ROOT / 'tests/fixtures/evo/research-v1.json')
        self.corpus = json.loads(self.corpus_path.read_text(encoding='utf-8'))
        self.catalog_path = self.root / 'catalog.json'
        self.catalog = import_corpus(self.corpus_path)
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')

    def research(self):
        spec = copy.deepcopy(self.template)
        spec['evaluations'] = {'catalog': {'source': 'catalog.json', 'sha256': sha256_file(self.catalog_path)}}
        spec['selection']['groups'] = list(self.corpus['suites'])
        spec['runtime'] = {'adapter': 'codex', 'model': 'explicit-research-model', 'reasoning_effort': 'low',
                           'swe': {'corpus': str(self.corpus_path), 'state_root': str(self.root / 'state'), 'work_root': str(self.root / 'work'),
                                   'work_reservation_mb': 100}}
        path = self.root / 'research.json'
        path.write_text(json.dumps(spec), encoding='utf-8')
        return path

    def test_catalog_contains_only_tasks_groups_and_provenance(self):
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            catalog = import_corpus(self.corpus_path)
        self.assertEqual(set(catalog), {'schema', 'id', 'version', 'source', 'items', 'groups'})
        self.assertEqual([i['id'] for i in catalog['items']], [t['id'] for t in self.corpus['tasks']])
        self.assertEqual({g['id']: g['items'] for g in catalog['groups']}, self.corpus['suites'])
        serialized = json.dumps(catalog)
        for forbidden in ('reasoning_effort', '"model"', '"profile"', '"runtime"', '"components"', '"active"', '"budget"', '"observations"'):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse((self.root / 'state').exists())
        self.assertNotIn(str(self.corpus_path), serialized)

    def test_research_supplies_model_environment_selection_and_components(self):
        path = self.research()
        before = path.read_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            spec = load_spec(path)
        plan = build_plan(spec)
        expected = len({task for group in self.corpus['suites'].values() for task in group})
        self.assertEqual(plan['job_count'], expected * len(self.template['combinations']))
        self.assertEqual(spec['runtime']['model'], 'explicit-research-model')
        self.assertEqual(spec['components'], self.template['components'])
        self.assertEqual(spec['scoring'], self.template['scoring'])
        for item in spec['evaluations']['items']:
            self.assertEqual(item['runtime']['swe']['task'], item['id'])
            self.assertEqual(item['runtime']['swe']['state_root'], str(self.root / 'state'))
            self.assertNotIn('model', item['runtime'])
        self.assertEqual(path.read_bytes(), before)

    def test_standalone_catalog_validation_needs_no_host_corpus_or_model(self):
        with patch('evo.swe_catalog.import_corpus', side_effect=AssertionError('must not resolve a host corpus')):
            self.assertEqual(load_catalog(self.catalog_path), self.catalog)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['validate', '--spec', str(self.catalog_path)]), 0)
        self.catalog['runtime'] = {'model': 'forbidden'}
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'outside the task contract'):
            load_catalog(self.catalog_path)

    def test_offline_research_plans_without_model_or_runtime_environment(self):
        path = self.research()
        value = json.loads(path.read_text(encoding='utf-8'))
        del value['runtime']
        path.write_text(json.dumps(value), encoding='utf-8')
        with patch('evo.swe_catalog.import_corpus', side_effect=AssertionError('offline must not resolve a corpus')):
            spec = load_spec(path)
            self.assertNotIn('runtime', spec)
            self.assertGreater(build_plan(spec)['job_count'], 0)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['plan', '--spec', str(path)]), 0)

    def test_catalog_change_and_mixed_inline_authority_are_rejected(self):
        path = self.research()
        self.catalog_path.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'catalog changed'):
            load_spec(path)
        value = json.loads(path.read_text(encoding='utf-8'))
        value['evaluations']['items'] = []
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'cannot coexist'):
            load_spec(path)

    def test_generated_catalog_cannot_be_edited_into_a_second_task_authority(self):
        self.catalog['groups'][0]['items'] = []
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'stale or edited'):
            load_catalog(self.catalog_path, corpus_path=self.corpus_path)

    def test_cli_writes_task_catalog_once_without_queue_or_execution(self):
        output = self.root / 'imported.json'
        argv = ['swe-import', '--corpus', str(self.corpus_path), '--output', str(output)]
        with contextlib.redirect_stdout(io.StringIO()) as out, patch('subprocess.Popen', side_effect=AssertionError('must not run')):
            self.assertEqual(cli.main(argv), 0)
        summary = json.loads(out.getvalue())
        self.assertFalse(summary['queued'])
        self.assertFalse(summary['executed'])
        self.assertEqual(load_catalog(output), self.catalog)
        original = output.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(argv), 2)
        self.assertEqual(output.read_bytes(), original)

    def test_model_summary_preserves_no_run_decision_with_bounded_groups(self):
        value = {'schema': 'agentbase-evo-swe-import/v1', 'id': 'synthetic', 'output': 'local.json',
                 'item_count': 400, 'queued': False, 'executed': False,
                 'groups': [{'id': str(i), 'items': 1} for i in range(400)]}
        rendered = render_model(value, 500)
        summary = json.loads(rendered)
        self.assertLessEqual(model_text_cost(rendered), 500)
        self.assertFalse(summary['executed'])
        self.assertGreater(summary['omitted_groups'], 0)


if __name__ == '__main__':
    unittest.main()
