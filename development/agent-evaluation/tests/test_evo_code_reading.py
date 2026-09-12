from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.cli import main
from evo.code_reading_adapter import answer_schema, score_answer, subject_prompt, validate_binding
from evo.code_reading_catalog import import_catalog, snapshot_inventory
from evo.runtime import artifacts, recover, run, submit
from evo.scoring import score_artifacts
from evo.spec import EvoError, load_spec
from evo.store import Store


class EvoCodeReadingTests(unittest.TestCase):
    def test_compact_transport_rejects_paths_in_coordinate_slots(self) -> None:
        # A real answer put its group path in at as well as in path. Prevent
        # this transport-valid / grader-invalid mismatch before generation.
        for answer_format, key in (('file-groups-v1', 'at'), ('file-notes-v1', 'entries')):
            entry = answer_schema(answer_format)['properties']['files']['items']['properties'][key]['items']
            coordinate = entry['properties']['at'] if key == 'entries' else entry
            for valid in ('file', '1', '38-71'):
                self.assertIsNotNone(re.fullmatch(coordinate['pattern'], valid))
            for invalid in ('src/handler.ts', '', '0', '-1', '1:2', '01', '1\n'):
                self.assertIsNone(re.fullmatch(coordinate['pattern'], invalid))

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'project'
        self.snapshot_root = self.project / 'local' / 'workspaces'
        self.workspace = self.snapshot_root / 'sample'
        self.workspace.mkdir(parents=True)
        (self.workspace / 'src').mkdir()
        (self.workspace / 'src' / 'value.py').write_text('def value():\n    return 1\n', encoding='utf-8')
        self.source = self.root / 'questions.json'
        self.source.write_text(json.dumps({
            'schema': 'agentbase.code-reading-source/v1', 'id': 'synthetic-reading', 'version': '1',
            'items': [{'id': 'find-value', 'family': 'python', 'workspace': 'sample',
                       'prompt': 'Locate value.', 'answer_max_lines': 3,
                       'required_locations': [
                           {'path': 'src/value.py'}, {'path': 'src/value.py', 'line': 1},
                           {'path': 'src/value.py', 'start_line': 1, 'end_line': 2}],
                       'supporting': ['value returns one']}],
            'groups': [{'id': 'all', 'items': ['find-value']}],
        }), encoding='utf-8')

    def _catalog(self) -> Path:
        path = self.root / 'catalog.json'
        value = import_catalog(self.source, self.snapshot_root)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def _spec(self, catalog: Path) -> tuple[Path, dict]:
        digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
        spec = {
            'schema': 'agentbase-evo-research/v1', 'id': 'reading-run', 'version': '1',
            'components': {kind: [] for kind in ('agents_md', 'skills', 'hooks', 'mcp', 'tools', 'agents', 'codex_settings')},
            'combinations': [{'id': 'empty', 'members': {}}],
            'runtime': {'adapter': 'codex', 'model': 'synthetic', 'reasoning_effort': 'low',
                        'max_agents': 1, 'token_reservation': 100,
                        'code_reading': {'snapshot_root': str(self.snapshot_root)}},
            'evaluations': {'catalog': {'source': str(catalog), 'sha256': digest},
                            'observations': ['quality.required_found', 'quality.required_total',
                                             'quality.extra_locations', 'quality.passed', 'quality.reward']},
            'fields': [
                {'id': 'quality.required_found', 'type': 'integer', 'unit': 'count', 'grain': 'attempt', 'source': 'location grader'},
                {'id': 'quality.required_total', 'type': 'integer', 'unit': 'count', 'grain': 'attempt', 'source': 'location grader'},
                {'id': 'quality.extra_locations', 'type': 'integer', 'unit': 'count', 'grain': 'attempt', 'source': 'location grader'},
                {'id': 'quality.passed', 'type': 'boolean', 'unit': 'flag', 'grain': 'attempt', 'source': 'location grader'},
                {'id': 'quality.reward', 'type': 'number', 'unit': 'ratio', 'grain': 'attempt', 'source': 'location grader'},
            ],
            'scoring': [{'id': 'quality', 'version': '1', 'metrics': [
                {'id': 'reward', 'unit': 'ratio', 'expression': {'aggregate': 'mean', 'field': 'quality.reward'}}]}],
            'selection': {'combinations': ['empty'], 'groups': ['all'], 'replicates': 1},
            'budget': {'concurrency': 1, 'max_tokens': 1000},
        }
        path = self.project / 'research.json'
        path.write_text(json.dumps(spec), encoding='utf-8')
        return path, spec

    def test_import_validate_and_plan_one_frozen_snapshot(self) -> None:
        catalog = self.root / 'catalog.json'
        imported = StringIO()
        with redirect_stdout(imported):
            self.assertEqual(main(['code-reading-import', '--source', str(self.source), '--snapshot-root',
                                   str(self.snapshot_root), '--output', str(catalog)]), 0)
        projection = json.loads(imported.getvalue())
        self.assertEqual((projection['operation'], projection['item_count'], projection['required_locations']),
                         ('code-reading-import', 1, 3))
        spec_path, _ = self._spec(catalog)
        self.assertEqual(main(['validate', '--spec', str(spec_path), '--view', 'machine']), 0)
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['plan', '--spec', str(spec_path), '--view', 'machine']), 0)
        self.assertEqual(len(json.loads(output.getvalue())['jobs']), 1)
        loaded = load_spec(spec_path)
        self.assertEqual(loaded['evaluations']['items'][0]['required_locations'][0], {'path': 'src/value.py'})

    def test_queue_stub_transport_uses_real_location_grader_and_score(self) -> None:
        self._check_transport('flat-v1')

    def test_grouped_transport_uses_selected_prompt_schema_and_same_grader(self) -> None:
        self._check_transport('file-groups-v1')

    def test_noted_transport_uses_selected_prompt_schema_and_same_grader(self) -> None:
        self._check_transport('file-notes-v1')

    def test_path_tree_transport_uses_selected_prompt_schema_and_same_grader(self) -> None:
        self._check_transport('path-tree-v1')

    def test_subject_prompt_preserves_format_specific_explanation_contract(self) -> None:
        task_prompt = (
            'Locate value.py and explain the source relationship, exact condition, affected object, '
            'and result. Include the requested explanation.'
        )
        item = {'prompt': task_prompt}
        old_tail = 'Paths are relative to the frozen snapshot root. Optional explanation text belongs in a top-level explanation string.'
        binding = {'snapshot_root': str(self.snapshot_root), 'workspace': 'sample'}
        prompts = {}
        for answer_format in ('flat-v1', 'file-groups-v1', 'file-notes-v1', 'path-tree-v1'):
            with self.subTest(answer_format=answer_format):
                current = {**binding, 'answer_format': answer_format}
                rendered = subject_prompt(item, current)
                prompts[answer_format] = rendered
                self.assertIn(task_prompt, rendered)
                self.assertIn('Read the frozen source snapshot at this absolute path:', rendered)

        self.assertTrue(prompts['flat-v1'].endswith(old_tail))
        self.assertTrue(prompts['file-groups-v1'].endswith(old_tail))
        for answer_format in ('file-notes-v1', 'path-tree-v1'):
            self.assertNotIn(old_tail, prompts[answer_format])
            # The final mapping must agree with the selected containers, without
            # freezing all wording of the model-facing instructions.
            tail = prompts[answer_format].rsplit('Paths are relative to the frozen snapshot root.', 1)[1]
            self.assertIn('adjacent', tail)
            self.assertIn('explanation', tail)
            self.assertIn('shared scope', tail)
        self.assertIn('with a tree string and an explanation string', prompts['path-tree-v1'])
        self.assertIn('with a files array', prompts['file-notes-v1'])

    def _check_transport(self, answer_format: str) -> None:
        catalog = self._catalog()
        spec_path, spec = self._spec(catalog)
        if answer_format != 'flat-v1':
            spec['runtime']['code_reading']['answer_format'] = answer_format
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
        state, work, codex = self.root / 'state', self.root / 'work', self.root / 'codex'
        codex.mkdir(); (codex / 'auth.json').write_text('{}', encoding='utf-8')
        store = Store(state); store.initialize(concurrency=1, model_capacity=1, max_disk_mb=64, min_free_mb=1)
        study = submit(store, spec_path, self.project, work)
        def transport(**kwargs):
            selected = next(item for item in kwargs['spec']['evaluations']['items'] if item['id'] == 'find-value')
            self.assertIn(str(self.workspace.resolve()), selected['prompt'])
            self.assertIn('Return exactly one JSON object', selected['prompt'])
            expected_prompt = {
                'flat-v1': 'with a locations array',
                'file-groups-v1': 'with a files array',
                'file-notes-v1': 'with a files array',
                'path-tree-v1': 'with a tree string',
            }[answer_format]
            self.assertIn(expected_prompt, selected['prompt'])
            self.assertEqual(kwargs['output_schema'], answer_schema(answer_format))
            logs = kwargs['attempt_root'] / 'codex-logs'; logs.mkdir(parents=True)
            answer = {'locations': [
                {'path': 'src/value.py'}, {'path': 'src/value.py', 'line': 1},
                {'path': 'src/value.py', 'start_line': 1, 'end_line': 2}]}
            if answer_format == 'file-groups-v1':
                answer = {'files': [{'path': 'src/value.py', 'at': ['file', '1', '1-2']}]}
            elif answer_format == 'file-notes-v1':
                answer = {'files': [{'path': 'src/value.py', 'entries': [
                    {'at': at, 'note': 'source fact'} for at in ('file', '1', '1-2')]}]}
            elif answer_format == 'path-tree-v1':
                answer = {'tree': 'src/\n  value.py  file,1,1-2\n    > source fact', 'explanation': ''}
            (logs / 'last-message.txt').write_text(json.dumps(answer), encoding='utf-8')
            raw = {'schema': 'agentbase.evo-codex-run/v1', 'status': 'completed', 'model_invoked': True,
                   'duration_seconds': .1, 'usage': {'total_tokens': 7}, 'usage_complete': True}
            return {'status': 'completed', 'model_invoked': True, 'raw_receipt': raw,
                    'trace': {'schema': 'agentbase.evo-codex-trace/v1'}, 'projection': {}}
        with mock.patch.dict(os.environ, {'AGENT_EVALUATION_DISABLE_MODEL': '0',
                                          'AGENTBASE_AGENT_EVALUATOR_DISABLED': '0'}), \
                mock.patch('evo.codex_adapter.run_codex_job', side_effect=transport):
            status = run(store, study=study, installed_codex_root=codex)
        self.assertEqual(status['counts'], {'completed': 1})
        facts = artifacts(store, study)
        self.assertEqual(facts['rows'][0]['values']['quality.required_found'], 3)
        self.assertEqual(facts['rows'][0]['values']['quality.extra_locations'], 0)
        self.assertTrue(facts['rows'][0]['values']['quality.passed'])
        self.assertEqual(facts['rows'][0]['values']['quality.reward'], 1)
        score = score_artifacts(load_spec(spec_path), facts)
        self.assertEqual(score['scores'][0]['groups'][0]['metrics'][0]['value'], 1)

    def test_codex_adapter_persists_the_selected_task_prompt(self) -> None:
        from evo import codex_adapter
        workspace, attempt, codex = self.root / 'slot', self.root / 'attempt', self.root / 'installed'
        for path in (workspace, attempt, codex):
            path.mkdir()
        (codex / 'auth.json').write_text('{}', encoding='utf-8')
        executable = self.root / 'codex.exe'; executable.write_bytes(b'fixture')
        prompt = 'read frozen snapshot and return strict JSON'
        spec = {'runtime': {'adapter': 'codex', 'model': 'synthetic', 'reasoning_effort': 'low'},
                'components': {}, 'combinations': [{'id': 'empty', 'members': {}}],
                'evaluations': {'items': [{'id': 'reading', 'prompt': prompt,
                                           'runtime': {'prompt': 'must not win'}}]}}
        raw = {'schema': 'agentbase.evo-codex-run/v1', 'status': 'completed', 'model_invoked': True,
               'usage': {'total_tokens': 1}, 'usage_complete': True}
        class Process:
            returncode = 0
            def poll(self): return 0
        def start(argv, **_kwargs):
            schema_path = Path(argv[argv.index('-OutputSchemaPath') + 1])
            self.assertEqual(schema_path, attempt / 'candidate-output-schema.json')
            self.assertEqual(json.loads(schema_path.read_text(encoding='utf-8')), answer_schema())
            (attempt / 'codex-result.json').write_text(json.dumps(raw), encoding='utf-8')
            return Process()
        with (mock.patch.dict(os.environ, {'AGENTBASE_AGENT_EVALUATOR_DISABLED': '0'}),
              mock.patch.object(codex_adapter.agentbase_codex, 'stage_codex_component_projection',
                                return_value={'hooks_enabled': False, 'tool_paths': []}),
              mock.patch.object(codex_adapter, '_codex_preflight', return_value={}),
              mock.patch.object(codex_adapter.agentbase_codex, 'candidate_rollout_snapshot', return_value={}),
              mock.patch.object(codex_adapter, 'recover_codex_artifacts',
                                return_value={'raw_receipt': raw, 'trace': {}}),
              mock.patch.object(codex_adapter.subprocess, 'Popen', side_effect=start)):
            result = codex_adapter.run_codex_job(
                project_root=self.project, workspace=workspace, attempt_root=attempt,
                installed_codex_root=codex, spec=spec, job={'combination': 'empty', 'item': 'reading'},
                process_environment={'AGENTBASE_CODEX_EXECUTABLE_PATH': str(executable)}, timeout_seconds=60,
                output_schema=answer_schema())
        self.assertEqual(result['status'], 'completed')
        self.assertEqual((attempt / 'candidate-prompt.txt').read_text(encoding='utf-8'), prompt)

    def test_completed_raw_recovers_answer_without_calling_model(self) -> None:
        self._check_recover('flat-v1')

    def test_grouped_recovery_uses_frozen_format_without_calling_model(self) -> None:
        self._check_recover('file-groups-v1')

    def test_noted_recovery_uses_frozen_format_without_calling_model(self) -> None:
        self._check_recover('file-notes-v1')

    def test_path_tree_recovery_uses_frozen_format_without_calling_model(self) -> None:
        self._check_recover('path-tree-v1')

    def _check_recover(self, answer_format: str) -> None:
        catalog = self._catalog(); spec_path, spec = self._spec(catalog)
        spec['runtime']['code_reading']['answer_format'] = answer_format
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        store = Store(self.root / 'state')
        store.initialize(concurrency=1, model_capacity=1, max_disk_mb=64, min_free_mb=1)
        study = submit(store, spec_path, self.project, self.root / 'work')
        # Edits to the research file must not change an already submitted job.
        spec['runtime']['code_reading']['answer_format'] = 'flat-v1'
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        job = store.claim(study); self.assertIsNotNone(job)
        attempt = store.root / 'jobs' / f"j{job['id']}"
        store.phase(job['id'], 'running')
        (attempt / 'codex-logs').mkdir(parents=True)
        answer = {'locations': [
            {'path': 'src/value.py'}, {'path': 'src/value.py', 'line': 1},
            {'path': 'src/value.py', 'start_line': 1, 'end_line': 2}]}
        if answer_format == 'file-groups-v1':
            answer = {'files': [{'path': 'src/value.py', 'at': ['file', '1', '1-2']}]}
        elif answer_format == 'file-notes-v1':
            answer = {'files': [{'path': 'src/value.py', 'entries': [
                {'at': at, 'note': 'source fact'} for at in ('file', '1', '1-2')]}]}
        elif answer_format == 'path-tree-v1':
            answer = {'tree': 'src/\n  value.py  file,1,1-2\n    > source fact', 'explanation': ''}
        (attempt / 'codex-logs' / 'last-message.txt').write_text(json.dumps(answer), encoding='utf-8')
        raw = {'schema': 'agentbase.evo-codex-run/v1', 'status': 'completed', 'model_invoked': True,
               'duration_seconds': .1, 'usage': {'total_tokens': 9}, 'usage_complete': True}
        (attempt / 'codex-result.json').write_text(json.dumps(raw), encoding='utf-8')
        with mock.patch('evo.codex_adapter.run_codex_job', side_effect=AssertionError('model rerun')) as launch:
            result = recover(store, study)
        launch.assert_not_called()
        self.assertEqual(result['counts'], {'completed': 1})
        self.assertEqual(store.jobs(study)[0]['usage'], 9)
        self.assertTrue(artifacts(store, study)['rows'][0]['values']['quality.passed'])

    def test_grouped_grammar_preserves_exact_scoring_and_rejects_invalid_coordinates(self) -> None:
        item = {'required_locations': [{'path': 'a.py'}, {'path': 'a.py', 'line': 2},
                                       {'path': 'b.py', 'start_line': 3, 'end_line': 5}]}
        flat = {'locations': item['required_locations'] + [{'path': 'a.py'}, {'path': 'other.py', 'line': 9}]}
        grouped = {'files': [{'path': 'a.py', 'at': ['file', '2']}, {'path': 'b.py', 'at': ['3-5']},
                             {'path': 'a.py', 'at': ['file']}, {'path': 'other.py', 'at': ['9']}]}
        self.assertEqual(score_answer(item, json.dumps(flat)),
                         score_answer(item, json.dumps(grouped), answer_format='file-groups-v1'))
        self.assertFalse(score_answer(item, json.dumps(grouped))['valid'])
        self.assertFalse(score_answer(item, json.dumps(flat), answer_format='file-groups-v1')['valid'])
        noted = {'files': [{'path': group['path'], 'entries': [{'at': at, 'note': 'source fact'} for at in group['at']]}
                           for group in grouped['files']]}
        self.assertEqual(score_answer(item, json.dumps(flat)),
                         score_answer(item, json.dumps(noted), answer_format='file-notes-v1'))
        self.assertFalse(score_answer(item, json.dumps(noted), answer_format='file-groups-v1')['valid'])
        for entry in ({'at': '2'}, {'at': '2', 'note': None}, {'at': '2-1', 'note': ''}):
            self.assertFalse(score_answer(item, json.dumps({'files': [{'path': 'a.py', 'entries': [entry]}]}),
                                          answer_format='file-notes-v1')['valid'])
        for at in ([], ['0'], ['01'], ['-1'], ['2-1'], ['2-'], ['2:5'], ['2,5'], [' 2'], [True], [2], [None], ['１']):
            with self.subTest(at=at):
                answer = {'files': [{'path': 'a.py', 'at': at}]}
                self.assertFalse(score_answer(item, json.dumps(answer), answer_format='file-groups-v1')['valid'])
        for path in ('../a.py', '', str(self.workspace)):
            self.assertFalse(score_answer(item, json.dumps({'files': [{'path': path, 'at': ['file']}]}),
                                          answer_format='file-groups-v1')['valid'])
        for at in ('3', '1-9', '3-6'):
            result = score_answer({'required_locations': [{'path': 'a.py', 'line': 2},
                                                          {'path': 'a.py', 'start_line': 3, 'end_line': 5}]},
                                  json.dumps({'files': [{'path': 'a.py', 'at': [at]}]}),
                                  answer_format='file-groups-v1')
            self.assertEqual(result['required_found'], 0)
            self.assertEqual(result['extra_count'], 1)

    def test_path_tree_scores_explicit_ancestry_and_same_named_files(self) -> None:
        item = {'required_locations': [
            {'path': 'src/lib/alpha.py', 'line': 2},
            {'path': 'src/lib/alpha.py', 'start_line': 4, 'end_line': 8},
            {'path': 'src/lib/only.py'},
            {'path': 'pkg/alpha.py', 'line': 5},
            {'path': 'pkg/nested/alpha.py', 'line': 7},
        ]}
        answer = {
            'tree': '\n'.join((
                'src/lib/',
                '  alpha.py  2,4-8',
                '    > preserves the relation and its result',
                '  only.py  file',
                'pkg/',
                '  alpha.py  5',
                '  nested/alpha.py  7',
            )),
            'explanation': 'The two directories are the relevant shared scope.',
        }
        result = score_answer(item, json.dumps(answer), answer_format='path-tree-v1')
        self.assertEqual((result['valid'], result['required_found'], result['required_total'],
                          result['extra_count'], result['reported_unique'], result['reward']),
                         (True, 5, 5, 0, 5, 1))
        self.assertTrue(result['passed'])

    def test_path_tree_preserves_file_level_scoring_and_default_flat_compatibility(self) -> None:
        item = {'required_locations': [{'path': 'a.py'}]}
        answer = {'tree': 'a.py  3,4-8', 'explanation': ''}
        result = score_answer(item, json.dumps(answer), answer_format='path-tree-v1')
        self.assertEqual((result['required_found'], result['required_total'], result['extra_count'],
                          result['reported_unique'], result['reward']), (1, 1, 0, 2, 1))
        self.assertTrue(result['passed'])

        default_schema = answer_schema()
        tree_schema = answer_schema('path-tree-v1')
        self.assertIn('locations', default_schema['properties'])
        self.assertNotIn('tree', default_schema['properties'])
        self.assertEqual(tree_schema['required'], ['tree', 'explanation'])
        self.assertEqual(tree_schema['properties']['tree'], {'type': 'string'})
        self.assertEqual(tree_schema['properties']['explanation'], {'type': 'string'})
        self.assertFalse(score_answer(item, json.dumps(answer))['valid'])

    def test_path_tree_requires_safe_grammar_and_does_not_infer_locations_from_descriptions(self) -> None:
        item = {'required_locations': [{'path': 'a.py', 'line': 1}]}
        malformed = {
            'odd indentation': ' a.py  1',
            'skipped indentation': 'a/\n    a.py  1',
            'below a file leaf': 'a.py  1\n  child.py  2',
            'blank line': 'a.py  1\n\nb.py  2',
            'tab': 'a.py\t1',
            'trailing whitespace': 'a.py  1 ',
            'missing positions': 'a.py',
            'empty directory': 'a/',
            'description without marker': 'a.py  1\n    source fact',
            'description missing space': 'a.py  1\n    >source fact',
            'description without file': '    > source fact\na.py  1',
            'description at wrong depth': 'a.py  1\n      > source fact',
            'empty description': 'a.py  1\n    > ',
            'duplicate casefold file': 'a.py  1\na.PY  1',
            'file as directory parent': 'a  file\na/\n  child.py  1',
            'compressed file ancestor conflict': 'a  file\na/b/\n  child.py  1',
            'parent traversal': '../a.py  1',
            'dot segment': './a.py  1',
            'empty path segment': 'a//b.py  1',
            'absolute path': '/a.py  1',
            'drive path': 'C:/a.py  1',
            'backslash path': 'a\\b.py  1',
            'zero coordinate': 'a.py  0',
            'reversed range': 'a.py  2-1',
            'empty coordinate': 'a.py  1,',
            'leading-zero coordinate': 'a.py  01',
        }
        for label, tree in malformed.items():
            with self.subTest(tree=label):
                result = score_answer(item, json.dumps({'tree': tree, 'explanation': ''}),
                                      answer_format='path-tree-v1')
                self.assertFalse(result['valid'])

        inferred = score_answer(
            {'required_locations': [{'path': 'a.py', 'start_line': 5, 'end_line': 8}]},
            json.dumps({'tree': 'a.py  file\n  > lines 5-8', 'explanation': 'shared scope'}),
            answer_format='path-tree-v1')
        self.assertEqual((inferred['valid'], inferred['required_found'], inferred['required_total'],
                          inferred['extra_count'], inferred['reward']), (True, 0, 1, 1, 0))
        self.assertFalse(inferred['passed'])

    def test_path_tree_precise_ranges_require_exact_file_and_boundary(self) -> None:
        item = {'required_locations': [
            {'path': 'src/a.py', 'start_line': 5, 'end_line': 8},
            {'path': 'pkg/a.py', 'line': 3},
        ]}
        cases = {
            'missing range': 'src/\n  a.py  file\npkg/\n  a.py  3',
            'short range': 'src/\n  a.py  5-7\npkg/\n  a.py  3',
            'misbound range': 'other/\n  a.py  5-8\npkg/\n  a.py  3',
        }
        for label, tree in cases.items():
            with self.subTest(tree=label):
                result = score_answer(item, json.dumps({'tree': tree, 'explanation': ''}),
                                      answer_format='path-tree-v1')
                self.assertEqual((result['valid'], result['required_found'], result['required_total'],
                                  result['extra_count'], result['reward']), (True, 1, 2, 1, 0))
                self.assertFalse(result['passed'])

    def test_answer_format_binding_is_validated_and_part_of_job_identity(self) -> None:
        catalog = self._catalog(); spec_path, spec = self._spec(catalog)
        store = Store(self.root / 'state')
        store.initialize(concurrency=1, model_capacity=1, max_disk_mb=64, min_free_mb=1)
        flat = submit(store, spec_path, self.project, self.root / 'work')
        spec['runtime']['code_reading']['answer_format'] = 'file-groups-v1'
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        grouped = submit(store, spec_path, self.project, self.root / 'work')
        spec['runtime']['code_reading']['answer_format'] = 'path-tree-v1'
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        tree = submit(store, spec_path, self.project, self.root / 'work')
        flat_job, grouped_job, tree_job = (store.jobs(flat)[0], store.jobs(grouped)[0],
                                           store.jobs(tree)[0])
        self.assertNotEqual(flat_job['identity'], grouped_job['identity'])
        self.assertNotEqual(grouped_job['identity'], tree_job['identity'])
        binding = load_spec(spec_path)['evaluations']['items'][0]['runtime']['code_reading']
        self.assertEqual(validate_binding({'code_reading': binding})['answer_format'], 'path-tree-v1')
        for invalid in ('auto', '', None, True, []):
            spec['runtime']['code_reading']['answer_format'] = invalid
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            with self.assertRaisesRegex(EvoError, 'answer_format'):
                load_spec(spec_path)
            with self.assertRaisesRegex(EvoError, 'answer_format'):
                validate_binding({'code_reading': {**binding, 'answer_format': invalid}})

    def test_completed_raw_missing_answer_stays_uncertain_with_usage(self) -> None:
        catalog = self._catalog(); spec_path, _ = self._spec(catalog)
        store = Store(self.root / 'state')
        store.initialize(concurrency=1, model_capacity=1, max_disk_mb=64, min_free_mb=1)
        study = submit(store, spec_path, self.project, self.root / 'work')
        job = store.claim(study); self.assertIsNotNone(job)
        attempt = store.root / 'jobs' / f"j{job['id']}"; attempt.mkdir(parents=True)
        store.phase(job['id'], 'running')
        raw = {'schema': 'agentbase.evo-codex-run/v1', 'status': 'completed', 'model_invoked': True,
               'usage': {'total_tokens': 11}, 'usage_complete': True}
        (attempt / 'codex-result.json').write_text(json.dumps(raw), encoding='utf-8')
        with mock.patch('evo.codex_adapter.run_codex_job', side_effect=AssertionError('model rerun')) as launch:
            result = recover(store, study)
        launch.assert_not_called()
        self.assertEqual(result['counts'], {'uncertain': 1})
        recovered = store.jobs(study)[0]
        self.assertEqual((recovered['usage'], recovered['usage_complete']), (11, True))

        # A valid answer must not erase a separately observed input invalidation.
        (attempt / 'codex-logs').mkdir()
        (attempt / 'codex-logs' / 'last-message.txt').write_text(json.dumps({'locations': [
            {'path': 'src/value.py'}, {'path': 'src/value.py', 'line': 1},
            {'path': 'src/value.py', 'start_line': 1, 'end_line': 2}]}), encoding='utf-8')
        (attempt / 'skill-cache-invalid.json').write_text(json.dumps({
            'schema': 'agentbase-evo-skill-cache-invalid/v1', 'model_invoked': True,
            'error': 'shared payload changed', 'versions': ['v-0123456789ab']}), encoding='utf-8')
        with mock.patch('evo.codex_adapter.run_codex_job', side_effect=AssertionError('model rerun')) as launch:
            result = recover(store, study)
        launch.assert_not_called()
        self.assertEqual(result['counts'], {'uncertain': 1})
        recovered = store.jobs(study)[0]
        self.assertEqual((recovered['usage'], recovered['usage_complete']), (11, True))
        self.assertIn('shared payload changed', recovered['error'])

    def test_location_grammar_deduplicates_and_rejects_bad_ranges(self) -> None:
        item = {'required_locations': [{'path': 'a.py'}, {'path': 'a.py', 'line': 2}]}
        result = score_answer(item, json.dumps({'locations': [
            {'path': 'a.py'}, {'path': 'a.py'}, {'path': 'a.py', 'line': 2}, {'path': 'extra.py'}]}))
        self.assertEqual((result['required_found'], result['required_total'], result['extra_count'], result['reward']),
                         (2, 2, 1, .5))
        self.assertFalse(result['passed'])
        invalid = score_answer(item, json.dumps({'locations': [
            {'path': 'a.py', 'start_line': 3, 'end_line': 2}]}))
        self.assertEqual((invalid['valid'], invalid['reward']), (False, 0))
        self.assertIn('range', invalid['format_error'])
        malformed = score_answer(item, '{not-json')
        self.assertEqual((malformed['valid'], malformed['required_total'], malformed['reward']), (False, 2, 0))

    def test_file_only_requirements_accept_qualified_paths_without_duplicate_credit(self) -> None:
        item = {'required_locations': [{'path': 'a.py'}, {'path': 'b.py'}]}
        result = score_answer(item, json.dumps({'locations': [
            {'path': 'a.py', 'line': 2}, {'path': 'a.py', 'line': 3},
            {'path': 'b.py', 'start_line': 1, 'end_line': 4}]}))
        self.assertEqual(result['schema'], 'agentbase.evo-code-reading-score/v2')
        self.assertEqual((result['required_found'], result['extra_count'], result['reported_unique']), (2, 0, 3))
        self.assertTrue(result['passed'])
        wrong_file = score_answer(item, json.dumps({'locations': [
            {'path': 'a.py', 'line': 2}, {'path': 'other.py', 'line': 2}]}))
        self.assertEqual((wrong_file['required_found'], wrong_file['extra_count']), (1, 1))
        self.assertFalse(wrong_file['passed'])

    def test_precise_requirements_do_not_accept_nearby_or_broad_locations(self) -> None:
        for extra_required in ([], [{'path': 'a.py'}]):
            item = {'required_locations': extra_required + [
                {'path': 'a.py', 'line': 2}, {'path': 'a.py', 'start_line': 5, 'end_line': 8}]}
            for wrong in ({'path': 'a.py', 'line': 3},
                          {'path': 'a.py', 'start_line': 1, 'end_line': 10},
                          {'path': 'a.py', 'start_line': 5, 'end_line': 9}):
                with self.subTest(extra_required=extra_required, wrong=wrong):
                    result = score_answer(item, json.dumps({'locations': [{'path': 'a.py'}, wrong]}))
                    self.assertEqual(result['required_found'], len(extra_required))
                    self.assertGreater(result['extra_count'], 0)
                    self.assertFalse(result['passed'])

    def test_import_rejects_duplicate_required_semantics_even_when_labels_differ(self) -> None:
        value = json.loads(self.source.read_text(encoding='utf-8'))
        value['items'][0]['required_locations'] = [
            {'path': 'src/value.py', 'line': 1, 'label': 'primary'},
            {'path': 'src/value.py', 'line': 1, 'label': 'supporting'},
        ]
        self.source.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'duplicate location'):
            import_catalog(self.source, self.snapshot_root)

    def test_import_rejects_empty_family_and_submit_rejects_two_domain_bindings(self) -> None:
        source = json.loads(self.source.read_text(encoding='utf-8'))
        source['items'][0]['family'] = ''
        self.source.write_text(json.dumps(source), encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'family/prompt/answer_max_lines'):
            import_catalog(self.source, self.snapshot_root)
        source['items'][0]['family'] = 'python'
        self.source.write_text(json.dumps(source), encoding='utf-8')
        catalog = self._catalog(); spec_path, spec = self._spec(catalog)
        spec['runtime']['swe'] = {}
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        store = Store(self.root / 'state')
        store.initialize(concurrency=1, model_capacity=1, max_disk_mb=64, min_free_mb=1)
        with self.assertRaisesRegex(EvoError, 'cannot combine SWE and code-reading'):
            submit(store, spec_path, self.project, self.root / 'work')

    def test_import_checks_lines_without_decoding_snapshot_source(self) -> None:
        binary = self.workspace / 'src' / 'legacy.cpp'
        binary.write_bytes(b'one\r\nlegacy-\x96-byte\r\n')
        value = json.loads(self.source.read_text(encoding='utf-8'))
        value['items'][0]['required_locations'] = [
            {'path': 'src/legacy.cpp', 'line': 2},
            {'path': 'src/legacy.cpp', 'start_line': 1, 'end_line': 2},
        ]
        self.source.write_text(json.dumps(value), encoding='utf-8')
        self.assertEqual(len(import_catalog(self.source, self.snapshot_root)['items'][0]['required_locations']), 2)
        value['items'][0]['required_locations'][1]['end_line'] = 3
        self.source.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'outside the frozen source'):
            import_catalog(self.source, self.snapshot_root)

    def test_snapshot_change_blocks_binding_before_or_after_subject(self) -> None:
        frozen = snapshot_inventory(self.workspace)
        binding = {'snapshot_root': str(self.snapshot_root), 'workspace': 'sample', 'snapshot': frozen}
        self.assertEqual(validate_binding({'code_reading': binding}), binding)
        (self.workspace / 'src' / 'value.py').write_text('changed\n', encoding='utf-8')
        with self.assertRaisesRegex(EvoError, 'differs'):
            validate_binding({'code_reading': binding})

    def test_snapshot_inventory_rejects_a_junction_entrypoint(self) -> None:
        link = self.root / 'snapshot-junction'
        created = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(self.workspace)],
                                 capture_output=True, text=True)
        if created.returncode != 0:
            self.skipTest(f'junction fixture unavailable: {created.stderr.strip()}')
        try:
            with self.assertRaisesRegex(EvoError, 'must not be a link'):
                snapshot_inventory(link)
        finally:
            link.rmdir()


if __name__ == '__main__':
    unittest.main()
