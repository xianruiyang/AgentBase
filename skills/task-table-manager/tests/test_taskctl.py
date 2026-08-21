from __future__ import annotations

import json
import importlib.util
import os
import re
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
        arguments = list(args)
        if "--view" not in arguments and not any(
            argument.startswith("--view=") for argument in arguments
        ):
            arguments.extend(["--view", "machine"])
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(script), *arguments],
            text=True,
            capture_output=True,
            encoding="utf-8",
            env=environment,
            check=False,
        )

    def run_default_cli(
        self, script: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment.pop("PYTHONUTF8", None)
        environment.pop("PYTHONIOENCODING", None)
        return subprocess.run(
            [sys.executable, str(script), *args],
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
        arguments = list(args)
        command = arguments[0] if arguments else ""
        if command in {"claim", "start", "note", "complete", "reopen", "release"}:
            if "--expected-state-revision" not in arguments and "--id" in arguments:
                task_id = arguments[arguments.index("--id") + 1]
                state_path = self.root / "state" / f"{task_id}.json"
                if state_path.is_file():
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    arguments.extend(
                        ["--expected-state-revision", str(state["revision"])]
                    )
        if command == "complete" and "--expected-task-revision" not in arguments:
            if "--id" in arguments:
                task_id = arguments[arguments.index("--id") + 1]
                task_path = self.root / "tasks" / f"{task_id}.json"
                if task_path.is_file():
                    task = json.loads(task_path.read_text(encoding="utf-8"))
                    arguments.extend(
                        ["--expected-task-revision", str(task["revision"])]
                    )
        if command == "update" and "--expected-task-revision" not in arguments:
            if "--file" in arguments:
                candidate_path = Path(arguments[arguments.index("--file") + 1])
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                task_path = self.root / "tasks" / f"{candidate['id']}.json"
                if task_path.is_file():
                    task = json.loads(task_path.read_text(encoding="utf-8"))
                    arguments.extend(
                        ["--expected-task-revision", str(task["revision"])]
                    )
        return self.run_ok(TASKCTL, *arguments, "--task-dir", str(self.root))

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
        }

    def legacy_task_payload(self, task: dict, revision: int = 1) -> dict:
        return {"schema": "task.record", **task, "revision": revision}

    def add_task(self, task: dict) -> dict:
        candidate = Path(self.temp.name) / f"{task['id']}.json"
        candidate.write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.run_task("add", "--file", str(candidate))

    def result_payload(self) -> dict:
        return {
            "outcome": "导出职责已经实现",
            "outputs": ["正式导出接口"],
            "changed_files": ["src/export/service.py"],
            "verification": ["真实调用并读回通过"],
            "unresolved": [],
            "invalidated_source_ids": [],
            "evidence_for": ["SOL-001"],
            "evidence_refs": [
                {"ref": "tests/export-readback", "kind": "test", "note": "真实读回"}
            ],
        }

    def legacy_result_payload(self, task_id: str = "T001") -> dict:
        return {
            "schema": "task.result",
            "task_id": task_id,
            "task_revision": 1,
            **self.result_payload(),
        }

    def read_snapshot(self, reference: str) -> dict:
        digest = reference.removeprefix("sha256:")
        return json.loads(
            (self.root / "snapshots" / f"{digest}.json").read_text(encoding="utf-8")
        )

    def assert_completion_snapshot_gate(
        self, result_file: Path, reference: str, issue_kind: str
    ) -> None:
        task = json.loads(
            (self.root / "tasks" / "T001.json").read_text(encoding="utf-8")
        )
        state_path = self.root / "state" / "T001.json"
        state_before = json.loads(state_path.read_text(encoding="utf-8"))
        results_before = sorted((self.root / "results").glob("*.json"))
        failed = self.run_cli(
            TASKCTL,
            "complete",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--source-snapshot-ref",
            reference,
            "--expected-task-revision",
            str(task["revision"]),
            "--expected-state-revision",
            str(state_before["revision"]),
        )
        self.assertEqual(failed.returncode, 2, failed.stdout)
        payload = json.loads(failed.stderr)
        self.assertEqual(payload["gate"]["id"], "TASK-INPUT-UNREADABLE")
        self.assertEqual(payload["gate"]["scope"], "current completion write")
        self.assertIn(issue_kind, payload["error"])
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8")), state_before
        )
        self.assertEqual(sorted((self.root / "results").glob("*.json")), results_before)

    def complete_t001(self) -> dict:
        context = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
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
        result = self.result_payload()
        result_file = Path(self.temp.name) / "T001-result.json"
        result_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
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
            "--source-snapshot-ref",
            context["source_snapshot_ref"],
            "--expected-state-revision",
            str(started["state"]["revision"]),
        )

    def test_default_model_view_is_sparse_and_machine_is_explicit(self) -> None:
        model = self.run_default_cli(
            TASKCTL, "status", "--task-dir", str(self.root)
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("tasks:", model.stdout)
        self.assertNotIn('"command"', model.stdout)
        self.assertNotIn('"ok"', model.stdout)
        self.assertFalse(model.stdout.lstrip().startswith("{"))

        machine = self.run_cli(
            TASKCTL, "status", "--task-dir", str(self.root)
        )
        self.assertEqual(machine.returncode, 0, machine.stderr)
        payload = json.loads(machine.stdout)
        self.assertEqual(payload["task_count"], 2)
        self.assertIn("total:2", model.stdout)

    def test_contract_write_model_receipt_omits_machine_defaults(self) -> None:
        candidate = self.task("T003", "补充交付", ["SOL-001"])
        candidate_file = Path(self.temp.name) / "T003.json"
        candidate_file.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        model = self.run_default_cli(
            TASKCTL,
            "add",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate_file),
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertEqual(
            model.stdout.strip().splitlines(),
            ["task_id:T003", "task_revision:1", "state_revision:1"],
        )
        self.assertNotIn("recovered_partial_write:false", model.stdout)
        self.assertNotIn("diagnostic_count:0", model.stdout)

        stored_task = json.loads(
            (self.root / "tasks" / "T003.json").read_text(encoding="utf-8")
        )
        stored_state = json.loads(
            (self.root / "state" / "T003.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored_task["schema"], "task.record")
        self.assertEqual(stored_task["revision"], 1)
        self.assertEqual(stored_state["schema"], "task.state")
        self.assertEqual(stored_state["task_id"], "T003")
        self.assertIsNone(stored_state["started_at"])
        self.assertIsNone(stored_state["ended_at"])

    def test_state_write_model_receipt_omits_state_envelope_and_zero_counts(self) -> None:
        model = self.run_default_cli(
            TASKCTL,
            "claim",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--expected-state-revision",
            "1",
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertEqual(
            model.stdout.strip().splitlines(),
            ["id:T001", "state:{status:claimed,owner:agent-a,revision:2}"],
        )
        self.assertNotIn("schema", model.stdout)
        self.assertNotIn("task_id", model.stdout)
        self.assertNotIn("warning_count:0", model.stdout)
        self.assertNotIn("diagnostic_count:0", model.stdout)

        stored = json.loads(
            (self.root / "state" / "T001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored["schema"], "task.state")
        self.assertEqual(stored["task_id"], "T001")
        self.assertEqual(stored["revision"], 2)

    def test_state_timestamps_follow_execution_lifecycle_and_render(self) -> None:
        claimed = self.run_task("claim", "--id", "T001", "--owner", "agent-a")
        self.assertIsNone(claimed["state"]["started_at"])
        self.assertIsNone(claimed["state"]["ended_at"])

        started = self.run_task(
            "start",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--expected-state-revision",
            str(claimed["state"]["revision"]),
        )
        started_at = started["state"]["started_at"]
        self.assertRegex(started_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertIsNone(started["state"]["ended_at"])

        state_path = self.root / "state" / "T001.json"
        state_before_contract_update = json.loads(
            state_path.read_text(encoding="utf-8")
        )
        revised_task = self.task(
            "T001", "实现导出职责修订", ["SOL-001"], scope=["src/export/**"]
        )
        revised_file = Path(self.temp.name) / "T001-revised.json"
        revised_file.write_text(
            json.dumps(revised_task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.run_task("update", "--file", str(revised_file), "--owner", "agent-a")
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8")),
            state_before_contract_update,
        )

        blocked = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--blocked-reason",
            "等待输入",
            "--expected-state-revision",
            str(started["state"]["revision"]),
        )
        self.assertEqual(blocked["state"]["started_at"], started_at)
        self.assertIsNone(blocked["state"]["ended_at"])

        completed = self.complete_t001()
        ended_at = completed["state"]["ended_at"]
        self.assertEqual(completed["state"]["started_at"], started_at)
        self.assertRegex(ended_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        self.run_task("render")
        rendered = (self.root / "TASK_TABLE.md").read_text(encoding="utf-8")
        self.assertIn("| ID | 状态 | Owner | 开始时间 | 结束时间 |", rendered)
        self.assertIn(started_at, rendered)
        self.assertIn(ended_at, rendered)

        reopened = self.run_task(
            "reopen",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--reason",
            "需要修订",
        )
        self.assertEqual(reopened["state"]["started_at"], started_at)
        self.assertIsNone(reopened["state"]["ended_at"])

        retired = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--status",
            "retired",
            "--message",
            "由新任务替代",
        )
        self.assertEqual(retired["state"]["started_at"], started_at)
        self.assertRegex(
            retired["state"]["ended_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )

        released = self.run_task(
            "release", "--id", "T001", "--owner", "agent-a"
        )
        self.assertEqual(released["state"]["started_at"], started_at)
        self.assertIsNone(released["state"]["ended_at"])

    def test_legacy_state_timestamps_remain_unknown_until_a_real_transition(self) -> None:
        state_path = self.root / "state" / "T001.json"
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy.pop("started_at")
        legacy.pop("ended_at")
        state_path.write_text(
            json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        shown = self.run_task("show", "--id", "T001")
        self.assertIsNone(shown["state"]["started_at"])
        self.assertIsNone(shown["state"]["ended_at"])
        unchanged = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertNotIn("started_at", unchanged)
        self.assertNotIn("ended_at", unchanged)

        claimed = self.run_task("claim", "--id", "T001", "--owner", "agent-a")
        self.assertIsNone(claimed["state"]["started_at"])
        self.assertIsNone(claimed["state"]["ended_at"])
        stored = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIsNone(stored["started_at"])
        self.assertIsNone(stored["ended_at"])

    def test_complete_model_receipt_keeps_only_visible_issues_and_total_overflow(
        self,
    ) -> None:
        module = load_taskctl_module()
        payload = {
            "ok": True,
            "command": "complete",
            "id": "T001",
            "state": {
                "schema": "task.state",
                "task_id": "T001",
                "status": "done",
                "owner": "agent-a",
                "note": "",
                "blocked_reason": "",
                "next_action": "",
                "result_ref": "results/T001.r4.json",
                "started_at": "2026-08-21T10:00:00Z",
                "ended_at": "2026-08-21T10:05:00Z",
                "revision": 4,
            },
            "result_ref": "results/T001.r4.json",
            "recovered_partial_write": False,
            "diagnostics": [{"kind": "first"}, {"kind": "second"}],
            "diagnostic_count": 3,
        }

        projected = module.task_model_projection(payload)
        self.assertEqual(
            projected,
            {
                "id": "T001",
                "state": {
                    "status": "done",
                    "owner": "agent-a",
                    "started_at": "2026-08-21T10:00:00Z",
                    "ended_at": "2026-08-21T10:05:00Z",
                    "revision": 4,
                },
                "result_ref": "results/T001.r4.json",
                "diagnostics": [{"kind": "first"}, {"kind": "second"}],
                "diagnostic_count": 3,
            },
        )

    def test_render_model_receipt_reuses_sparse_status_summary(self) -> None:
        model = self.run_default_cli(
            TASKCTL, "render", "--task-dir", str(self.root)
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("output:", model.stdout)
        self.assertIn("tasks:{total:2,states:{todo:2}}", model.stdout)
        self.assertNotIn("results:", model.stdout)
        self.assertNotIn("_count:0", model.stdout)

        machine = self.run_cli(TASKCTL, "render", "--task-dir", str(self.root))
        self.assertEqual(machine.returncode, 0, machine.stderr)
        payload = json.loads(machine.stdout)
        self.assertEqual(payload["task_count"], 2)
        self.assertEqual(payload["results"]["referenced_result_count"], 0)

    def test_show_model_removes_repeated_record_envelopes(self) -> None:
        self.complete_t001()
        model = self.run_default_cli(
            TASKCTL, "show", "--task-dir", str(self.root), "--id", "T001"
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("id:T001", model.stdout)
        self.assertIn("task:", model.stdout)
        self.assertIn("state:", model.stdout)
        self.assertIn("result:", model.stdout)
        self.assertIn("task_revision:1", model.stdout)
        self.assertIn("source_snapshot_count:", model.stdout)
        self.assertNotIn("schema:", model.stdout)
        self.assertNotIn("task_id:", model.stdout)
        self.assertNotIn("current_for_task_revision:true", model.stdout)
        self.assertNotIn("source_snapshot:", model.stdout)

        machine = self.run_cli(
            TASKCTL, "show", "--task-dir", str(self.root), "--id", "T001"
        )
        self.assertEqual(machine.returncode, 0, machine.stderr)
        payload = json.loads(machine.stdout)
        self.assertEqual(payload["task"]["schema"], "task.record")
        self.assertEqual(payload["state"]["schema"], "task.state")
        self.assertEqual(payload["result"]["schema"], "task.result")

    def test_list_model_keeps_nonzero_state_summary_without_page_defaults(self) -> None:
        model = self.run_default_cli(
            TASKCTL, "list", "--task-dir", str(self.root), "--limit", "10"
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("counts:{todo:2}", model.stdout)
        self.assertIn("items:", model.stdout)
        self.assertNotIn("matched_count", model.stdout)
        self.assertNotIn("truncated:false", model.stdout)
        self.assertNotIn("diagnostic_count:0", model.stdout)
        self.assertNotIn("done:0", model.stdout)

    def test_empty_relation_and_next_queries_keep_semantic_zero(self) -> None:
        dependencies = self.run_default_cli(
            TASKCTL,
            "deps",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
        )
        self.assertEqual(dependencies.returncode, 0, dependencies.stderr)
        self.assertEqual(
            dependencies.stdout.strip().splitlines(),
            ["id:T001", "dependency_count:0"],
        )

        module = load_taskctl_module()
        projected = module.task_model_projection(
            {
                "ok": True,
                "command": "next",
                "items": [],
                "candidate_count": 0,
                "recommended_count": 0,
                "next_after_id": None,
                "truncated": False,
                "diagnostics": [],
                "diagnostic_count": 0,
            }
        )
        self.assertEqual(module.render_model(projected), "candidate_count:0")

    def test_impact_entry_supports_its_declared_query_contract(self) -> None:
        model = self.run_default_cli(
            TASKCTL,
            "impact",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--limit",
            "10",
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("id:T001", model.stdout)
        self.assertIn("id:T002", model.stdout)
        self.assertNotIn("dependent_count", model.stdout)
        self.assertNotIn("truncated:false", model.stdout)

        continued = self.run_default_cli(
            TASKCTL,
            "impact",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--after-id",
            "T002",
        )
        self.assertEqual(continued.returncode, 0, continued.stderr)
        self.assertEqual(
            continued.stdout.strip().splitlines(),
            ["id:T001", "dependent_count:1"],
        )

    def test_context_model_budget_preserves_core_and_provenance(self) -> None:
        model = self.run_default_cli(
            TASKCTL,
            "context",
            "--id",
            "T001",
            "--task-dir",
            str(self.root),
            "--model-token-budget",
            "2048",
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("task:", model.stdout)
        self.assertIn("实现导出职责", model.stdout)
        self.assertIn("source_snapshot:", model.stdout)
        self.assertIn("complete:true", model.stdout)
        self.assertIn("capture:context --capture", model.stdout)
        self.assertNotIn("sha256:", model.stdout)
        module = load_taskctl_module()
        self.assertLessEqual(module.model_text_cost(model.stdout.rstrip()), 2048)

        captured = self.run_default_cli(
            TASKCTL,
            "context",
            "--id",
            "T001",
            "--task-dir",
            str(self.root),
            "--capture",
            "--model-token-budget",
            "2048",
        )
        self.assertEqual(captured.returncode, 0, captured.stderr)
        match = re.search(r'ref:"(sha256:[0-9a-f]{64})"', captured.stdout)
        self.assertIsNotNone(match, captured.stdout)
        snapshot = self.read_snapshot(match.group(1))
        self.assertEqual(len(snapshot["sources"]), 7)

        constrained = self.run_default_cli(
            TASKCTL,
            "context",
            "--id",
            "T001",
            "--task-dir",
            str(self.root),
            "--model-token-budget",
            "256",
        )
        self.assertEqual(constrained.returncode, 0, constrained.stderr)
        self.assertIn("more:", constrained.stdout)
        self.assertTrue(
            "task:" in constrained.stdout or "id: T001" in constrained.stdout
        )
        self.assertNotEqual(
            constrained.stdout.strip(),
            "hint: increase --budget or use show/deps/context with a narrower target",
        )
        self.assertLessEqual(
            module.model_text_cost(constrained.stdout.rstrip()), 256
        )

    def test_captured_snapshot_matches_final_budgeted_model_upstream(self) -> None:
        captured = None
        for budget in (1536, 1280, 1024, 768, 512):
            candidate = self.run_default_cli(
                TASKCTL,
                "context",
                "--id",
                "T001",
                "--task-dir",
                str(self.root),
                "--capture",
                "--model-token-budget",
                str(budget),
            )
            self.assertEqual(candidate.returncode, 0, candidate.stderr)
            if "complete:false" in candidate.stdout and 'ref:"sha256:' in candidate.stdout:
                captured = candidate
                break
        self.assertIsNotNone(captured, "no budget produced a recoverable partial context")
        match = re.search(r'ref:"(sha256:[0-9a-f]{64})"', captured.stdout)
        self.assertIsNotNone(match, captured.stdout)
        snapshot = self.read_snapshot(match.group(1))
        visible_ids = set(
            re.findall(
                r'- \{id:((?:REQ|AC|CON|UDES|DEC|DES|OBS|GAP|SOL|DCR)-[A-Za-z0-9._-]+)',
                captured.stdout,
            )
        )
        self.assertEqual(set(snapshot["sources"]), visible_ids)
        self.assertGreater(len(visible_ids), 0)
        self.assertLess(len(visible_ids), 7)
        self.assertIn("upstream_ids", captured.stdout)

    def test_capture_deduplicates_identical_source_maps(self) -> None:
        first = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        second = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        self.assertEqual(first["source_snapshot_ref"], second["source_snapshot_ref"])
        self.assertEqual(len(list((self.root / "snapshots").glob("*.json"))), 1)

    def test_capture_upgrades_legacy_workspace_without_snapshot_manifest(self) -> None:
        table_path = self.root / "task-table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table.pop("snapshot_dir")
        table_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.root / "snapshots").rmdir()

        captured = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )

        self.assertRegex(captured["source_snapshot_ref"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue((self.root / "snapshots").is_dir())
        self.assertEqual(
            self.read_snapshot(captured["source_snapshot_ref"])["sources"],
            captured["source_snapshot"],
        )

    def test_completion_model_omits_full_source_snapshot(self) -> None:
        self.complete_t001()
        machine = self.run_task(
            "completion-context", "--target-id", "REQ-001", "--budget", "12000"
        )
        self.assertTrue(
            machine["candidate_tasks"]["T001"]["source_snapshot"]
        )
        model = self.run_default_cli(
            TASKCTL,
            "completion-context",
            "--target-id",
            "REQ-001",
            "--task-dir",
            str(self.root),
            "--model-token-budget",
            "4096",
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("targets:", model.stdout)
        self.assertIn("candidates:", model.stdout)
        self.assertNotIn("source_snapshot:", model.stdout)
        self.assertIn("verification:", model.stdout)

    def test_model_error_keeps_gate_and_recovery(self) -> None:
        result = self.run_default_cli(
            TASKCTL, "show", "--id", "UNKNOWN", "--task-dir", str(self.root)
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        self.assertIn("gate:", result.stderr)
        self.assertIn("recovery:", result.stderr)
        self.assertNotIn('"ok"', result.stderr)

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
        self.assertEqual(status["results"]["referenced_result_count"], 0)

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

    def test_note_on_completed_task_preserves_readable_result(self) -> None:
        completed = self.complete_t001()
        noted = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--message",
            "补充交付说明",
            "--expected-state-revision",
            str(completed["state"]["revision"]),
        )
        self.assertEqual(noted["state"]["status"], "done")
        self.assertEqual(noted["state"]["result_ref"], completed["result_ref"])
        shown = self.run_task("show", "--id", "T001")
        self.assertEqual(shown["result"]["outcome"], "导出职责已经实现")
        self.assertNotIn(
            "current_result_unreadable",
            {item["kind"] for item in shown["diagnostics"]},
        )

    def test_blocked_reason_and_status_remain_consistent(self) -> None:
        started = self.run_task("start", "--id", "T001", "--owner", "agent-a")
        blocked = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--blocked-reason",
            "等待外部输入",
            "--expected-state-revision",
            str(started["state"]["revision"]),
        )
        self.assertEqual(blocked["state"]["status"], "blocked")
        self.assertEqual(blocked["state"]["blocked_reason"], "等待外部输入")

        resumed = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--status",
            "in_progress",
            "--expected-state-revision",
            str(blocked["state"]["revision"]),
        )
        self.assertEqual(resumed["state"]["status"], "in_progress")
        self.assertEqual(resumed["state"]["blocked_reason"], "")

    def test_damaged_blocked_state_combinations_are_diagnostic(self) -> None:
        state_path = self.root / "state" / "T001.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["status"] = "blocked"
        state["owner"] = "agent-a"
        state["blocked_reason"] = ""
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        listed = self.run_cli(TASKCTL, "list", "--task-dir", str(self.root))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        payload = json.loads(listed.stdout)
        self.assertIn(
            "blocked_reason_missing",
            {item["kind"] for item in payload["diagnostics"]},
        )

    def test_release_reports_an_unowned_task_and_clears_execution_fields(self) -> None:
        unowned = self.run_cli(
            TASKCTL,
            "release",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--expected-state-revision",
            "1",
        )
        self.assertEqual(unowned.returncode, 0, unowned.stderr)
        unowned_payload = json.loads(unowned.stdout)
        self.assertIn(
            "unowned_task_released",
            {item["kind"] for item in unowned_payload["diagnostics"]},
        )

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
        referenced_candidate_ids = set()
        for target in completion["targets"]:
            self.assertGreaterEqual(target["candidate_result_count"], 1)
            self.assertNotIn("candidate_tasks", target)
            referenced_candidate_ids.update(target["candidate_task_ids"])
            self.assertTrue(
                set(target["candidate_task_ids"]).issubset(completion["candidate_tasks"])
            )
        self.assertEqual(set(completion["candidate_tasks"]), referenced_candidate_ids)
        self.assertLess(
            len(completion["candidate_tasks"]),
            sum(
                target["returned_candidate_task_count"]
                for target in completion["targets"]
            ),
        )
        for task_id, candidate in completion["candidate_tasks"].items():
            self.assertNotIn("id", candidate)
            self.assertTrue(task_id.startswith("T"))
        self.assertNotIn("passed", completion)
        self.assertNotIn("pass", completion)

    def test_completion_records_structured_evidence_and_source_snapshot(self) -> None:
        completed = self.complete_t001()
        result_path = self.root / completed["result_ref"]
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["schema"], "task.result")
        self.assertEqual(result["task_id"], "T001")
        self.assertEqual(result["task_revision"], 1)
        self.assertEqual(result["evidence_for"], ["SOL-001"])
        self.assertEqual(result["evidence_refs"][0]["kind"], "test")
        self.assertNotIn("source_snapshot", result)
        snapshot = self.read_snapshot(result["source_snapshot_ref"])
        self.assertIn("SOL-001", snapshot["sources"])
        self.assertIn("REQ-001", snapshot["sources"])

        with (self.root / "solution.md").open("a", encoding="utf-8") as handle:
            handle.write("\n结果形成后上游文档变化。\n")
        self.run_ok(WORKCTL, "index", "--work-dir", str(self.root))
        completion = self.run_task(
            "completion-context", "--target-id", "REQ-001", "--budget", "12000"
        )
        self.assertIn("T001", completion["targets"][0]["candidate_task_ids"])
        task_row = completion["candidate_tasks"]["T001"]
        self.assertIn(
            "result_source_snapshot_stale",
            {item["kind"] for item in task_row["result_diagnostics"]},
        )
        summary = completion["diagnostic_summary"]
        self.assertEqual(summary["query_diagnostic_count"], 0)
        self.assertEqual(summary["candidate_result_with_diagnostics_count"], 1)
        self.assertEqual(summary["candidate_source_snapshot_issue_result_count"], 1)
        self.assertEqual(summary["candidate_result_diagnostic_count"], 1)
        self.assertEqual(
            summary["candidate_result_diagnostic_kind_counts"],
            {"result_source_snapshot_stale": 1},
        )
        self.assertEqual(summary["total_diagnostic_count"], 1)
        self.assertNotIn("diagnostics", completion)
        self.assertNotIn("diagnostic_count", completion)
        status = self.run_task("status")
        self.assertEqual(status["results"]["referenced_result_count"], 1)
        self.assertEqual(status["results"]["result_with_diagnostics_count"], 1)
        self.assertEqual(status["results"]["task_revision_stale_result_count"], 0)
        self.assertEqual(status["results"]["source_snapshot_issue_result_count"], 1)
        self.assertEqual(status["results"]["result_diagnostic_count"], 1)
        self.assertEqual(status["diagnostic_count"], 1)

    def test_legacy_result_envelope_is_normalized_by_the_only_write_entry(self) -> None:
        context = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        result_file = Path(self.temp.name) / "legacy-result-envelope.json"
        result_file.write_text(
            json.dumps(self.legacy_result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        completed = self.run_task(
            "complete",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--source-snapshot-ref",
            context["source_snapshot_ref"],
        )
        self.assertIn(
            "legacy_result_envelope_normalized",
            {item["kind"] for item in completed["diagnostics"]},
        )
        stored = json.loads(
            (self.root / completed["result_ref"]).read_text(encoding="utf-8")
        )
        self.assertEqual(stored["schema"], "task.result")
        self.assertEqual(stored["task_id"], "T001")
        self.assertEqual(stored["task_revision"], 1)
        self.assertNotIn("source_snapshot", stored)

    def test_completion_preserves_execution_snapshot_and_diagnoses_missing_snapshot(self) -> None:
        context = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        self.assertTrue(context["source_snapshot_complete"])
        captured = context["source_snapshot"]
        with (self.root / "solution.md").open("a", encoding="utf-8") as handle:
            handle.write("\n执行读取后方案发生变化。\n")

        result = self.result_payload()
        result_file = Path(self.temp.name) / "captured-result.json"
        result_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        completed = self.run_task(
            "complete",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--source-snapshot-ref",
            context["source_snapshot_ref"],
        )
        kinds = {item["kind"] for item in completed["diagnostics"]}
        self.assertIn("result_source_snapshot_stale", kinds)
        stored = json.loads((self.root / completed["result_ref"]).read_text(encoding="utf-8"))
        self.assertNotIn("source_snapshot", stored)
        self.assertEqual(stored["source_snapshot_ref"], context["source_snapshot_ref"])
        self.assertEqual(self.read_snapshot(stored["source_snapshot_ref"])["sources"], captured)

        self.add_task(self.task("T003", "记录无快照结果", ["REQ-001"]))
        missing_file = Path(self.temp.name) / "missing-snapshot-result.json"
        missing_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        missing = self.run_task(
            "complete",
            "--id",
            "T003",
            "--owner",
            "agent-a",
            "--result-file",
            str(missing_file),
        )
        missing_kinds = {item["kind"] for item in missing["diagnostics"]}
        self.assertIn("result_source_snapshot_missing", missing_kinds)
        missing_stored = json.loads(
            (self.root / missing["result_ref"]).read_text(encoding="utf-8")
        )
        self.assertNotIn("source_snapshot", missing_stored)
        self.assertNotIn("source_snapshot_ref", missing_stored)

        self.add_task(self.task("T004", "记录部分来源快照", ["REQ-001"]))
        partial_context = self.run_task("context", "--id", "T004", "--budget", "12000")
        partial_result = self.legacy_result_payload("T004")
        partial_result["source_snapshot"] = {
            "REQ-001": partial_context["source_snapshot"]["REQ-001"]
        }
        partial_file = Path(self.temp.name) / "partial-snapshot-result.json"
        partial_file.write_text(
            json.dumps(partial_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        partial = self.run_task(
            "complete",
            "--id",
            "T004",
            "--owner",
            "agent-a",
            "--result-file",
            str(partial_file),
        )
        partial_kinds = {item["kind"] for item in partial["diagnostics"]}
        self.assertIn("legacy_inline_source_snapshot_externalized", partial_kinds)
        self.assertIn("result_source_snapshot_incomplete", partial_kinds)
        status = self.run_task("status")
        self.assertEqual(status["results"]["referenced_result_count"], 3)
        self.assertEqual(status["results"]["result_with_diagnostics_count"], 3)
        self.assertEqual(status["results"]["task_revision_stale_result_count"], 0)
        self.assertEqual(status["results"]["source_snapshot_issue_result_count"], 3)
        self.assertEqual(status["results"]["result_diagnostic_count"], 3)
        self.assertEqual(
            status["results"]["result_diagnostic_kind_counts"],
            {
                "result_source_snapshot_incomplete": 1,
                "result_source_snapshot_missing": 1,
                "result_source_snapshot_stale": 1,
            },
        )

    def test_complete_rejects_missing_snapshot_asset_without_mutation(self) -> None:
        context = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        reference = context["source_snapshot_ref"]
        snapshot_path = (
            self.root
            / "snapshots"
            / f"{reference.removeprefix('sha256:')}.json"
        )
        snapshot_path.unlink()
        result_file = Path(self.temp.name) / "missing-asset-result.json"
        result_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.assert_completion_snapshot_gate(
            result_file, reference, "result_source_snapshot_asset_missing"
        )

    def test_snapshot_asset_loss_after_completion_remains_a_diagnostic(self) -> None:
        completed = self.complete_t001()
        stored = json.loads(
            (self.root / completed["result_ref"]).read_text(encoding="utf-8")
        )
        reference = stored["source_snapshot_ref"]
        snapshot_path = (
            self.root
            / "snapshots"
            / f"{reference.removeprefix('sha256:')}.json"
        )
        snapshot_path.unlink()
        shown = self.run_task("show", "--id", "T001", "--budget", "12000")
        self.assertEqual(
            [
                item["kind"]
                for item in shown["diagnostics"]
                if item["kind"] == "result_source_snapshot_asset_missing"
            ],
            ["result_source_snapshot_asset_missing"],
        )
        status = self.run_task("status")
        self.assertEqual(status["results"]["source_snapshot_issue_result_count"], 1)
        self.assertEqual(
            status["results"]["result_diagnostic_kind_counts"],
            {"result_source_snapshot_asset_missing": 1},
        )
        self.assertEqual(status["diagnostic_count"], 1)
        dependent_context = self.run_task(
            "context", "--id", "T002", "--budget", "12000"
        )
        self.assertIn(
            "result_source_snapshot_asset_missing",
            {
                item["kind"]
                for item in dependent_context["dependencies"][0]["diagnostics"]
            },
        )

    def test_complete_rejects_snapshot_asset_identity_mismatch(self) -> None:
        context = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        reference = context["source_snapshot_ref"]
        snapshot_path = (
            self.root
            / "snapshots"
            / f"{reference.removeprefix('sha256:')}.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["sources"]["REQ-001"] = "sha256:" + ("0" * 64)
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result_file = Path(self.temp.name) / "modified-asset-result.json"
        result_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.assert_completion_snapshot_gate(
            result_file,
            reference,
            "result_source_snapshot_asset_identity_mismatch",
        )

    def test_complete_rejects_unreadable_snapshot_asset(self) -> None:
        context = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        reference = context["source_snapshot_ref"]
        snapshot_path = (
            self.root
            / "snapshots"
            / f"{reference.removeprefix('sha256:')}.json"
        )
        snapshot_path.write_text("not-json", encoding="utf-8")
        result_file = Path(self.temp.name) / "invalid-asset-result.json"
        result_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.assert_completion_snapshot_gate(
            result_file, reference, "result_source_snapshot_asset_invalid"
        )

    def test_complete_rejects_competing_snapshot_inputs(self) -> None:
        context = self.run_task(
            "context", "--id", "T001", "--budget", "12000", "--capture"
        )
        result = self.legacy_result_payload()
        result["source_snapshot"] = context["source_snapshot"]
        result_file = Path(self.temp.name) / "conflicting-snapshot-result.json"
        result_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        conflict = self.run_cli(
            TASKCTL,
            "complete",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--source-snapshot-ref",
            context["source_snapshot_ref"],
            "--expected-task-revision",
            "1",
            "--expected-state-revision",
            "1",
            "--task-dir",
            str(self.root),
        )

        self.assertEqual(conflict.returncode, 2)
        payload = json.loads(conflict.stderr)
        self.assertEqual(payload["gate"]["id"], "TASK-SNAPSHOT-CONFLICT")

    def test_historical_inline_snapshot_remains_readable(self) -> None:
        completed = self.complete_t001()
        result_path = self.root / completed["result_ref"]
        stored = json.loads(result_path.read_text(encoding="utf-8"))
        snapshot = self.read_snapshot(stored.pop("source_snapshot_ref"))["sources"]
        stored["source_snapshot"] = snapshot
        result_path.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shown = self.run_task("show", "--id", "T001", "--budget", "12000")
        self.assertEqual(shown["result"]["source_snapshot"], snapshot)
        self.assertNotIn("source_snapshot_ref", shown["result"])
        self.assertNotIn(
            "result_source_snapshot_missing",
            {item["kind"] for item in shown["diagnostics"]},
        )

    def test_completion_context_uses_direct_result_evidence_mapping(self) -> None:
        self.add_task(self.task("T003", "提供直接验收证据", []))
        index = json.loads(
            (self.root / ".work-cache" / "index.json").read_text(encoding="utf-8")
        )
        requirement = next(
            section for section in index["sections"] if section["id"] == "REQ-001"
        )
        result = self.legacy_result_payload("T003")
        result["evidence_for"] = ["REQ-001"]
        result["source_snapshot"] = {"REQ-001": requirement["fingerprint"]}
        result_file = Path(self.temp.name) / "T003-direct-evidence.json"
        result_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.run_task(
            "complete",
            "--id",
            "T003",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
        )
        completion = self.run_task(
            "completion-context", "--target-id", "REQ-001", "--budget", "12000"
        )
        candidate_ids = set(completion["targets"][0]["candidate_task_ids"])
        self.assertIn("T003", candidate_ids)
        self.assertIn("T003", completion["candidate_tasks"])
        stored_result = json.loads(
            next((self.root / "results").glob("T003.r*.json")).read_text(encoding="utf-8")
        )
        self.assertNotIn("source_snapshot", stored_result)
        self.assertIn(
            "REQ-001", self.read_snapshot(stored_result["source_snapshot_ref"])["sources"]
        )

    def test_later_current_evidence_does_not_suppress_stale_predecessor(self) -> None:
        self.complete_t001()
        with (self.root / "solution.md").open("a", encoding="utf-8") as handle:
            handle.write("\n前置结果形成后方案发生变化。\n")
        self.run_ok(WORKCTL, "index", "--work-dir", str(self.root))

        context = self.run_task(
            "context", "--id", "T002", "--budget", "12000", "--capture"
        )
        later_result = self.result_payload()
        later_result["evidence_for"] = ["REQ-001"]
        later_file = Path(self.temp.name) / "T002-current-evidence.json"
        later_file.write_text(
            json.dumps(later_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.run_task(
            "complete",
            "--id",
            "T002",
            "--owner",
            "agent-a",
            "--result-file",
            str(later_file),
            "--source-snapshot-ref",
            context["source_snapshot_ref"],
        )

        completion = self.run_task(
            "completion-context", "--target-id", "REQ-001", "--budget", "12000"
        )
        predecessor = completion["candidate_tasks"]["T001"]
        later = completion["candidate_tasks"]["T002"]
        self.assertIn(
            "result_source_snapshot_stale",
            {item["kind"] for item in predecessor["result_diagnostics"]},
        )
        self.assertEqual(later["result_diagnostics"], [])
        self.assertEqual(later["evidence_for"], ["REQ-001"])
        self.assertEqual(
            completion["diagnostic_summary"][
                "candidate_result_with_diagnostics_count"
            ],
            1,
        )
        self.assertEqual(
            completion["diagnostic_summary"][
                "candidate_source_snapshot_issue_result_count"
            ],
            1,
        )
        self.assertNotIn("resolved_diagnostics", predecessor)
        self.assertNotIn("revalidated_result_refs", later)
        self.assertNotIn("passed", completion)

    def test_completion_context_budget_trimming_keeps_candidate_catalog_closed(self) -> None:
        completion = self.run_task(
            "completion-context", "--limit", "10", "--budget", "2500"
        )
        self.assertGreater(completion["returned_target_count"], 0)
        self.assertLess(completion["returned_target_count"], completion["target_count"])
        referenced = {
            task_id
            for target in completion["targets"]
            for task_id in target["candidate_task_ids"]
        }
        self.assertEqual(set(completion["candidate_tasks"]), referenced)
        self.assertTrue(
            all(
                set(target["candidate_task_ids"]).issubset(
                    completion["candidate_tasks"]
                )
                for target in completion["targets"]
            )
        )
        result_diagnostic_count = sum(
            len(candidate["result_diagnostics"])
            for candidate in completion["candidate_tasks"].values()
            if candidate["result_ref"] is not None
        )
        self.assertEqual(
            completion["diagnostic_summary"]["candidate_result_diagnostic_count"],
            result_diagnostic_count,
        )

    def test_fit_payload_last_resort_preserves_source_fingerprint(self) -> None:
        module = load_taskctl_module()
        fingerprint = "sha256:" + "a" * 64
        payload = {
            "ok": True,
            "command": "completion-context",
            "source_snapshot": {"REQ-001": fingerprint},
            "items": ["x" * 200 for _ in range(10)],
        }
        at_120 = module.shrink_value(payload, 120)
        at_120["truncated"] = True
        at_80 = module.shrink_value(payload, 80)
        at_80["truncated"] = True
        size_120 = len(module.compact_json(at_120))
        size_80 = len(module.compact_json(at_80))
        self.assertLess(size_80, size_120)

        fitted = module.fit_payload(payload, (size_80 + size_120) // 2)
        self.assertNotIn("hint", fitted)
        self.assertTrue(fitted["truncated"])
        self.assertEqual(fitted["source_snapshot"]["REQ-001"], fingerprint)
        self.assertTrue(all(len(item) <= 81 for item in fitted["items"]))

    def test_recursive_dependents_report_consumption_path(self) -> None:
        self.add_task(
            self.task(
                "T003",
                "消费界面结果",
                ["SOL-001"],
                dependencies=[
                    {"id": "T002", "type": "hard", "consumes": ["界面接入结果"]}
                ],
            )
        )
        impact = self.run_task("dependents", "--id", "T001", "--recursive")
        by_id = {item["id"]: item for item in impact["items"]}
        self.assertEqual(by_id["T002"]["path"], ["T001", "T002"])
        self.assertEqual(by_id["T002"]["consumes"], ["导出接口"])
        self.assertEqual(by_id["T003"]["path"], ["T001", "T002", "T003"])
        self.assertEqual(by_id["T003"]["via"], "T002")
        self.assertEqual(by_id["T003"]["consumes"], ["界面接入结果"])

    def test_retired_state_is_preserved_but_not_recommended(self) -> None:
        retired = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--status",
            "retired",
            "--message",
            "由 T002 替代",
        )
        self.assertEqual(retired["state"]["status"], "retired")
        status = self.run_task("status")
        self.assertEqual(status["status_counts"]["retired"], 1)
        next_tasks = self.run_task("next", "--include-blocked")
        self.assertNotIn("T001", {item["id"] for item in next_tasks["items"]})

    def test_non_standard_status_is_preserved_as_a_diagnostic(self) -> None:
        noted = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--status",
            "awaiting_user",
            "--message",
            "等待用户确认",
        )
        self.assertEqual(noted["state"]["status"], "awaiting_user")
        self.assertIn(
            "non_standard_status",
            {item["kind"] for item in noted["diagnostics"]},
        )
        status = self.run_task("status")
        self.assertEqual(status["status_counts"]["awaiting_user"], 1)
        candidates = self.run_task("next", "--include-blocked")
        row = next(item for item in candidates["items"] if item["id"] == "T001")
        self.assertFalse(row["recommended"])

        blank = self.run_task(
            "note",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--status",
            "",
            "--message",
            "文档状态暂未命名",
        )
        self.assertEqual(blank["state"]["status"], "")
        self.assertIn(
            "semantic_text_empty", {item["kind"] for item in blank["diagnostics"]}
        )

    def test_parseable_non_standard_task_values_are_diagnostics(self) -> None:
        task = self.task("T003", "保留外部协调合同", ["custom-goal", "custom-goal"])
        task["title"] = " "
        task["outcome"] = ""
        task["dependencies"] = [
            {"id": "", "type": "custom", "consumes": [""]}
        ]
        task["mutation_scope"] = ["C:/external/**", "C:/external/**"]
        task["outputs"] = ["协调结果", "协调结果"]
        task["reasoning_hint"] = "extreme"
        added = self.add_task(self.legacy_task_payload(task, revision=7))
        kinds = {item["kind"] for item in added["diagnostics"]}
        self.assertTrue(
            {
                "duplicate_task_values",
                "non_standard_source_id",
                "non_standard_dependency_id",
                "non_standard_dependency_type",
                "non_project_relative_mutation_scope",
                "non_standard_reasoning_hint",
                "non_initial_task_revision",
                "semantic_text_empty",
            }.issubset(kinds),
            kinds,
        )
        stored = json.loads(
            (self.root / "tasks" / "T003.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored["source_ids"], ["custom-goal", "custom-goal"])
        self.assertEqual(stored["mutation_scope"], ["C:/external/**", "C:/external/**"])
        self.assertEqual(stored["title"], " ")
        self.assertEqual(stored["outcome"], "")
        self.assertEqual(stored["dependencies"][0]["id"], "")
        self.assertEqual(stored["revision"], 7)

    def test_parseable_non_standard_result_values_are_diagnostics(self) -> None:
        result = self.legacy_result_payload()
        result["outcome"] = ""
        result["changed_files"] = ["C:/external/output.txt"]
        result["evidence_for"] = ["custom-goal"]
        result["evidence_refs"] = [{"ref": ""}]
        result["source_snapshot"] = {"": ""}
        result_file = Path(self.temp.name) / "non-standard-result.json"
        result_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        completed = self.run_task(
            "complete",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--diagnostic-limit",
            "50",
        )
        kinds = {item["kind"] for item in completed["diagnostics"]}
        self.assertIn("non_project_relative_changed_file", kinds)
        self.assertIn("non_standard_result_source_id", kinds)
        self.assertIn("semantic_text_empty", kinds)
        stored = json.loads(
            (self.root / completed["result_ref"]).read_text(encoding="utf-8")
        )
        self.assertEqual(stored["outcome"], "")
        self.assertEqual(stored["evidence_refs"], [{"ref": ""}])

    def test_common_queries_support_cursor_pagination(self) -> None:
        self.add_task(
            self.task(
                "T003",
                "组合依赖",
                ["SOL-001"],
                dependencies=[
                    {"id": "T001", "type": "hard", "consumes": ["接口"]},
                    {"id": "T002", "type": "informational", "consumes": ["界面"]},
                ],
            )
        )
        self.add_task(
            self.task(
                "T004",
                "另一后继",
                ["SOL-001"],
                dependencies=[
                    {"id": "T001", "type": "ordering", "consumes": ["顺序"]}
                ],
            )
        )

        expected_count_fields = {
            "list": "matched_count",
            "next": "candidate_count",
            "deps": "dependency_count",
            "dependents": "dependent_count",
        }
        for command, extra in (
            ("list", ()),
            ("next", ("--include-blocked",)),
            ("deps", ("--id", "T003")),
            ("dependents", ("--id", "T001")),
        ):
            seen: list[str] = []
            after_id: str | None = None
            while True:
                arguments = [command, *extra, "--limit", "1"]
                if after_id is not None:
                    arguments.extend(("--after-id", after_id))
                page = self.run_task(*arguments)
                seen.extend(item["id"] for item in page["items"])
                after_id = page["next_after_id"]
                if after_id is None:
                    self.assertFalse(page["truncated"])
                    break
                self.assertTrue(page["truncated"])
            self.assertEqual(len(seen), len(set(seen)))
            self.assertEqual(len(seen), page[expected_count_fields[command]])

        invalid = self.run_cli(
            TASKCTL,
            "list",
            "--task-dir",
            str(self.root),
            "--after-id",
            "T999",
        )
        self.assertEqual(invalid.returncode, 0, invalid.stderr)
        invalid_payload = json.loads(invalid.stdout)
        self.assertIn(
            "pagination_cursor_reset",
            {item["kind"] for item in invalid_payload["diagnostics"]},
        )

    def test_task_revision_conflict_is_a_gate_and_dependency_cycle_is_diagnostic(self) -> None:
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
        conflict_payload = json.loads(conflict.stderr)
        self.assertIn("revision conflict", conflict_payload["error"])
        self.assertEqual(conflict_payload["gate"]["id"], "TASK-REVISION")

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
        self.assertEqual(cycle.returncode, 0, cycle.stderr)
        self.assertIn(
            "dependency_cycle",
            {item["kind"] for item in json.loads(cycle.stdout)["diagnostics"]},
        )

    def test_existing_record_writes_require_compare_and_swap_revision(self) -> None:
        missing_state_revision = self.run_cli(
            TASKCTL,
            "claim",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
        )
        self.assertEqual(missing_state_revision.returncode, 2)
        state_payload = json.loads(missing_state_revision.stderr)
        self.assertEqual(state_payload["gate"]["id"], "TASK-REVISION")
        self.assertIn("--expected-state-revision", state_payload["gate"]["recovery"])

        candidate = json.loads(
            (self.root / "tasks" / "T001.json").read_text(encoding="utf-8")
        )
        candidate["title"] = "并发安全更新"
        candidate_file = Path(self.temp.name) / "T001-cas-update.json"
        candidate_file.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        missing_task_revision = self.run_cli(
            TASKCTL,
            "update",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate_file),
        )
        self.assertEqual(missing_task_revision.returncode, 2)
        task_payload = json.loads(missing_task_revision.stderr)
        self.assertEqual(task_payload["gate"]["id"], "TASK-REVISION")
        self.assertIn("--expected-task-revision", task_payload["gate"]["recovery"])

    def test_complete_requires_and_compares_the_executed_task_revision(self) -> None:
        result_file = Path(self.temp.name) / "semantic-completion-result.json"
        result_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        state_path = self.root / "state" / "T001.json"
        state_before = json.loads(state_path.read_text(encoding="utf-8"))
        missing = self.run_cli(
            TASKCTL,
            "complete",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--expected-state-revision",
            str(state_before["revision"]),
        )
        self.assertEqual(missing.returncode, 2)
        missing_payload = json.loads(missing.stderr)
        self.assertEqual(missing_payload["gate"]["id"], "TASK-REVISION")
        self.assertIn("--expected-task-revision", missing_payload["gate"]["recovery"])
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8")), state_before
        )
        self.assertEqual(list((self.root / "results").glob("*.json")), [])

        candidate = json.loads(
            (self.root / "tasks" / "T001.json").read_text(encoding="utf-8")
        )
        candidate["title"] = "执行后发生合同修订"
        candidate_file = Path(self.temp.name) / "T001-after-execution.json"
        candidate_file.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.run_task(
            "update",
            "--file",
            str(candidate_file),
            "--expected-task-revision",
            "1",
        )
        conflict = self.run_cli(
            TASKCTL,
            "complete",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--expected-task-revision",
            "1",
            "--expected-state-revision",
            str(state_before["revision"]),
        )
        self.assertEqual(conflict.returncode, 2)
        conflict_payload = json.loads(conflict.stderr)
        self.assertEqual(conflict_payload["gate"]["id"], "TASK-REVISION")
        self.assertIn("different task contract revision", conflict_payload["gate"]["risk"])
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8")), state_before
        )
        self.assertEqual(list((self.root / "results").glob("*.json")), [])

    def test_semantic_completion_input_rejects_machine_owned_fields(self) -> None:
        result = self.result_payload()
        result["task_id"] = "T001"
        result_file = Path(self.temp.name) / "mixed-completion-result.json"
        result_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        failed = self.run_cli(
            TASKCTL,
            "complete",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--expected-task-revision",
            "1",
            "--expected-state-revision",
            "1",
        )
        self.assertEqual(failed.returncode, 2)
        payload = json.loads(failed.stderr)
        self.assertEqual(payload["gate"]["id"], "TASK-INPUT-UNREADABLE")
        self.assertIn("task_id", payload["error"])
        self.assertEqual(list((self.root / "results").glob("*.json")), [])

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

    def test_render_exposes_review_and_result_summary(self) -> None:
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
        rendered = self.run_task("render")
        table = Path(rendered["output"]).read_text(encoding="utf-8")
        self.assertEqual(rendered["needs_review_count"], 1)
        self.assertEqual(rendered["results"]["referenced_result_count"], 0)
        self.assertIn("| review | 1 |", table)
        self.assertIn("需复核任务：1", table)
        self.assertIn("当前没有结果引用", table)
        self.assertNotIn("当前状态引用结果：0", table)
        self.assertNotIn("含验证结果：0", table)
        self.assertNotIn("| todo | 0 |", table)
        self.assertNotIn("可修订上游未决：0", table)
        self.assertNotIn("延后讨论项：0", table)
        self.assertIn("只是任务合同与状态的可重建视图", table)

    def test_render_uses_visible_placeholders_for_empty_task_cells(self) -> None:
        rendered = self.run_task("render")
        table = Path(rendered["output"]).read_text(encoding="utf-8")
        self.assertIn(
            "| T001 | todo | — | — | — | 实现导出职责 | — | — | 1 |",
            table,
        )
        self.assertIn(
            "| T002 | todo | — | — | — | 接入界面 | T001:hard | — | 1 |",
            table,
        )

    def test_protected_source_drift_is_diagnostic_for_state_changes(self) -> None:
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
            "--expected-state-revision",
            "1",
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        payload = json.loads(started.stdout)
        self.assertEqual(payload["state"]["status"], "in_progress")
        self.assertIn(
            "baseline_source_drift",
            {item["kind"] for item in payload["diagnostics"]},
        )

    def test_completed_contract_update_keeps_result_as_stale_evidence(self) -> None:
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
        self.assertEqual(updated.returncode, 0, updated.stderr)
        payload = json.loads(updated.stdout)
        self.assertIn(
            "completed_task_contract_updated",
            {item["kind"] for item in payload["diagnostics"]},
        )
        rendered = self.run_task("render")
        self.assertEqual(rendered["results"]["referenced_result_count"], 1)
        self.assertEqual(rendered["results"]["task_revision_stale_result_count"], 1)
        self.assertEqual(rendered["results"]["source_snapshot_issue_result_count"], 0)
        self.assertEqual(rendered["results"]["result_with_diagnostics_count"], 1)
        self.assertEqual(rendered["results"]["result_diagnostic_count"], 1)
        self.assertEqual(
            rendered["results"]["result_diagnostic_kind_counts"],
            {"result_task_revision_stale": 1},
        )

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

        model = self.run_default_cli(
            TASKCTL,
            "draft",
            "--task-dir",
            str(self.root),
            "--id",
            "T011",
            "--title",
            "生成模型候选任务",
            "--outcome",
            "形成模型可修改语义",
        )
        self.assertEqual(model.returncode, 0, model.stderr)
        self.assertIn("id:T011", model.stdout)
        self.assertNotIn("schema:", model.stdout)
        self.assertNotIn("revision:", model.stdout)

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
        stored = json.loads(
            (self.root / "tasks" / "T010.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored["schema"], "task.record")
        self.assertEqual(stored["revision"], 1)
        context = self.run_task("context", "--id", "T010", "--budget", "12000")
        self.assertFalse(context["source_snapshot_complete"])
        self.assertEqual(context["source_snapshot"], {})

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
        stored = json.loads(
            (self.root / "tasks" / "T010.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored["schema"], "task.record")
        self.assertEqual(stored["revision"], 2)

    def test_legacy_task_envelope_is_normalized_by_add_and_update(self) -> None:
        task = self.task("T010", "兼容上一版任务输入", ["SOL-001"])
        candidate = Path(self.temp.name) / "T010-legacy-add.json"
        candidate.write_text(
            json.dumps(
                self.legacy_task_payload(task), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        added = self.run_task("add", "--file", str(candidate))
        self.assertIn(
            "legacy_task_envelope_normalized",
            {item["kind"] for item in added["diagnostics"]},
        )
        stored_path = self.root / "tasks" / "T010.json"
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        stored["title"] = "兼容上一版任务更新"
        update_file = Path(self.temp.name) / "T010-legacy-update.json"
        update_file.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        updated = self.run_task(
            "update",
            "--file",
            str(update_file),
            "--expected-task-revision",
            "1",
        )
        self.assertIn(
            "legacy_task_envelope_normalized",
            {item["kind"] for item in updated["diagnostics"]},
        )
        self.assertEqual(
            json.loads(stored_path.read_text(encoding="utf-8"))["revision"], 2
        )

    def test_semantic_task_input_rejects_partial_machine_fields(self) -> None:
        task = self.task("T010", "混合任务输入", ["SOL-001"])
        task["revision"] = 1
        candidate = Path(self.temp.name) / "T010-mixed-task.json"
        candidate.write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        failed = self.run_cli(
            TASKCTL,
            "add",
            "--task-dir",
            str(self.root),
            "--file",
            str(candidate),
        )
        self.assertEqual(failed.returncode, 2)
        payload = json.loads(failed.stderr)
        self.assertEqual(payload["gate"]["id"], "TASK-INPUT-UNREADABLE")
        self.assertIn("revision", payload["error"])
        self.assertFalse((self.root / "tasks" / "T010.json").exists())
        self.assertFalse((self.root / "state" / "T010.json").exists())

    def test_add_isolates_unrelated_state_storage_damage(self) -> None:
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
        self.assertEqual(added.returncode, 0, added.stderr)
        payload = json.loads(added.stdout)
        self.assertIn(
            "orphan_task_state", {item["kind"] for item in payload["diagnostics"]}
        )
        self.assertTrue((self.root / "tasks" / "T010.json").exists())
        self.assertTrue((self.root / "state" / "T010.json").exists())

    def test_update_isolates_unrelated_state_storage_damage(self) -> None:
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
        self.assertEqual(updated.returncode, 0, updated.stderr)
        payload = json.loads(updated.stdout)
        self.assertIn(
            "orphan_task_state", {item["kind"] for item in payload["diagnostics"]}
        )
        after = json.loads((self.root / "tasks" / "T001.json").read_text(encoding="utf-8"))
        self.assertEqual(after["title"], "不得在失败时改写")
        self.assertEqual(after["revision"], 2)

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

    def test_tampered_baseline_confirmation_is_advisory(self) -> None:
        baseline_path = self.root / "protected-baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["confirmed_by"] = "model"
        baseline_path.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        listed = self.run_cli(TASKCTL, "list", "--task-dir", str(self.root))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        status = self.run_task("status")
        self.assertIn(
            "baseline_confirmation_provenance_unverified",
            {item["kind"] for item in status["index_diagnostics"]},
        )

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

    def test_completion_context_rebuilds_stale_index_in_memory(self) -> None:
        with (self.root / "deferred-changes.md").open("a", encoding="utf-8") as handle:
            handle.write(
                "\n## DCR-001 延后讨论入口调整\n\n- 状态: deferred\n- 目标: UDES-001\n"
            )
        completion = self.run_task("completion-context")
        self.assertEqual(completion["target_source"], "current_markdown_documents")
        self.assertTrue(completion["targets"])
        self.assertEqual(completion["deferred_change_count"], 1)
        self.assertIn(
            "upstream_index_stale",
            {diagnostic["kind"] for diagnostic in completion["query_diagnostics"]},
        )

    def test_completion_context_preserves_distinct_relative_document_paths(self) -> None:
        requirements_path = Path("requirements") / "stage.md"
        user_design_path = Path("user-design") / "stage.md"
        for source_name, configured_path in (
            ("requirements.md", requirements_path),
            ("user-design.md", user_design_path),
        ):
            destination = self.root / configured_path
            destination.parent.mkdir(parents=True)
            (self.root / source_name).replace(destination)
        workflow_path = self.root / "workflow.json"
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        workflow["documents"]["requirements"] = requirements_path.as_posix()
        workflow["documents"]["user_design"] = user_design_path.as_posix()
        workflow_path.write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        completion = self.run_task("completion-context", "--limit", "20")
        documents = {
            row["id"]: row["document"]
            for row in completion["targets"]
            if row["id"] in {"REQ-001", "UDES-001"}
        }
        self.assertEqual(documents["REQ-001"], requirements_path.as_posix())
        self.assertEqual(documents["UDES-001"], user_design_path.as_posix())
        self.assertNotEqual(documents["REQ-001"], documents["UDES-001"])

    def test_completion_context_ignores_tampered_cached_derived_content(self) -> None:
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
        self.assertTrue(completion["targets"])
        self.assertNotIn("REQ-999", {item["id"] for item in completion["targets"]})
        self.assertIn(
            "upstream_index_derived_content_mismatch",
            {item["kind"] for item in completion["query_diagnostics"]},
        )

    def test_completion_context_pages_candidates_constraints_and_deferred_items(self) -> None:
        (self.root / "deferred-changes.md").write_text(
            """# 延后讨论项

## DCR-001 延后入口调整

- 状态: deferred
- 目标: UDES-001

## DCR-002 需复核的项目自定义状态

- 状态: project-paused
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
        self.assertEqual(first["deferred_change_count"], 2)
        self.assertEqual(first["returned_deferred_change_count"], 1)
        self.assertIn(
            "non_standard_deferred_change_status",
            {item["kind"] for item in first["query_diagnostics"]},
        )
        self.assertEqual(first["targets"][0]["candidate_task_count"], 2)
        self.assertEqual(first["targets"][0]["returned_candidate_task_count"], 1)
        self.assertEqual(
            set(first["candidate_tasks"]),
            set(first["targets"][0]["candidate_task_ids"]),
        )
        self.assertEqual(
            first["returned_streams"],
            ["targets", "constraints", "deferred_changes"],
        )
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
        self.assertEqual(
            set(candidate_page["candidate_tasks"]),
            set(candidate_page["targets"][0]["candidate_task_ids"]),
        )
        self.assertNotEqual(
            first["targets"][0]["candidate_task_ids"],
            candidate_page["targets"][0]["candidate_task_ids"],
        )
        self.assertEqual(candidate_page["returned_streams"], ["targets"])
        self.assertEqual(candidate_page["constraints"], [])
        self.assertEqual(candidate_page["deferred_changes"], [])
        deferred_page = self.run_task(
            "completion-context",
            "--deferred-after-id",
            first["pagination"]["deferred_next_after_id"],
            "--snapshot-id",
            first["snapshot_id"],
            "--max-items",
            "1",
        )
        self.assertEqual(deferred_page["deferred_changes"][0]["id"], "DCR-002")
        self.assertEqual(
            deferred_page["deferred_changes"][0]["status"], "project-paused"
        )
        self.assertEqual(deferred_page["returned_streams"], ["deferred_changes"])
        self.assertEqual(deferred_page["targets"], [])
        self.assertEqual(deferred_page["constraints"], [])

        target_first = self.run_task(
            "completion-context", "--limit", "1", "--max-items", "1"
        )
        target_page = self.run_task(
            "completion-context",
            "--after-id",
            target_first["pagination"]["target_next_after_id"],
            "--snapshot-id",
            target_first["snapshot_id"],
            "--limit",
            "1",
            "--max-items",
            "1",
        )
        self.assertEqual(target_page["returned_streams"], ["targets"])
        self.assertEqual(target_page["constraints"], [])
        self.assertEqual(target_page["deferred_changes"], [])

        mixed_page = self.run_cli(
            TASKCTL,
            "completion-context",
            "--task-dir",
            str(self.root),
            "--after-id",
            target_first["pagination"]["target_next_after_id"],
            "--deferred-after-id",
            first["pagination"]["deferred_next_after_id"],
            "--snapshot-id",
            first["snapshot_id"],
        )
        self.assertEqual(mixed_page.returncode, 2)
        self.assertIn(
            "one result stream", json.loads(mixed_page.stderr)["error"]
        )

    def test_completion_context_rejects_unknown_stream_cursors(self) -> None:
        (self.root / "deferred-changes.md").write_text(
            """# 延后讨论项

## DCR-001 延后入口调整

- 状态: deferred
- 目标: UDES-001
""",
            encoding="utf-8",
        )
        first = self.run_task(
            "completion-context", "--limit", "1", "--max-items", "1"
        )
        probes = (
            ("--after-id", "REQ-999"),
            ("--constraint-after-id", "CON-999"),
            ("--deferred-after-id", "DCR-999"),
            (
                "--target-id",
                "REQ-001",
                "--candidate-after-id",
                "T999",
            ),
        )
        for probe in probes:
            with self.subTest(probe=probe):
                continued = self.run_cli(
                    TASKCTL,
                    "completion-context",
                    "--task-dir",
                    str(self.root),
                    *probe,
                    "--snapshot-id",
                    first["snapshot_id"],
                    "--limit",
                    "1",
                    "--max-items",
                    "1",
                )
                self.assertEqual(continued.returncode, 2, continued.stdout)
                payload = json.loads(continued.stderr)
                self.assertEqual(payload["gate"]["id"], "TASK-INPUT-UNREADABLE")
                self.assertEqual(
                    payload["gate"]["scope"],
                    "current completion-context continuation",
                )
                self.assertIn("exact cursor", payload["gate"]["recovery"])

    def test_unreadable_current_result_is_isolated_from_batch_render(self) -> None:
        self.complete_t001()
        rendered = self.run_task("render")
        self.assertEqual(rendered["results"]["referenced_result_count"], 1)
        self.assertEqual(rendered["results"]["result_with_verification_count"], 1)
        table = Path(rendered["output"]).read_text(encoding="utf-8")
        self.assertIn("当前状态引用结果：1", table)
        result_path = self.root / "results" / "T001.r4.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["task_revision"] = 99
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shown = self.run_cli(
            TASKCTL, "show", "--task-dir", str(self.root), "--id", "T001"
        )
        self.assertEqual(shown.returncode, 0, shown.stderr)
        shown_payload = json.loads(shown.stdout)
        self.assertIsNone(shown_payload["result"])
        self.assertIn(
            "current_result_unreadable",
            {item["kind"] for item in shown_payload["diagnostics"]},
        )
        rerendered = self.run_cli(
            TASKCTL, "render", "--task-dir", str(self.root)
        )
        self.assertEqual(rerendered.returncode, 0, rerendered.stderr)
        rerendered_payload = json.loads(rerendered.stdout)
        self.assertEqual(rerendered_payload["results"]["referenced_result_count"], 0)
        self.assertIn(
            "current_result_unreadable",
            {item["kind"] for item in rerendered_payload["storage_diagnostics"]},
        )

    def test_reopen_reports_non_typical_state_and_owner_mismatch(self) -> None:
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
            "--expected-state-revision",
            "1",
        )
        self.assertEqual(not_done.returncode, 0, not_done.stderr)
        self.assertIn(
            "non_typical_reopen_state",
            {item["kind"] for item in json.loads(not_done.stdout)["diagnostics"]},
        )
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
        self.assertEqual(wrong_owner.returncode, 0, wrong_owner.stderr)
        self.assertIn(
            "owner_mismatch",
            {item["kind"] for item in json.loads(wrong_owner.stdout)["diagnostics"]},
        )

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
            json.dumps(self.legacy_result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
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

    def test_recompletion_recovers_orphan_result_after_done_state(self) -> None:
        completed = self.complete_t001()
        next_revision = completed["state"]["revision"] + 1
        orphan = self.root / "results" / f"T001.r{next_revision}.json"
        existing = json.loads(
            (self.root / completed["result_ref"]).read_text(encoding="utf-8")
        )
        orphan.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result_file = Path(self.temp.name) / "retry-done-result.json"
        result_file.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        recovered = self.run_task(
            "complete",
            "--id",
            "T001",
            "--owner",
            "agent-a",
            "--result-file",
            str(result_file),
            "--expected-state-revision",
            str(completed["state"]["revision"]),
        )
        self.assertTrue(recovered["recovered_partial_write"])
        self.assertEqual(recovered["state"]["result_ref"], f"results/T001.r{next_revision}.json")

    def test_complete_from_a_non_typical_state_records_a_diagnostic(self) -> None:
        result_file = Path(self.temp.name) / "state-transition-result.json"
        result_file.write_text(
            json.dumps(self.result_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
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
            "1",
        )
        self.assertEqual(completed["state"]["status"], "done")
        self.assertIn(
            "non_typical_completion_state",
            {item["kind"] for item in completed["diagnostics"]},
        )

    def test_add_recovers_matching_partial_task_record(self) -> None:
        task = self.task("T020", "恢复部分写入", ["SOL-001"])
        task_path = self.root / "tasks" / "T020.json"
        task_path.write_text(
            json.dumps(
                self.legacy_task_payload(task), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
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

    def test_init_rejects_blank_id_but_preserves_blank_semantic_title(self) -> None:
        rejected_root = Path(self.temp.name) / "blank-task-id"
        rejected = self.run_cli(
            TASKCTL,
            "init",
            "--task-dir",
            str(rejected_root),
            "--id",
            " ",
            "--title",
            "有效标题",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("must not be empty", json.loads(rejected.stderr)["error"])
        self.assertFalse((rejected_root / "task-table.json").exists())

        accepted_root = Path(self.temp.name) / "blank-task-title"
        accepted = self.run_cli(
            TASKCTL,
            "init",
            "--task-dir",
            str(accepted_root),
            "--id",
            "valid",
            "--title",
            " ",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn(
            "semantic_text_empty",
            {item["kind"] for item in json.loads(accepted.stdout)["diagnostics"]},
        )
        table = json.loads(
            (accepted_root / "task-table.json").read_text(encoding="utf-8")
        )
        self.assertEqual(table["title"], " ")
        self.assertEqual(table["snapshot_dir"], "snapshots")
        self.assertTrue((accepted_root / "snapshots").is_dir())

    def test_init_in_existing_workflow_gates_id_but_not_semantic_title(self) -> None:
        target = Path(self.temp.name) / "recover-task-table"
        initialized = self.run_cli(
            WORKCTL,
            "init",
            "--work-dir",
            str(target),
            "--id",
            "delivery-id",
            "--title",
            "Delivery Title",
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        (target / "task-table.json").unlink()

        rejected = self.run_cli(
            TASKCTL,
            "init",
            "--task-dir",
            str(target),
            "--id", "other-id",
            "--title", "Delivery Title",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("workflow id", json.loads(rejected.stderr)["error"])
        self.assertFalse((target / "task-table.json").exists())

        accepted = self.run_cli(
            TASKCTL,
            "init",
            "--task-dir",
            str(target),
            "--id", "delivery-id",
            "--title", "Other Title",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        table = json.loads((target / "task-table.json").read_text(encoding="utf-8"))
        self.assertEqual(table["title"], "Other Title")
        status = self.run_cli(TASKCTL, "status", "--task-dir", str(target))
        self.assertEqual(status.returncode, 0, status.stderr)

    def test_filesystem_error_is_bounded_json(self) -> None:
        target = Path(self.temp.name) / "not-a-task-directory"
        target.write_text("occupied", encoding="utf-8")
        initialized = self.run_cli(
            TASKCTL,
            "init",
            "--task-dir",
            str(target),
            "--id",
            "valid",
            "--title",
            "有效标题",
        )
        self.assertEqual(initialized.returncode, 2)
        payload = json.loads(initialized.stderr)
        self.assertFalse(payload["ok"])
        self.assertIn("filesystem operation failed", payload["error"])
        self.assertNotIn("Traceback", initialized.stderr)

    def test_argument_errors_are_bounded_json_while_help_remains_text(self) -> None:
        cases = (
            ("list", "--unknown"),
            ("list",),
            ("claim", "--task-dir", str(self.root), "--id", "T001"),
        )
        for arguments in cases:
            result = self.run_cli(TASKCTL, *arguments)
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stderr)
            self.assertFalse(payload["ok"])
            self.assertIn("argument error", payload["error"])
            self.assertNotIn("usage:", result.stderr)
        helped = self.run_cli(TASKCTL, "--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("usage:", helped.stdout)
        self.assertIn("管理任务合同、依赖查询、执行状态和有界上下文", helped.stdout)
        self.assertIn("返回建议候选，不签发执行许可", helped.stdout)
        self.assertIn("分页取得最终复核证据，不裁决整体完成", helped.stdout)
        self.assertIn("用 task/state CAS 和来源收据提交结果", helped.stdout)

        context_help = self.run_cli(TASKCTL, "context", "--help")
        self.assertEqual(context_help.returncode, 0)
        self.assertIn("model 视图的保守 Token 上限", context_help.stdout)
        self.assertIn("内容寻址来源快照并返回收据", context_help.stdout)
        self.assertIn("taskctl.py context --task-dir", context_help.stdout)

        complete_help = self.run_cli(TASKCTL, "complete", "--help")
        self.assertEqual(complete_help.returncode, 0)
        self.assertIn("执行所依据的 task revision", complete_help.stdout)
        self.assertIn("context --capture 返回的内容寻址来源收据", complete_help.stdout)
        self.assertIn("预期 state revision", complete_help.stdout)

        module = load_taskctl_module()
        parser = module.build_parser()
        subparser_action = next(
            action for action in parser._actions if action.dest == "command"
        )
        for command, command_parser in subparser_action.choices.items():
            self.assertTrue(command_parser.description, command)
            for action in command_parser._actions:
                if action.dest == "help":
                    continue
                self.assertIsInstance(action.help, str, f"{command}:{action.dest}")
                self.assertTrue(action.help.strip(), f"{command}:{action.dest}")

    def test_task_table_preserves_noncanonical_semantic_title(self) -> None:
        table_path = self.root / "task-table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["title"] = " 演示交付 "
        table_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        listed = self.run_cli(TASKCTL, "list", "--task-dir", str(self.root))
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(
            "semantic_text_surrounding_whitespace",
            {item["kind"] for item in json.loads(listed.stdout)["diagnostics"]},
        )

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
        payload = json.loads(continued.stderr)
        self.assertIn("snapshot changed", payload["error"])
        self.assertEqual(payload["gate"]["id"], "TASK-PAGINATION-SNAPSHOT")

    def test_completion_snapshot_rejects_unreadable_markdown_continuation(self) -> None:
        first = self.run_task(
            "completion-context", "--limit", "1", "--max-items", "1"
        )
        cursor = first["pagination"]["target_next_after_id"]
        self.assertIsNotNone(cursor)
        (self.root / "requirements.md").unlink()

        first_page_retry = self.run_cli(
            TASKCTL,
            "completion-context",
            "--task-dir",
            str(self.root),
            "--limit",
            "1",
            "--max-items",
            "1",
        )
        self.assertEqual(first_page_retry.returncode, 0, first_page_retry.stderr)
        first_page_payload = json.loads(first_page_retry.stdout)
        self.assertNotIn("snapshot_id", first_page_payload)
        self.assertIn(
            "delivery_index_rebuild_failed",
            {item["kind"] for item in first_page_payload["query_diagnostics"]},
        )

        continued = self.run_cli(
            TASKCTL,
            "completion-context",
            "--task-dir",
            str(self.root),
            "--after-id",
            cursor,
            "--snapshot-id",
            first["snapshot_id"],
            "--limit",
            "1",
            "--max-items",
            "1",
        )
        self.assertEqual(continued.returncode, 2, continued.stdout)
        payload = json.loads(continued.stderr)
        self.assertEqual(payload["gate"]["id"], "TASK-INPUT-UNREADABLE")
        self.assertEqual(
            payload["gate"]["scope"], "current completion-context continuation"
        )
        self.assertIn(
            "restart completion-context from the first page",
            payload["gate"]["recovery"],
        )
        self.assertIn("missing file", payload["error"])

    def test_owner_mismatch_is_advisory_but_state_revision_is_a_gate(self) -> None:
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
        updated = self.run_task(
            "update",
            "--file",
            str(candidate),
            "--expected-task-revision",
            "1",
        )
        self.assertEqual(updated["task_revision"], 2)
        self.assertIn(
            "owner_mismatch", {item["kind"] for item in updated["diagnostics"]}
        )
        stale_state = self.run_cli(
            TASKCTL,
            "note",
            "--task-dir",
            str(self.root),
            "--id",
            "T001",
            "--owner",
            "agent-b",
            "--message",
            "基于陈旧状态的说明",
            "--expected-state-revision",
            str(claimed["state"]["revision"] - 1),
        )
        self.assertEqual(stale_state.returncode, 2)
        payload = json.loads(stale_state.stderr)
        self.assertEqual(payload["gate"]["id"], "TASK-REVISION")

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
                json.dumps(self.legacy_result_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
        shown = self.run_task("show", "--id", "T001", "--budget", "5000")
        self.assertIsNone(shown["result"])

    def test_far_ahead_result_history_is_isolated_as_a_diagnostic(self) -> None:
        invalid = self.root / "results" / "T001.r999.json"
        invalid.write_text(
            json.dumps(self.legacy_result_payload(), ensure_ascii=False),
            encoding="utf-8",
        )
        shown = self.run_task("show", "--id", "T001")
        self.assertIsNone(shown["result"])
        history = [
            item
            for item in shown["diagnostics"]
            if item["kind"] == "result_history_record_unreadable"
        ]
        self.assertEqual(len(history), 1)
        self.assertIn("ahead of task state", history[0]["message"])

    def test_invalid_result_history_name_is_isolated_as_a_diagnostic(self) -> None:
        invalid = self.root / "results" / "T001.rbad.json"
        invalid.write_text(
            json.dumps(self.legacy_result_payload(), ensure_ascii=False),
            encoding="utf-8",
        )
        shown = self.run_task("show", "--id", "T001")
        self.assertIsNone(shown["result"])
        history = [
            item
            for item in shown["diagnostics"]
            if item["kind"] == "result_history_record_unreadable"
        ]
        self.assertEqual(len(history), 1)
        self.assertIn("invalid task result history name", history[0]["message"])

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

    def test_cycle_diagnostic_excludes_downstream_non_cycle_tasks(self) -> None:
        module = load_taskctl_module()
        tasks = {
            "T001": {
                "dependencies": [{"id": "T002", "type": "hard", "consumes": []}]
            },
            "T002": {
                "dependencies": [{"id": "T001", "type": "hard", "consumes": []}]
            },
            "T003": {
                "dependencies": [{"id": "T001", "type": "hard", "consumes": []}]
            },
        }
        self.assertEqual(module.ensure_acyclic(tasks), ["T001", "T002"])

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

    def test_concurrent_task_init_has_one_winner(self) -> None:
        root = Path(self.temp.name) / "concurrent-task-init"
        commands = [
            [
                sys.executable,
                "-X",
                "utf8",
                str(TASKCTL),
                "init",
                "--task-dir",
                str(root),
                "--id",
                table_id,
                "--title",
                title,
            ]
            for table_id, title in (("first", "第一身份"), ("second", "第二身份"))
        ]
        environment = dict(os.environ)
        environment["PYTHONUTF8"] = "1"
        processes = [
            subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                env=environment,
            )
            for command in commands
        ]
        completed = [process.communicate(timeout=20) for process in processes]
        self.assertEqual(sorted(process.returncode for process in processes), [0, 2], completed)
        table = json.loads((root / "task-table.json").read_text(encoding="utf-8"))
        self.assertIn(
            (table["id"], table["title"]),
            {("first", "第一身份"), ("second", "第二身份")},
        )


if __name__ == "__main__":
    unittest.main()
