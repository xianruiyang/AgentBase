from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.runtime import execute, managed_storage_roots, settle


class SweLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Mock()
        self.store.root = self.root / 'state'
        self.study = {'project': str(self.root / 'project'), 'work': str(self.root / 'work'),
                      'spec': {}, 'state': 'active'}
        self.store.study.return_value = self.study
        self.job = {'id': 2, 'study': 1, 'identity': 'frozen', 'plan': {},
                    'runtime': {'adapter': 'codex', 'swe': {'work_root': str(self.root / 'swe-work')}}}
        self.attempt = self.store.root / 'jobs/j2'
        self.attempt.mkdir(parents=True)

    def test_final_receipt_settles_without_requiring_unchanged_candidate_sources(self):
        receipt = {'execution_identity': 'frozen', 'job': 2}
        (self.attempt / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        with patch('evo.runtime.candidate_roots', return_value=[]), \
             patch('evo.runtime.execution_sources', side_effect=AssertionError('must not re-open execution inputs')), \
             patch('evo.runtime.settle') as settlement:
            execute(self.store, self.job, None)
        settlement.assert_called_once_with(self.store, self.job, receipt)
        self.store.finish.assert_not_called()

    def test_failed_post_model_recovery_keeps_usage_unknown_and_does_not_clean_workspace(self):
        (self.attempt / 'codex-result.json').write_text(
            json.dumps({'model_invoked': True, 'status': 'completed'}), encoding='utf-8')
        with patch('evo.runtime.candidate_roots', return_value=[]), \
             patch('evo.runtime._complete_from_raw', side_effect=RuntimeError('verifier interrupted')), \
             patch('evo.swe_adapter.cleanup_job') as cleanup:
            execute(self.store, self.job, None)
        cleanup.assert_not_called()
        self.assertEqual(self.store.finish.call_args.args, (2, 'uncertain'))
        self.assertIsNone(self.store.finish.call_args.kwargs['usage'])
        self.assertFalse(self.store.finish.call_args.kwargs['usage_complete'])

    def test_settlement_owns_cleanup_for_normal_and_recovered_receipts(self):
        receipt = {'execution_identity': 'frozen', 'job': 2, 'usage': 19, 'usage_complete': True}
        with patch('evo.swe_adapter.cleanup_job') as cleanup:
            settle(self.store, self.job, receipt)
        cleanup.assert_called_once_with(self.job['runtime'], self.attempt)
        self.assertEqual(self.store.finish.call_args.args, (2, 'completed'))
        self.assertEqual(self.store.finish.call_args.kwargs['usage'], 19)

    def test_storage_includes_every_owned_swe_root_but_not_external_cold_state(self):
        self.store.work_roots.return_value = [self.root / 'work']
        self.store.jobs.return_value = [
            {'runtime': {'swe': {'work_root': str(self.root / name), 'owner_namespace': 'owner',
                                 'state_root': str(self.root / 'cold')}}} for name in ('swe-a', 'swe-b')]
        roots = managed_storage_roots(self.store)
        self.assertIn(self.root / 'swe-a/evo/owner', roots)
        self.assertIn(self.root / 'swe-b/evo/owner', roots)
        self.assertNotIn(self.root / 'cold', roots)


if __name__ == '__main__':
    unittest.main()
