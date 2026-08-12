from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workctl.py"


def load_workctl_module():
    spec = importlib.util.spec_from_file_location("workctl_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkctlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "work"
        result = self.run_cli(
            "init",
            "--work-dir",
            str(self.root),
            "--id",
            "demo",
            "--title",
            "演示交付",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.initialized = self.payload(result)
        self.write_valid_documents()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), *args],
            text=True,
            capture_output=True,
            encoding="utf-8",
            env=environment,
            check=False,
        )

    def payload(self, result: subprocess.CompletedProcess[str]) -> dict:
        text = result.stdout if result.returncode == 0 else result.stderr
        return json.loads(text)

    def write_valid_documents(self) -> None:
        (self.root / "requirements.md").write_text(
            """# 演示：需求分析

## REQ-001 导出当前结果

- 状态: confirmed
- 来源: 用户确认
- 关联: AC-001

用户能够从正式入口导出当前结果。

## AC-001 导出内容可读回

- 状态: confirmed
- 来源: 用户确认
- 关联: REQ-001

导出后能够读回约定字段。

## CON-001 保持现有认证

- 状态: confirmed
- 来源: 用户确认

不得绕过现有认证。
""",
            encoding="utf-8",
        )
        (self.root / "user-design.md").write_text(
            """# 演示：用户设计

## UDES-001 使用现有公开入口

- 状态: confirmed
- 来源: 用户明确设计
- 关联: REQ-001

导出能力必须接入现有公开入口。
""",
            encoding="utf-8",
        )
        (self.root / "design.md").write_text(
            """# 演示：模型设计

## DES-001 导出职责

- 状态: confirmed
- 满足: REQ-001, AC-001, UDES-001

现有公开入口调用独立导出职责。
""",
            encoding="utf-8",
        )
        (self.root / "current-state.md").write_text(
            """# 演示：现状分析

## OBS-001 当前入口没有导出能力

- 状态: confirmed
- 关联: DES-001

直接检查未发现导出调用。

## GAP-001 缺少导出职责

- 状态: confirmed
- 关联: DES-001, OBS-001

当前行为未满足设计。
""",
            encoding="utf-8",
        )
        (self.root / "solution.md").write_text(
            """# 演示：方案设计

## SOL-001 实现并接入导出职责

- 状态: confirmed
- 解决: GAP-001
- 满足: DES-001

实现导出职责并从公开入口调用。
""",
            encoding="utf-8",
        )
        (self.root / "deferred-changes.md").write_text(
            "# 演示：延后讨论项\n\n- 无\n", encoding="utf-8"
        )

    def protect(self) -> dict:
        result = self.run_cli(
            "protect",
            "--work-dir",
            str(self.root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            "conversation:confirmed",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.payload(result)

    def test_init_index_and_protected_drift_is_advisory(self) -> None:
        before = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(self.payload(before)["summary"]["section_count"], 8)
        self.assertEqual(
            json.loads((self.root / ".work-cache" / "index.json").read_text(encoding="utf-8"))[
                "protected_baseline"
            ]["status"],
            "unprotected",
        )

        protected = self.protect()
        self.assertEqual(protected["baseline"]["status"], "protected")
        indexed = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        self.assertEqual(self.payload(indexed)["summary"]["duplicate_count"], 0)

        with (self.root / "requirements.md").open("a", encoding="utf-8") as handle:
            handle.write("\n未经确认的改写。\n")
        drifted = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(drifted.returncode, 0, drifted.stderr)
        payload = self.payload(drifted)
        self.assertIn("baseline_source_drift", {item["kind"] for item in payload["diagnostics"]})
        cached = json.loads(
            (self.root / ".work-cache" / "index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(cached["protected_baseline"]["status"], "drifted")

    def test_init_distinguishes_created_and_pending_artifacts(self) -> None:
        self.assertIn("workflow.json", self.initialized["created"])
        self.assertIn("requirements.md", self.initialized["created"])
        self.assertNotIn("protected-baseline.json", self.initialized["created"])
        self.assertNotIn(".work-cache/index.json", self.initialized["created"])
        self.assertEqual(
            self.initialized["pending"],
            [
                "protected-baseline.json",
                ".work-cache/index.json",
                "WORK_STATUS.md",
                "TASK_TABLE.md",
            ],
        )
        for relative in self.initialized["pending"]:
            self.assertFalse((self.root / relative).exists())

    def test_render_exposes_confirmation_and_separate_progress_layers(self) -> None:
        self.protect()
        rendered = self.run_cli(
            "render", "--work-dir", str(self.root), "--max-items", "100"
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        payload = self.payload(rendered)
        self.assertEqual(payload["tasks"]["task_count"], 0)
        self.assertEqual(payload["tasks"]["result_count"], 0)
        view = Path(payload["output"]).read_text(encoding="utf-8")
        self.assertIn("确认者：user", view)
        self.assertIn("确认引用：conversation:confirmed", view)
        self.assertIn("## 可修订语义闭合", view)
        self.assertIn("## 任务执行状态", view)
        self.assertIn("需复核任务：0", view)
        self.assertIn("## 任务结果证据", view)
        self.assertIn("当前可读取结果：0", view)
        self.assertIn("含验证结果：0", view)
        self.assertIn("含未决结果：0", view)
        self.assertIn("不定义语义、READY 或最终完成状态", view)

    def test_render_isolates_a_corrupt_current_task_result(self) -> None:
        task = {
            "schema": "task.record",
            "id": "T001",
            "title": "导出结果",
            "outcome": "结果可读回",
            "source_ids": ["SOL-001"],
            "dependencies": [],
            "mutation_scope": ["exports"],
            "outputs": ["导出结果"],
            "verification": ["读回字段"],
            "suggested_skills": [],
            "reasoning_hint": "medium",
            "revision": 1,
        }
        state = {
            "schema": "task.state",
            "task_id": "T001",
            "status": "done",
            "owner": "agent-a",
            "revision": 4,
            "note": "",
            "blocked_reason": "",
            "next_action": "",
            "result_ref": "results/T001.r4.json",
        }
        (self.root / "tasks" / "T001.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.root / "state" / "T001.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.root / "results" / "T001.r4.json").write_text(
            '{"schema":"task.result"}\n', encoding="utf-8"
        )
        rendered = self.run_cli("render", "--work-dir", str(self.root))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        payload = self.payload(rendered)
        self.assertEqual(payload["tasks"]["status"], "partial")
        self.assertIn(
            "current_result_unreadable",
            {item["kind"] for item in payload["tasks"]["diagnostics"]},
        )

    def test_init_rejects_blank_identity_before_writing(self) -> None:
        for index, arguments in enumerate(
            (("--id", " ", "--title", "有效标题"), ("--id", "valid", "--title", " "))
        ):
            target = Path(self.temp.name) / f"blank-identity-{index}"
            initialized = self.run_cli("init", "--work-dir", str(target), *arguments)
            self.assertEqual(initialized.returncode, 2)
            self.assertIn("must not be empty", self.payload(initialized)["error"])
            self.assertFalse((target / "workflow.json").exists())

    def test_filesystem_error_is_bounded_json(self) -> None:
        target = Path(self.temp.name) / "not-a-directory"
        target.write_text("occupied", encoding="utf-8")
        initialized = self.run_cli(
            "init", "--work-dir", str(target), "--id", "valid", "--title", "有效标题"
        )
        self.assertEqual(initialized.returncode, 2)
        payload = self.payload(initialized)
        self.assertFalse(payload["ok"])
        self.assertIn("filesystem operation failed", payload["error"])
        self.assertNotIn("Traceback", initialized.stderr)

    def test_argument_errors_are_bounded_json_while_help_remains_text(self) -> None:
        cases = (
            ("status", "--unknown"),
            ("status",),
            ("outline", "--work-dir", str(self.root), "--stage", "invalid"),
        )
        for arguments in cases:
            result = self.run_cli(*arguments)
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stderr)
            self.assertFalse(payload["ok"])
            self.assertIn("argument error", payload["error"])
            self.assertNotIn("usage:", result.stderr)
        helped = self.run_cli("--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("usage:", helped.stdout)

    def test_manifest_rejects_noncanonical_identity(self) -> None:
        manifest_path = self.root / "workflow.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = " demo "
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        status = self.run_cli("status", "--work-dir", str(self.root))
        self.assertEqual(status.returncode, 2)
        self.assertIn("surrounding whitespace", self.payload(status)["error"])

    def test_outline_uses_public_stage_names_and_the_workspace_argument(self) -> None:
        outlined = self.run_cli(
            "outline",
            "--work-dir",
            str(self.root),
            "--stage",
            "current-state",
        )
        self.assertEqual(outlined.returncode, 0, outlined.stderr)
        payload = self.payload(outlined)
        self.assertEqual(payload["stage"], "current-state")
        self.assertEqual(payload["document"], "current-state.md")
        self.assertEqual(payload["ids"], ["OBS", "GAP", "DEC"])

    def test_only_explicit_relation_fields_create_semantic_edges(self) -> None:
        with (self.root / "current-state.md").open("a", encoding="utf-8") as handle:
            handle.write(
                """

## OBS-099 标题示例 REQ-IN-TITLE

- 状态: confirmed
- 来源或证据: 正文示例 REQ-IN-EVIDENCE
- 关联: DES-001, REQ-MISSING

说明文字再次出现 REQ-IN-BODY，但都不是关系。
"""
            )
        module = load_workctl_module()
        index = module.build_index(self.root)
        observed = next(row for row in index["sections"] if row["id"] == "OBS-099")
        self.assertEqual(observed["references"], ["DES-001", "REQ-MISSING"])
        unknown = [
            item["reference"]
            for item in index["diagnostics"]
            if item["kind"] == "unknown_reference" and item["id"] == "OBS-099"
        ]
        self.assertEqual(unknown, ["REQ-MISSING"])

    def test_protect_reports_unconfirmed_entries_without_becoming_a_gate(self) -> None:
        content = (self.root / "requirements.md").read_text(encoding="utf-8")
        (self.root / "requirements.md").write_text(
            content.replace("状态: confirmed", "状态: proposed", 1), encoding="utf-8"
        )
        result = self.run_cli(
            "protect",
            "--work-dir",
            str(self.root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            "conversation:confirmed",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = self.payload(result)
        self.assertIn(
            "baseline_entries_not_confirmed",
            {item["kind"] for item in payload["diagnostics"]},
        )

    def test_context_impact_and_bounded_output(self) -> None:
        self.protect()
        indexed = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        context = self.run_cli(
            "context",
            "--work-dir",
            str(self.root),
            "--id",
            "REQ-001",
            "--depth",
            "4",
            "--budget",
            "2200",
        )
        self.assertEqual(context.returncode, 0, context.stderr)
        self.assertLessEqual(len(context.stdout), 2201)
        self.assertEqual(self.payload(context)["id"], "REQ-001")

        impact = self.run_cli(
            "impact", "--work-dir", str(self.root), "--id", "REQ-001"
        )
        self.assertEqual(impact.returncode, 0, impact.stderr)
        affected = {item["id"] for item in self.payload(impact)["affected"]}
        self.assertTrue({"DES-001", "GAP-001", "SOL-001"}.issubset(affected))

    def test_deferred_change_is_reported_separately(self) -> None:
        self.protect()
        (self.root / "deferred-changes.md").write_text(
            """# 演示：延后讨论项

## DCR-001 建议改变用户入口设计

- 状态: deferred
- 目标: UDES-001

其余工作完成后再与用户讨论。
""",
            encoding="utf-8",
        )
        indexed = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        payload = self.payload(indexed)
        self.assertEqual(payload["summary"]["deferred_change_count"], 1)
        self.assertIn("DCR-001", payload["unresolved_ids"])

    def test_duplicate_identity_is_diagnostic_but_context_is_ambiguous(self) -> None:
        content = (self.root / "design.md").read_text(encoding="utf-8")
        (self.root / "design.md").write_text(
            content
            + """
## DES-001 重复设计

- 状态: confirmed
""",
            encoding="utf-8",
        )
        indexed = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        self.assertEqual(self.payload(indexed)["summary"]["duplicate_count"], 1)
        context = self.run_cli(
            "context", "--work-dir", str(self.root), "--id", "DES-001"
        )
        self.assertEqual(context.returncode, 2)
        self.assertIn("ambiguous semantic id", self.payload(context)["error"])

    def test_generated_paths_cannot_be_redirected_to_workflow_truth(self) -> None:
        manifest_path = self.root / "workflow.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status_view"] = "requirements.md"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rendered = self.run_cli("render", "--work-dir", str(self.root))
        self.assertEqual(rendered.returncode, 2)
        self.assertIn("status_view must remain", self.payload(rendered)["error"])

    def test_task_storage_cannot_contain_workflow_truth(self) -> None:
        table_path = self.root / "task-table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["task_dir"] = "."
        table_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        indexed = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(indexed.returncode, 2)
        self.assertIn("task_dir must remain tasks", self.payload(indexed)["error"])

    def test_task_table_identity_must_match_the_workflow(self) -> None:
        table_path = self.root / "task-table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["id"] = "another-workflow"
        table_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        status = self.run_cli("status", "--work-dir", str(self.root))
        self.assertEqual(status.returncode, 2)
        self.assertIn("different workflow", self.payload(status)["error"])

    def test_task_summary_isolates_unrelated_storage_damage(self) -> None:
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
        status = self.run_cli("status", "--work-dir", str(self.root))
        self.assertEqual(status.returncode, 0, status.stderr)
        payload = self.payload(status)
        self.assertEqual(payload["tasks"]["status"], "partial")
        self.assertIn(
            "orphan_task_state",
            {item["kind"] for item in payload["tasks"]["diagnostics"]},
        )

    def test_protect_reports_model_decision_in_requirements(self) -> None:
        with (self.root / "requirements.md").open("a", encoding="utf-8") as handle:
            handle.write(
                "\n## DEC-001 模型待决选择\n\n- 状态: confirmed\n\n不属于用户基线。\n"
            )
        protected = self.run_cli(
            "protect",
            "--work-dir",
            str(self.root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            "conversation:confirmed",
        )
        self.assertEqual(protected.returncode, 0, protected.stderr)
        self.assertIn(
            "baseline_stage_id_mismatch",
            {item["kind"] for item in self.payload(protected)["diagnostics"]},
        )

    def test_tampered_baseline_ids_are_reported(self) -> None:
        self.protect()
        baseline_path = self.root / "protected-baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["documents"]["requirements"]["ids"] = ["REQ-001"]
        baseline_path.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        indexed = self.run_cli("index", "--work-dir", str(self.root))
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        self.assertIn(
            "baseline_id_set_drift",
            {item["kind"] for item in self.payload(indexed)["diagnostics"]},
        )

    def test_protected_baseline_requires_user_confirmation_provenance(self) -> None:
        blank_root = Path(self.temp.name) / "blank-confirmation"
        initialized = self.run_cli(
            "init",
            "--work-dir",
            str(blank_root),
            "--id",
            "blank-confirmation",
            "--title",
            "空确认引用",
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        for filename in (
            "requirements.md",
            "user-design.md",
            "design.md",
            "current-state.md",
            "solution.md",
            "deferred-changes.md",
        ):
            source = self.root / filename
            (blank_root / filename).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        rejected = self.run_cli(
            "protect",
            "--work-dir",
            str(blank_root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            " ",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("must not be empty", self.payload(rejected)["error"])
        self.assertFalse((blank_root / "protected-baseline.json").exists())

        protected = self.protect()
        baseline_path = self.root / "protected-baseline.json"
        original = json.loads(baseline_path.read_text(encoding="utf-8"))
        for field, value, expected_kind in (
            ("confirmed_by", "model", "baseline_confirmation_provenance_unverified"),
            ("confirmation_ref", " ", "baseline_confirmation_reference_invalid"),
        ):
            tampered = dict(original)
            tampered[field] = value
            baseline_path.write_text(
                json.dumps(tampered, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            indexed = self.run_cli("index", "--work-dir", str(self.root))
            self.assertEqual(indexed.returncode, 0, indexed.stderr)
            self.assertIn(
                expected_kind,
                {item["kind"] for item in self.payload(indexed)["diagnostics"]},
            )
        baseline_path.write_text(
            json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        status = self.run_cli("status", "--work-dir", str(self.root))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(
            self.payload(status)["protected_baseline"]["confirmation_ref"],
            "conversation:confirmed",
        )

    def test_init_refuses_nonempty_managed_storage(self) -> None:
        other = Path(self.temp.name) / "occupied"
        (other / "tasks").mkdir(parents=True)
        (other / "tasks" / "sentinel.json").write_text("{}", encoding="utf-8")
        initialized = self.run_cli(
            "init",
            "--work-dir",
            str(other),
            "--id",
            "occupied",
            "--title",
            "不可覆盖",
        )
        self.assertEqual(initialized.returncode, 2)
        payload = self.payload(initialized)
        self.assertIn("refusing to overwrite", payload["error"])
        self.assertEqual(payload["gate"]["id"], "WORK-OVERWRITE")

    def test_protect_reports_a_snapshot_without_final_targets(self) -> None:
        (self.root / "requirements.md").write_text(
            """# 只有约束

## CON-001 保持认证

- 状态: confirmed

不得绕过认证。
""",
            encoding="utf-8",
        )
        (self.root / "user-design.md").write_text("# 无用户设计\n", encoding="utf-8")
        protected = self.run_cli(
            "protect",
            "--work-dir",
            str(self.root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            "conversation:confirmed",
        )
        self.assertEqual(protected.returncode, 0, protected.stderr)
        self.assertIn(
            "baseline_has_no_final_target",
            {item["kind"] for item in self.payload(protected)["diagnostics"]},
        )

    def test_protect_detects_source_change_during_snapshot(self) -> None:
        module = load_workctl_module()
        original = module.file_fingerprint
        changed = False

        def mutate_then_fingerprint(path: Path) -> str:
            nonlocal changed
            if path.name == "requirements.md" and not changed:
                changed = True
                with path.open("a", encoding="utf-8") as handle:
                    handle.write("\n快照期间发生改变。\n")
            return original(path)

        module.file_fingerprint = mutate_then_fingerprint
        with self.assertRaises(module.WorkctlError) as caught:
            module.protect_workspace(
                Namespace(
                    work_dir=str(self.root),
                    confirmed_by="user",
                    confirmation_ref="conversation:confirmed",
                )
            )
        self.assertEqual(caught.exception.gate["id"], "WORK-SNAPSHOT-RACE")
        self.assertIn("changed", str(caught.exception))
        self.assertFalse((self.root / "protected-baseline.json").exists())

    def test_concurrent_protect_has_one_winner_and_no_overwrite(self) -> None:
        command = [
            sys.executable,
            "-X",
            "utf8",
            str(SCRIPT),
            "protect",
            "--work-dir",
            str(self.root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            "conversation:confirmed",
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
            for _ in range(2)
        ]
        completed = [process.communicate(timeout=20) for process in processes]
        codes = sorted(process.returncode for process in processes)
        self.assertEqual(codes, [0, 2], completed)
        baseline = json.loads(
            (self.root / "protected-baseline.json").read_text(encoding="utf-8")
        )
        self.assertEqual(baseline["schema"], "delivery.protected-baseline")
        self.assertEqual(baseline["cycle_id"], "cycle-001")

    def test_concurrent_init_has_one_winner_and_no_mixed_identity(self) -> None:
        root = Path(self.temp.name) / "concurrent-init"
        commands = [
            [
                sys.executable,
                "-X",
                "utf8",
                str(SCRIPT),
                "init",
                "--work-dir",
                str(root),
                "--id",
                workflow_id,
                "--title",
                title,
            ]
            for workflow_id, title in (("first", "第一身份"), ("second", "第二身份"))
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
        workflow = json.loads((root / "workflow.json").read_text(encoding="utf-8"))
        table = json.loads((root / "task-table.json").read_text(encoding="utf-8"))
        self.assertEqual((workflow["id"], workflow["title"]), (table["id"], table["title"]))

    def test_new_cycle_preserves_previous_snapshot_history(self) -> None:
        first = self.protect()
        self.assertEqual(first["baseline"]["cycle_id"], "cycle-001")
        with (self.root / "requirements.md").open("a", encoding="utf-8") as handle:
            handle.write("\n用户已确认进入新执行周期。\n")
        second = self.run_cli(
            "protect",
            "--work-dir",
            str(self.root),
            "--confirmed-by",
            "user",
            "--confirmation-ref",
            "conversation:cycle-2",
            "--new-cycle",
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        payload = self.payload(second)
        self.assertEqual(payload["baseline"]["cycle_id"], "cycle-002")
        self.assertEqual(payload["baseline"]["history_count"], 1)
        baseline = json.loads(
            (self.root / "protected-baseline.json").read_text(encoding="utf-8")
        )
        self.assertEqual(baseline["history"][0]["cycle_id"], "cycle-001")
        self.assertEqual(baseline["confirmation_ref"], "conversation:cycle-2")

    def test_context_preserves_collection_truncation(self) -> None:
        module = load_workctl_module()
        payload = {
            "ok": True,
            "command": "context",
            "id": "REQ-001",
            "sections": [],
            "truncated": True,
        }
        fitted = module.fit_context(payload, 2000)
        self.assertTrue(fitted["truncated"])


if __name__ == "__main__":
    unittest.main()
