from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

import agentbase_codex
from evaluation_core import EvaluationError, PreconditionError
from evo.spec import EvoError
from evo.runtime import _persisted_model_invoked, _swe_codex_inputs
from evo.store import Store
from evo.swe_adapter import SWE_STATE_SCHEMA, finalize_job, prepare_job, validate_binding, validate_runtime


class EvoSweRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        self.project = root / "project"
        self.project.mkdir()
        self.corpus = root / "corpus.json"
        self.corpus.write_text("{}", encoding="utf-8")
        self.runtime = {
            "adapter": "codex",
            "swe": {
                "corpus": str(self.corpus),
                "corpus_sha256": hashlib.sha256(self.corpus.read_bytes()).hexdigest(),
                "task": "task-1",
                "state_root": str(root / "swe-state"),
                "work_root": str(root / "swe-work"),
                "work_reservation_mb": 64,
            },
        }

    def test_validate_binding_is_static_and_freezes_paths(self) -> None:
        with patch("evo.swe_adapter.load_corpus", return_value={"tasks": []}) as load, \
             patch("evo.swe_adapter.verify_windows_adapter_assets") as assets, \
             patch("evo.swe_adapter.require_task", return_value={"id": "task-1"}) as task:
            result = validate_binding(self.runtime, project_root=self.project)
        self.assertEqual(result["task"], "task-1")
        self.assertEqual(result["work_reservation_mb"], 64)
        load.assert_called_once_with(self.corpus)
        assets.assert_called_once()
        task.assert_called_once()

    def test_validate_binding_rejects_unreserved_swe_workspace(self) -> None:
        del self.runtime["swe"]["work_reservation_mb"]
        with self.assertRaisesRegex(EvoError, "work_reservation_mb"):
            validate_binding(self.runtime, project_root=self.project)

    def test_swe_rejects_silently_ignored_generic_inputs_and_graders(self) -> None:
        for key, value in [('files', [{'source': 'extra', 'target': 'extra'}]),
                           ('verifier', {'argv': ['custom']}), ('answer_contains', ['custom'])]:
            with self.subTest(key=key), self.assertRaisesRegex(EvoError, 'belong to the corpus'):
                validate_binding({**self.runtime, key: value}, project_root=self.project)

    def test_runtime_namespace_is_stable_per_evo_state_root(self) -> None:
        root = self.project.parent
        with patch("evo.swe_adapter.validate_binding", return_value=dict(self.runtime["swe"])):
            first = validate_runtime(self.runtime, project_root=self.project, evo_state_root=root / "evo-a",
                                     evo_work_root=root / "evo-work-a")
            repeat = validate_runtime(self.runtime, project_root=self.project, evo_state_root=root / "evo-a",
                                      evo_work_root=root / "evo-work-a")
            other = validate_runtime(self.runtime, project_root=self.project, evo_state_root=root / "evo-b",
                                     evo_work_root=root / "evo-work-b")
        self.assertEqual(first["owner_namespace"], repeat["owner_namespace"])
        self.assertNotEqual(first["owner_namespace"], other["owner_namespace"])

    def test_missing_qualification_does_not_create_or_prepare(self) -> None:
        attempt = self.project.parent / "attempt"
        context = {
            "swe": self.runtime["swe"], "corpus_path": self.corpus,
            "state_root": Path(self.runtime["swe"]["state_root"]),
            "work_root": Path(self.runtime["swe"]["work_root"]), "corpus": {},
            "task": {"toolchain": {"kind": "python"}},
        }
        with patch("evo.swe_adapter._qualified_context", side_effect=PreconditionError("run oracle")), \
             patch("evo.swe_adapter.create_workspace") as create, \
             patch("evo.swe_adapter.prepare_dependencies") as dependencies:
            with self.assertRaisesRegex(PreconditionError, "run oracle"):
                prepare_job(project_root=self.project, runtime=self.runtime, study_id=1, job_id=2,
                            attempt_root=attempt, environment={})
        create.assert_not_called()
        dependencies.assert_not_called()

    def test_shared_task_context_stages_instruction_prompt_and_runtime(self) -> None:
        workspace = self.project.parent / "task-workspace"
        workspace.mkdir()
        assets = self.project.parent / "task-assets"
        assets.mkdir()
        (assets / "instruction.md").write_text("repair the fixture", encoding="utf-8")
        task = {"windows_adapter": {"path": "adapter.patch"}, "allowed_patch_paths": ["src/**"]}
        runtime = {"bin_directory": str(workspace / ".agentbase" / "task-runtime" / "bin")}
        with patch.object(agentbase_codex, "task_asset_root", return_value=assets), \
             patch.object(agentbase_codex, "require_task", return_value=task), \
             patch.object(agentbase_codex, "candidate_public_tooling_hint", return_value="TOOLS\n"), \
             patch.object(agentbase_codex, "candidate_public_checks_hint", return_value="CHECKS\n"), \
             patch.object(agentbase_codex, "candidate_patch_scope_hint", return_value="SCOPE\n"), \
             patch.object(agentbase_codex, "candidate_windows_adapter_hint", return_value="ADAPTER\n"), \
             patch.object(agentbase_codex, "dependency_runtime_projection", return_value=runtime):
            result = agentbase_codex.stage_candidate_task_context(
                self.project.parent / "state", {}, "task-1", workspace, {"python": "python.exe"}
            )
        self.assertEqual((workspace / ".agentbase" / "task.md").read_text(encoding="utf-8"), "repair the fixture")
        for marker in ("ADAPTER", "SCOPE", "TOOLS", "CHECKS"):
            self.assertIn(marker, result["prompt"])
        self.assertEqual(result["task_runtime"], runtime)
        self.assertIsNone(result["prompt_path"])

    def test_finalize_resumes_after_patch_capture_without_model_call(self) -> None:
        attempt = self.project.parent / "attempt"
        attempt.mkdir()
        self.runtime["swe"]["owner_namespace"] = "owner"
        work = Path(self.runtime["swe"]["work_root"])
        workspace = work / "evo" / "owner" / "s1" / "j2" / "candidate"
        workspace.mkdir(parents=True)
        patch_path = attempt / "candidate.patch"
        patch_path.write_bytes(b"patch")
        qualification = {
            "receipt_sha256": "q", "dependency_identity_sha256": "dependency",
            "p2p_exclusions": ["known-skip"],
        }
        (attempt / "swe-state.json").write_text(json.dumps({
            "schema": SWE_STATE_SCHEMA, "stage": "patch-captured", "study": 1, "job": 2,
            "workspace": str(workspace), "task": "task-1", "qualification": qualification,
            "candidate_patch": {"path": str(patch_path), "sha256": hashlib.sha256(b"patch").hexdigest(), "bytes": 5, "files": ["a.py"]},
        }), encoding="utf-8")
        context = {
            "swe": self.runtime["swe"], "corpus_path": self.corpus,
            "state_root": Path(self.runtime["swe"]["state_root"]), "work_root": work,
            "corpus": {}, "task": {"toolchain": {"kind": "python"}},
            "qualifications": [qualification], "verifier_runtime": {},
        }
        verifier = {
            "dependency_identity": {"identity_sha256": "dependency"},
            "checks": [], "observed_baseline_p2p_exclusions": ["known-skip"],
            "grade": {"reward": {"reward": 1}},
        }
        with patch("evo.swe_adapter._qualified_context", return_value=context), \
             patch("evo.swe_adapter.CaseLock"), \
             patch("evo.swe_adapter.capture_candidate_patch") as capture, \
             patch("evo.swe_adapter.run_candidate_verifier", return_value=verifier) as verify:
            result = finalize_job(project_root=self.project, runtime=self.runtime, study_id=1, job_id=2,
                                  attempt_root=attempt, environment={},
                                  raw_receipt={"model_invoked": True, "status": "completed"})
        capture.assert_not_called()
        verify.assert_called_once()
        self.assertEqual(result["values"], {"quality.reward": 1})
        self.assertEqual(json.loads((attempt / "swe-state.json").read_text(encoding="utf-8"))["stage"], "verified")
        with patch("evo.swe_adapter._qualified_context", side_effect=AssertionError("must not revalidate")):
            reused = finalize_job(project_root=self.project, runtime=self.runtime, study_id=1, job_id=2,
                                  attempt_root=attempt, environment={}, raw_receipt={})
        self.assertEqual(reused["values"], {"quality.reward": 1})

    def test_tampered_captured_patch_stays_recoverable_and_skips_verifier(self) -> None:
        attempt = self.project.parent / "tampered-attempt"
        attempt.mkdir()
        self.runtime["swe"]["owner_namespace"] = "owner"
        work = Path(self.runtime["swe"]["work_root"])
        workspace = work / "evo" / "owner" / "s1" / "j4" / "candidate"
        workspace.mkdir(parents=True)
        patch_path = attempt / "candidate.patch"
        patch_path.write_bytes(b"tampered")
        qualification = {"receipt_sha256": "q", "dependency_identity_sha256": "dependency", "p2p_exclusions": []}
        (attempt / "swe-state.json").write_text(json.dumps({
            "schema": SWE_STATE_SCHEMA, "stage": "patch-captured", "study": 1, "job": 4,
            "workspace": str(workspace), "task": "task-1", "qualification": qualification,
            "candidate_patch": {"path": str(patch_path), "sha256": hashlib.sha256(b"original").hexdigest()},
        }), encoding="utf-8")
        context = {
            "swe": self.runtime["swe"], "state_root": Path(self.runtime["swe"]["state_root"]),
            "work_root": work, "corpus": {}, "task": {}, "qualifications": [qualification],
        }
        with patch("evo.swe_adapter._qualified_context", return_value=context), \
             patch("evo.swe_adapter.CaseLock"), \
             patch("evo.swe_adapter.run_candidate_verifier") as verify:
            with self.assertRaisesRegex(EvaluationError, "patch changed"):
                finalize_job(project_root=self.project, runtime=self.runtime, study_id=1, job_id=4,
                             attempt_root=attempt, environment={},
                             raw_receipt={"model_invoked": True, "status": "completed"})
        verify.assert_not_called()
        self.assertEqual(json.loads((attempt / "swe-state.json").read_text(encoding="utf-8"))["stage"], "patch-captured")

    def test_invalid_candidate_patch_is_terminal_reward_zero(self) -> None:
        attempt = self.project.parent / "invalid-attempt"
        attempt.mkdir()
        self.runtime["swe"]["owner_namespace"] = "owner"
        work = Path(self.runtime["swe"]["work_root"])
        workspace = work / "evo" / "owner" / "s1" / "j3" / "candidate"
        workspace.mkdir(parents=True)
        qualification = {"receipt_sha256": "q", "dependency_identity_sha256": "dependency", "p2p_exclusions": []}
        (attempt / "swe-state.json").write_text(json.dumps({
            "schema": SWE_STATE_SCHEMA, "stage": "candidate-finished", "study": 1, "job": 3,
            "workspace": str(workspace), "task": "task-1", "qualification": qualification,
        }), encoding="utf-8")
        context = {
            "swe": self.runtime["swe"], "state_root": Path(self.runtime["swe"]["state_root"]),
            "work_root": work, "corpus": {}, "task": {}, "qualifications": [qualification],
        }
        with patch("evo.swe_adapter._qualified_context", return_value=context), \
             patch("evo.swe_adapter.CaseLock"), \
             patch("evo.swe_adapter.capture_candidate_patch", side_effect=PreconditionError("protected paths")), \
             patch("evo.swe_adapter.run_candidate_verifier") as verify:
            result = finalize_job(project_root=self.project, runtime=self.runtime, study_id=1, job_id=3,
                                  attempt_root=attempt, environment={},
                                  raw_receipt={"model_invoked": True, "status": "completed"})
        verify.assert_not_called()
        self.assertFalse(result["valid"])
        self.assertEqual(result["values"], {"quality.reward": 0})
        with patch("evo.swe_adapter._qualified_context", side_effect=AssertionError("must not revalidate")):
            reused = finalize_job(project_root=self.project, runtime=self.runtime, study_id=1, job_id=3,
                                  attempt_root=attempt, environment={}, raw_receipt={})
        self.assertEqual(reused["values"], {"quality.reward": 0})

    def test_store_reserves_declared_swe_work_capacity(self) -> None:
        store = Store(self.project.parent / "evo-state")
        store.initialize(concurrency=1, model_capacity=1, max_disk_mb=256, min_free_mb=1)
        spec = {"id": "swe", "budget": {"max_tokens": 1000, "concurrency": 1}}
        job = {
            "runtime": {"adapter": "codex", "max_agents": 1, "token_reservation": 10,
                        "swe": {"work_reservation_mb": 64}},
            "execution_identity": "identity", "source_inventory": {},
        }
        study = store.submit(spec, [job], self.project, self.project.parent / "evo-work")
        self.assertEqual(store.jobs(study)[0]["disk_reservation"], 64 * 1024**2)

    def test_swe_prompt_is_injected_into_codex_consumed_item_runtime(self) -> None:
        study = {"spec": {"evaluations": {"items": [{"id": "task-1", "runtime": {"swe": {}}}]}}}
        job = {"plan": {"item": "task-1", "runtime": {"adapter": "codex"}}}
        spec, plan = _swe_codex_inputs(study, job, {"task_prompt": "fix the owned task"})
        self.assertEqual(spec["evaluations"]["items"][0]["runtime"]["prompt"], "fix the owned task")
        self.assertNotIn("prompt", plan["runtime"])
        self.assertNotIn("prompt", study["spec"]["evaluations"]["items"][0]["runtime"])

    def test_persisted_model_receipt_prevents_zero_cost_retry_after_postprocessing_failure(self) -> None:
        attempt = self.project.parent / "model-attempt"
        attempt.mkdir()
        (attempt / "codex-result.json").write_text(
            json.dumps({"model_invoked": True, "status": "completed"}), encoding="utf-8"
        )
        self.assertTrue(_persisted_model_invoked(attempt, False))


if __name__ == "__main__":
    unittest.main()
