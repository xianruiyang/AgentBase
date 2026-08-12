from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]
TASKCTL = Path(__file__).resolve().parents[1] / "scripts" / "taskctl.py"
WORKCTL = SKILLS_ROOT / "delivery-workflow" / "scripts" / "workctl.py"


def load_taskctl_module():
    spec = importlib.util.spec_from_file_location("taskctl_under_test", TASKCTL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskctlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "work"
        self.run_ok(
            WORKCTL,
            "init",
            "--work-dir",
            str(self.root),
            "--id",
            "demo",
            "--title",
            "演示交付",
        )
        self.write_documents()
        self.run_ok(
            WORKCTL,
            "protect",
            "--work-dir",
            str(self.root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            "conversation:confirmed",
        )
        self.run_ok(WORKCTL, "index", "--work-dir", str(self.root))
        self.add_task(
            self.task(
                "T001",
                "实现导出职责",
                ["SOL-001"],
                scope=["src/export/**"],
            )
        )
        self.add_task(
            self.task(
                "T002",
                "接入界面",
                ["SOL-001"],
                dependencies=[
                    {"id": "T001", "type": "hard", "consumes": ["导出接口"]}
                ],
                scope=["src/ui/**"],
            )
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(
        self, script: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(script), *args],
            text=True,
            capture_output=True,
            encoding="utf-8",
            env=environment,
            check=False,
        )

    def run_ok(self, script: Path, *args: str) -> dict:
        result = self.run_cli(script, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def run_task(self, *args: str) -> dict:
        return self.run_ok(TASKCTL, *args, "--task-dir", str(self.root))

    def write_documents(self) -> None:
        (self.root / "requirements.md").write_text(
            """# 需求

## REQ-001 导出结果

- 状态: confirmed
- 关联: AC-001

用户能够导出结果。

## AC-001 可读回

- 状态: confirmed
- 关联: REQ-001

导出结果能够读回。

## CON-001 保持认证

- 状态: confirmed

不得绕过认证。
""",
            encoding="utf-8",
        )
        (self.root / "user-design.md").write_text(
            """# 用户设计

## UDES-001 接入现有入口

- 状态: confirmed
- 关联: REQ-001

使用现有入口。
""",
            encoding="utf-8",
        )
        (self.root / "design.md").write_text(
            """# 模型设计

## DES-001 导出职责

- 状态: confirmed
- 满足: REQ-001, AC-001, UDES-001

建立导出职责。
""",
            encoding="utf-8",
        )
        (self.root / "current-state.md").write_text(
            """# 现状

## OBS-001 当前缺少导出

- 状态: confirmed
- 关联: DES-001

直接检查没有导出实现。

## GAP-001 导出差距

- 状态: confirmed
- 关联: DES-001, OBS-001

当前不满足设计。
""",
            encoding="utf-8",
        )
        (self.root / "solution.md").write_text(
            """# 方案

## SOL-001 实现导出

- 状态: confirmed
- 解决: GAP-001
- 满足: DES-001

实现并接入导出职责。
""",
            encoding="utf-8",
        )
        (self.root / "deferred-changes.md").write_text(
            "# 延后讨论项\n\n- 无\n", encoding="utf-8"
        )

    def task(
        self,
        task_id: str,
        title: str,
        source_ids: list[str],
        *,
        dependencies: list[dict] | None = None,
        scope: list[str] | None = None,
    ) -> dict:
        return {
            "schema": "task.record",
            "id": task_id,
            "title": title,
            "outcome": f"{title}完成并可由后继任务消费",
            "source_ids": source_ids,
            "dependencies": dependencies or [],
            "mutation_scope": scope or [],
            "outputs": [f"{title}的结果"],
            "verification": [f"验证{title}的实际行为"],
            "suggested_skills": [],
            "reasoning_hint": "medium",
            "revision": 1,
        }

    def add_task(self, task: dict) -> dict:
        candidate = Path(self.temp.name) / f"{task['id']}.json"
        candidate.write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.run_task("add", "--file", str(candidate))

    def result_payload(self, task_id: str = "T001") -> dict:
        return {
            "schema": "task.result",
            "task_id": task_id,
            "task_revision": 1,
            "outcome": "导出职责已经实现",
            "outputs": ["正式导出接口"],
            "changed_files": ["src/export/service.py"],
            "verification": ["真实调用并读回通过"],
            "unresolved": [],
            "invalidated_source_ids": [],
        }

    def complete_t001(self) -> dict:
        claimed = self.run_task("claim", "--id", "T001", "--owner", "agent-a")
        started = self.run_task(
            "start",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--expected-state-revision",
            str(claimed["state"]["revision"]),
        )
        result_file = Path(self.temp.name) / "T001-result.json"
        result_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.run_task(
            "complete",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--expected-state-revision",
            str(started["state"]["revision"]),
        )

    def test_next_is_advisory_and_dependency_query_is_compact(self) -> None:
        next_payload = self.run_task("next")
        self.assertEqual([item["id"] for item in next_payload["items"]], ["T001"])
        with_blocked = self.run_task("next", "--include-blocked")
        t002 = next(item for item in with_blocked["items"] if item["id"] == "T002")
        self.assertFalse(t002["recommended"])
        self.assertIn(
            "hard_dependency_incomplete",
            {item["kind"] for item in t002["diagnostics"]},
        )
        dependencies = self.run_task("deps", "--id", "T002")
        self.assertEqual(dependencies["items"][0]["id"], "T001")

        self.complete_t001()
        after = self.run_task("next")
        self.assertEqual(after["items"][0]["id"], "T002")
        self.assertTrue(after["items"][0]["recommended"])

    def test_status_always_exposes_review_and_separate_progress(self) -> None:
        status = self.run_task("status")
        self.assertEqual(status["status_counts"]["review"], 0)
        self.assertEqual(status["needs_review_count"], 0)
        started = self.run_task("start", "--id", "T001", "--owner", "agent-a")
        self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--status",
            "review",
            "--message",
            "等待人工查看",
            "--expected-state-revision",
            str(started["state"]["revision"]),
        )
        status = self.run_task("status")
        self.assertEqual(status["needs_review_count"], 1)
        self.assertEqual(status["upstream"]["deferred_change_count"], 0)
        self.assertEqual(status["results"]["current_result_count"], 0)

    def test_note_on_todo_task_claims_it_for_the_owner(self) -> None:
        noted = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--message",
            "开始梳理实现边界",
        )
        self.assertEqual(noted["state"]["status"], "claimed")
        self.assertEqual(noted["state"]["owner"], "agent-a")

    def test_note_can_explicitly_clear_a_message(self) -> None:
        noted = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--message",
            "临时说明",
        )
        cleared = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--message",
            "",
            "--expected-state-revision",
            str(noted["state"]["revision"]),
        )
        self.assertEqual(cleared["state"]["note"], "")

    def test_release_requires_an_owner_and_clears_the_previous_next_action(self) -> None:
        unowned = self.run_cli(
            TASKCTL,
            "release",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
        )
        self.assertEqual(unowned.returncode, 2)
        self.assertIn("unowned task", json.loads(unowned.stderr)["error"])

        claimed = self.run_task("claim", "--id", "T001", "--owner", "agent-a")
        noted = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--next-action",
            "继续修改",
            "--expected-state-revision",
            str(claimed["state"]["revision"]),
        )
        released = self.run_task(
            "release",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--expected-state-revision",
            str(noted["state"]["revision"]),
        )
        self.assertEqual(released["state"]["status"], "todo")
        self.assertIsNone(released["state"]["owner"])
        self.assertEqual(released["state"]["next_action"], "")

    def test_context_is_bounded_and_completion_context_has_no_pass_value(self) -> None:
        self.complete_t001()
        context_result = self.run_cli(
            TASKCTL,
            "context",
            "--task-dir",
            str(self.root),
            "--id",
            "T002",
            "--budget",
            "5000",
        )
        self.assertEqual(context_result.returncode, 0, context_result.stderr)
        self.assertLessEqual(len(context_result.stdout), 5001)
        context = json.loads(context_result.stdout)
        self.assertEqual(context["dependencies"][0]["result"]["outputs"], ["正式导出接口"])
        self.assertEqual(context["protected_baseline"]["status"], "protected")

        completion = self.run_task(
            "completion-context", "--limit", "10", "--budget", "12000"
        )
        target_ids = {target["id"] for target in completion["targets"]}
        self.assertEqual(target_ids, {"REQ-001", "AC-001", "UDES-001"})
        for target in completion["targets"]:
            self.assertGreaterEqual(target["candidate_result_count"], 1)
        self.assertNotIn("passed", completion)
        self.assertNotIn("pass", completion)

    def test_task_revision_conflict_and_dependency_cycle_are_hard_errors(self) -> None:
        updated = self.task(
            "T001", "更新导出职责", ["SOL-001"], scope=["src/export/**"]
        )
        candidate = Path(self.temp.name) / "T001-update.json"
        candidate.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        first = self.run_task(
            "update",
            "--file",
            str(candidate),
            "--expected-task-revision",
            "1",
        )
        self.assertEqual(first["task_revision"], 2)
        conflict = self.run_cli(
            TASKCTL,
            "update",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate),
            "--expected-task-revision",
            "1",
        )
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("revision conflict", json.loads(conflict.stderr)["error"])

        self.add_task(
            self.task(
                "T004",
                "等待未来任务",
                ["SOL-001"],
                dependencies=[
                    {"id": "T005", "type": "ordering", "consumes": ["候选信息"]}
                ],
            )
        )
        cycle_task = self.task(
            "T005",
            "形成循环",
            ["SOL-001"],
            dependencies=[
                {"id": "T004", "type": "hard", "consumes": ["结果"]}
            ],
        )
        cycle_file = Path(self.temp.name) / "T005.json"
        cycle_file.write_text(
            json.dumps(cycle_task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cycle = self.run_cli(
            TASKCTL,
            "add",
            "--task-dir",
            str(self.root),
            "--file",
            str(cycle_file),
        )
        self.assertEqual(cycle.returncode, 2)
        self.assertIn("dependency cycle", json.loads(cycle.stderr)["error"])

    def test_parallel_scope_overlap_is_a_warning(self) -> None:
        self.add_task(
            self.task(
                "T003",
                "修改界面子路径",
                ["SOL-001"],
                scope=["src/ui/widget/**"],
            )
        )
        self.run_task("claim", "--id", "T002", "--owner", "agent-a")
        claimed = self.run_task("claim", "--id", "T003", "--owner", "agent-b")
        self.assertIn(
            "mutation_overlap", {warning["kind"] for warning in claimed["warnings"]}
        )

    def test_render_contains_zero_review_count(self) -> None:
        rendered = self.run_task("render")
        table = Path(rendered["output"]).read_text(encoding="utf-8")
        self.assertIn("| review | 0 |", table)
        self.assertIn("只是任务合同与状态的可重建视图", table)

    def test_protected_source_drift_blocks_task_state_changes(self) -> None:
        with (self.root / "requirements.md").open("a", encoding="utf-8") as handle:
            handle.write("\n执行期改写。\n")
        started = self.run_cli(
            TASKCTL,
            "start",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
        )
        self.assertEqual(started.returncode, 2)
        self.assertIn("protected source changed", json.loads(started.stderr)["error"])

    def test_completed_contract_requires_reopen_before_update(self) -> None:
        self.complete_t001()
        candidate = Path(self.temp.name) / "T001-after-complete.json"
        candidate.write_text(
            json.dumps(
                self.task(
                    "T001", "改写已完成合同", ["SOL-001"], scope=["src/export/**"]
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        updated = self.run_cli(
            TASKCTL,
            "update",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate),
            "--expected-task-revision",
            "1",
        )
        self.assertEqual(updated.returncode, 2)
        self.assertIn("reopen", json.loads(updated.stderr)["error"])

    def test_draft_is_directly_addable_task_json(self) -> None:
        drafted = self.run_task(
            "draft",
            "--id",
            "T010",
            "--title",
            "生成候选任务",
            "--outcome",
            "形成可消费结果",
            "--source-id",
            "SOL-001",
            "--output",
            "候选产出",
            "--verification",
            "检查候选产出",
        )
        self.assertEqual(drafted["schema"], "task.record")
        self.assertEqual(drafted["id"], "T010")
        self.assertNotIn("task", drafted)

    def test_add_and_update_return_advisory_contract_diagnostics(self) -> None:
        candidate = self.task("T010", "带诊断的候选任务", ["SOL-999"])
        candidate["outputs"] = []
        candidate["verification"] = []
        added = self.add_task(candidate)
        added_kinds = {item["kind"] for item in added["diagnostics"]}
        self.assertIn("unknown_source_id", added_kinds)
        self.assertIn("outputs_empty", added_kinds)
        self.assertIn("verification_empty", added_kinds)
        self.assertIn("advisory", added["note"])

        candidate["title"] = "更新后的候选任务"
        update_file = Path(self.temp.name) / "T010-update.json"
        update_file.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        updated = self.run_task(
            "update",
            "--file",
            str(update_file),
            "--expected-task-revision",
            "1",
        )
        updated_kinds = {item["kind"] for item in updated["diagnostics"]}
        self.assertIn("unknown_source_id", updated_kinds)
        self.assertIn("outputs_empty", updated_kinds)
        self.assertIn("verification_empty", updated_kinds)

    def test_add_validates_existing_state_storage_before_writing(self) -> None:
        orphan = {
            "schema": "task.state",
            "task_id": "T999",
            "status": "todo",
            "owner": None,
            "revision": 1,
            "note": "",
            "blocked_reason": "",
            "next_action": "",
            "result_ref": None,
        }
        (self.root / "state" / "T999.json").write_text(
            json.dumps(orphan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        candidate = self.task("T010", "不得部分写入", ["SOL-001"])
        candidate_file = Path(self.temp.name) / "T010-invalid-storage.json"
        candidate_file.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        added = self.run_cli(
            TASKCTL,
            "add",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate_file),
        )
        self.assertEqual(added.returncode, 2)
        self.assertIn("task/state storage mismatch", json.loads(added.stderr)["error"])
        self.assertFalse((self.root / "tasks" / "T010.json").exists())
        self.assertFalse((self.root / "state" / "T010.json").exists())

    def test_update_validates_existing_state_storage_before_writing(self) -> None:
        original = json.loads((self.root / "tasks" / "T001.json").read_text(encoding="utf-8"))
        orphan = {
            "schema": "task.state",
            "task_id": "T999",
            "status": "todo",
            "owner": None,
            "revision": 1,
            "note": "",
            "blocked_reason": "",
            "next_action": "",
            "result_ref": None,
        }
        (self.root / "state" / "T999.json").write_text(
            json.dumps(orphan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        candidate = dict(original)
        candidate["title"] = "不得在失败时改写"
        candidate_file = Path(self.temp.name) / "T001-invalid-storage.json"
        candidate_file.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        updated = self.run_cli(
            TASKCTL,
            "update",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate_file),
            "--expected-task-revision",
            "1",
        )
        self.assertEqual(updated.returncode, 2)
        self.assertIn("task/state storage mismatch", json.loads(updated.stderr)["error"])
        after = json.loads((self.root / "tasks" / "T001.json").read_text(encoding="utf-8"))
        self.assertEqual(after, original)

    def test_task_table_identity_must_match_the_delivery_workflow(self) -> None:
        table_path = self.root / "task-table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["id"] = "another-workflow"
        table_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        listed = self.run_cli(
            TASKCTL, "list", "--task-dir", str(self.root)
        )
        self.assertEqual(listed.returncode, 2)
        self.assertIn("different workflow", json.loads(listed.stderr)["error"])

    def test_generated_task_view_cannot_be_redirected_to_requirements(self) -> None:
        table_path = self.root / "task-table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["table_view"] = "requirements.md"
        table_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rendered = self.run_cli(
            TASKCTL, "render", "--task-dir", str(self.root)
        )
        self.assertEqual(rendered.returncode, 2)
        self.assertIn("table_view must remain", json.loads(rendered.stderr)["error"])

    def test_workflow_cannot_redirect_or_bypass_protected_baseline(self) -> None:
        workflow_path = self.root / "workflow.json"
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        workflow["protected_baseline"] = "other.json"
        workflow_path.write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        started = self.run_cli(
            TASKCTL,
            "start",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
        )
        self.assertEqual(started.returncode, 2)
        self.assertIn("protected_baseline must remain", json.loads(started.stderr)["error"])

    def test_completion_context_rejects_stale_index(self) -> None:
        with (self.root / "deferred-changes.md").open("a", encoding="utf-8") as handle:
            handle.write(
                "\n## DCR-001 延后讨论入口调整\n\n- 状态: deferred\n- 目标: UDES-001\n"
            )
        completion = self.run_task("completion-context")
        self.assertEqual(completion["targets"], [])
        self.assertIn(
            "upstream_index_stale",
            {diagnostic["kind"] for diagnostic in completion["diagnostics"]},
        )

    def test_completion_context_rejects_tampered_derived_index_content(self) -> None:
        index_path = self.root / ".work-cache" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        fake = dict(index["sections"][0])
        fake["id"] = "REQ-999"
        fake["title"] = "伪造的可修订目标"
        index["sections"].append(fake)
        index["reverse_references"]["REQ-999"] = []
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        completion = self.run_task("completion-context", "--limit", "20")
        self.assertEqual(completion["targets"], [])
        self.assertIn(
            "upstream_index_derived_content_mismatch",
            {item["kind"] for item in completion["diagnostics"]},
        )

    def test_completion_context_pages_candidates_constraints_and_deferred_items(self) -> None:
        (self.root / "deferred-changes.md").write_text(
            """# 延后讨论项

## DCR-001 延后入口调整

- 状态: deferred
- 目标: UDES-001

## DCR-002 延后格式调整

- 状态: deferred
- 目标: REQ-001
""",
            encoding="utf-8",
        )
        self.run_ok(WORKCTL, "index", "--work-dir", str(self.root))
        first = self.run_task(
            "completion-context",
            "--target-id",
            "REQ-001",
            "--max-items",
            "1",
            "--budget",
            "12000",
        )
        self.assertEqual(first["constraint_count"], 1)
        self.assertEqual(first["returned_constraint_count"], 1)
        self.assertEqual(first["open_deferred_change_count"], 2)
        self.assertEqual(first["returned_open_deferred_change_count"], 1)
        self.assertEqual(first["targets"][0]["candidate_task_count"], 2)
        self.assertEqual(first["targets"][0]["returned_candidate_task_count"], 1)
        self.assertIsNotNone(first["pagination"]["deferred_next_after_id"])
        candidate_cursor = first["targets"][0]["candidate_next_after_id"]
        candidate_page = self.run_task(
            "completion-context",
            "--target-id",
            "REQ-001",
            "--candidate-after-id",
            candidate_cursor,
            "--snapshot-id",
            first["snapshot_id"],
            "--max-items",
            "1",
        )
        self.assertEqual(
            candidate_page["targets"][0]["returned_candidate_task_count"], 1
        )
        deferred_page = self.run_task(
            "completion-context",
            "--target-id",
            "REQ-001",
            "--deferred-after-id",
            first["pagination"]["deferred_next_after_id"],
            "--snapshot-id",
            first["snapshot_id"],
            "--max-items",
            "1",
        )
        self.assertEqual(deferred_page["open_deferred_changes"][0]["id"], "DCR-002")

    def test_current_result_must_match_current_task_revision(self) -> None:
        self.complete_t001()
        result_path = self.root / "results" / "T001.r4.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["task_revision"] = 99
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shown = self.run_cli(
            TASKCTL, "show", "--task-dir", str(self.root), "--id", "T001"
        )
        self.assertEqual(shown.returncode, 2)
        self.assertIn("task_revision", json.loads(shown.stderr)["error"])

    def test_reopen_requires_completed_state_and_matching_owner(self) -> None:
        not_done = self.run_cli(
            TASKCTL,
            "reopen",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--reason",
            "合同改变",
        )
        self.assertEqual(not_done.returncode, 2)
        self.assertIn("only a completed", json.loads(not_done.stderr)["error"])
        completed = self.complete_t001()
        wrong_owner = self.run_cli(
            TASKCTL,
            "reopen",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-b",
            "--reason",
            "合同改变",
            "--expected-state-revision",
            str(completed["state"]["revision"]),
        )
        self.assertEqual(wrong_owner.returncode, 2)
        self.assertIn("owned by agent-a", json.loads(wrong_owner.stderr)["error"])

    def test_complete_recovers_matching_orphan_result(self) -> None:
        claimed = self.run_task("claim", "--id", "T001", "--owner", "agent-a")
        started = self.run_task(
            "start",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--expected-state-revision",
            str(claimed["state"]["revision"]),
        )
        orphan = self.root / "results" / f"T001.r{started['state']['revision'] + 1}.json"
        orphan.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result_file = Path(self.temp.name) / "retry-result.json"
        result_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        completed = self.run_task(
            "complete",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--expected-state-revision",
            str(started["state"]["revision"]),
        )
        self.assertTrue(completed["recovered_partial_write"])
        self.assertEqual(completed["state"]["status"], "done")

    def test_add_recovers_matching_partial_task_record(self) -> None:
        task = self.task("T020", "恢复部分写入", ["SOL-001"])
        task_path = self.root / "tasks" / "T020.json"
        task_path.write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        candidate = Path(self.temp.name) / "T020.json"
        candidate.write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        added = self.run_task("add", "--file", str(candidate))
        self.assertTrue(added["recovered_partial_write"])
        self.assertTrue((self.root / "state" / "T020.json").exists())

    def test_init_refuses_nonempty_managed_storage(self) -> None:
        other = Path(self.temp.name) / "occupied-task-workspace"
        (other / "state").mkdir(parents=True)
        (other / "state" / "sentinel.json").write_text("{}", encoding="utf-8")
        initialized = self.run_cli(
            TASKCTL,
            "init",
            "--task-dir",
            str(other),
            "--id",
            "occupied",
            "--title",
            "不可覆盖",
        )
        self.assertEqual(initialized.returncode, 2)
        self.assertIn("refusing to overwrite", json.loads(initialized.stderr)["error"])

    def test_completion_snapshot_rejects_cross_page_state_change(self) -> None:
        first = self.run_task("completion-context", "--limit", "1", "--budget", "12000")
        cursor = first["pagination"]["target_next_after_id"]
        self.assertIsNotNone(cursor)
        self.run_task("claim", "--id", "T001", "--owner", "agent-a")
        continued = self.run_cli(
            TASKCTL,
            "completion-context",
            "--task-dir",
            str(self.root),
            "--after-id",
            cursor,
            "--snapshot-id",
            first["snapshot_id"],
        )
        self.assertEqual(continued.returncode, 2)
        self.assertIn("snapshot changed", json.loads(continued.stderr)["error"])

    def test_owned_active_task_contract_requires_owner_and_state_revision(self) -> None:
        claimed = self.run_task("claim", "--id", "T001", "--owner", "agent-a")
        candidate = Path(self.temp.name) / "owned-update.json"
        candidate.write_text(
            json.dumps(
                self.task("T001", "调整活动合同", ["SOL-001"]),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        missing_owner = self.run_cli(
            TASKCTL,
            "update",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate),
            "--expected-task-revision",
            "1",
        )
        self.assertEqual(missing_owner.returncode, 2)
        self.assertIn("requires --owner", json.loads(missing_owner.stderr)["error"])
        wrong_owner = self.run_cli(
            TASKCTL,
            "update",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate),
            "--expected-task-revision",
            "1",
            "--owner",
            "agent-b",
            "--expected-state-revision",
            str(claimed["state"]["revision"]),
        )
        self.assertEqual(wrong_owner.returncode, 2)
        self.assertIn("owned by agent-a", json.loads(wrong_owner.stderr)["error"])
        updated = self.run_task(
            "update",
            "--file",
            str(candidate),
            "--expected-task-revision",
            "1",
            "--owner",
            "agent-a",
            "--expected-state-revision",
            str(claimed["state"]["revision"]),
        )
        self.assertEqual(updated["task_revision"], 2)

    def test_result_history_is_derived_and_not_limited_to_200_entries(self) -> None:
        state_path = self.root / "state" / "T001.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["revision"] = 203
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for revision in range(2, 203):
            path = self.root / "results" / f"T001.r{revision}.json"
            path.write_text(
                json.dumps(self.result_payload(), ensure_ascii=False), encoding="utf-8"
            )
        shown = self.run_task("show", "--id", "T001", "--budget", "5000")
        self.assertIsNone(shown["result"])

    def test_result_history_revision_cannot_be_far_ahead_of_task_state(self) -> None:
        invalid = self.root / "results" / "T001.r999.json"
        invalid.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False), encoding="utf-8"
        )
        shown = self.run_cli(
            TASKCTL, "show", "--task-dir", str(self.root), "--id", "T001"
        )
        self.assertEqual(shown.returncode, 2)
        self.assertIn("ahead of task state", json.loads(shown.stderr)["error"])

    def test_invalid_result_history_record_is_rejected(self) -> None:
        invalid = self.root / "results" / "T001.rbad.json"
        invalid.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False), encoding="utf-8"
        )
        shown = self.run_cli(
            TASKCTL, "show", "--task-dir", str(self.root), "--id", "T001"
        )
        self.assertEqual(shown.returncode, 2)
        self.assertIn("invalid task result history name", json.loads(shown.stderr)["error"])

    def test_context_reports_collection_truncation(self) -> None:
        self.add_task(
            self.task(
                "T030",
                "后继一",
                ["SOL-001"],
                dependencies=[{"id": "T001", "type": "ordering", "consumes": []}],
            )
        )
        self.add_task(
            self.task(
                "T031",
                "后继二",
                ["SOL-001"],
                dependencies=[{"id": "T001", "type": "ordering", "consumes": []}],
            )
        )
        context = self.run_task(
            "context", "--id", "T001", "--max-items", "1", "--budget", "8000"
        )
        self.assertTrue(context["truncated"])
        self.assertTrue(context["truncation"]["dependents"])

    def test_scope_overlap_handles_leading_and_embedded_globs(self) -> None:
        module = load_taskctl_module()
        self.assertTrue(module.scopes_overlap(["**/*"], ["src/file.py"]))
        self.assertTrue(module.scopes_overlap(["src/a*.py"], ["src/abc.py"]))
        self.assertFalse(module.scopes_overlap(["src/a/**"], ["src/b/**"]))

    def test_deep_acyclic_chain_is_iterative(self) -> None:
        module = load_taskctl_module()
        tasks = {}
        for index in range(3000):
            task_id = f"T{index:04d}"
            dependency = []
            if index:
                dependency = [
                    {"id": f"T{index - 1:04d}", "type": "hard", "consumes": []}
                ]
            tasks[task_id] = {"dependencies": dependency}
        module.ensure_acyclic(tasks)

    def test_fit_payload_accounts_for_truncation_metadata_in_budget(self) -> None:
        module = load_taskctl_module()
        payload = {"ok": True, "command": "context", "body": "x" * 950}
        fitted = module.fit_payload(payload, 1000)
        self.assertLessEqual(len(module.compact_json(fitted)), 1000)

    def test_workspace_lock_file_does_not_grow_per_operation(self) -> None:
        module = load_taskctl_module()
        with module.workspace_lock(self.root):
            pass
        first_size = (self.root / ".work-cache" / "workspace.lock").stat().st_size
        with module.workspace_lock(self.root):
            pass
        second_size = (self.root / ".work-cache" / "workspace.lock").stat().st_size
        self.assertEqual((first_size, second_size), (1, 1))


if __name__ == "__main__":
    unittest.main()
