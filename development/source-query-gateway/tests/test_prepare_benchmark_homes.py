from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare_benchmark_homes.py"
SPEC = importlib.util.spec_from_file_location("prepare_benchmark_homes", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareBenchmarkHomesTests(unittest.TestCase):
    def test_subject_config_uses_standard_service_tier(self) -> None:
        config = MODULE.config_text(None)
        self.assertIn('service_tier = "default"', config)
        self.assertNotIn('service_tier = "fast"', config)
        self.assertIn('sandbox_mode = "danger-full-access"', config)
        self.assertNotIn('sandbox_mode = "read-only"', config)

    def test_subject_config_pre_registers_trusted_workspaces(self) -> None:
        project = Path("D:/Program/Example")
        config = MODULE.config_text(None, (project,))
        self.assertIn("[projects.'d:\\program\\example']", config)
        self.assertIn('trust_level = "trusted"', config)

    def test_benchmark_home_rejects_system_temp(self) -> None:
        with self.assertRaisesRegex(SystemExit, "must not be under the system temp"):
            MODULE.validate_benchmark_home_location(Path(tempfile.gettempdir()) / "benchmark-home")

    def test_candidate_is_the_exact_current_query_migration_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "installed"
            installed.mkdir()
            (installed / "AGENTS.md").write_text(MODULE.OLD_ROUTE + "\n", encoding="utf-8")
            skills = installed / "skills"
            skills.mkdir()
            for name in sorted(MODULE.MINIMAL_RELEVANT_SKILLS - {"source-query"}):
                source = skills / name
                source.mkdir()
                (source / "marker.txt").write_text(f"old:{name}\n", encoding="utf-8")

            control = root / "control"
            candidate = root / "candidate"
            MODULE.copy_common(installed, control, None, full_installed_skills=False, baseline_mode="premigration")
            MODULE.copy_common(installed, candidate, None, full_installed_skills=False, baseline_mode="premigration")
            srcq = root / "srcq.exe"
            srcq.write_bytes(b"current-srcq")
            MODULE.install_candidate_bundle(control, candidate, srcq)

            for name in MODULE.RETIRED_QUERY_SKILLS:
                self.assertTrue((control / "skills" / name / "marker.txt").is_file())
                self.assertFalse((candidate / "skills" / name).exists())
            self.assertEqual(
                "old:powershell-usage\n",
                (candidate / "skills" / "powershell-usage" / "marker.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (MODULE.PROJECT_ROOT / "skills" / "source-query" / "SKILL.md").read_bytes(),
                (candidate / "skills" / "source-query" / "SKILL.md").read_bytes(),
            )
            self.assertEqual(
                (MODULE.PROJECT_ROOT / "skills" / "symbol-structure-workflow" / "SKILL.md").read_bytes(),
                (candidate / "skills" / "symbol-structure-workflow" / "SKILL.md").read_bytes(),
            )
            self.assertEqual(b"current-srcq", (candidate / "bin" / "srcq.exe").read_bytes())
            self.assertFalse((control / "bin" / "srcq.exe").exists())

    def test_migrated_baseline_changes_only_source_query_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "installed"
            installed.mkdir()
            (installed / "AGENTS.md").write_text(
                MODULE.current_route_block() + "\n",
                encoding="utf-8",
            )
            skills = installed / "skills"
            skills.mkdir()
            for name in ("powershell-usage", "source-query", "symbol-structure-workflow"):
                source = skills / name
                source.mkdir()
                (source / "marker.txt").write_text(f"baseline:{name}\n", encoding="utf-8")

            control = root / "control"
            candidate = root / "candidate"
            MODULE.copy_common(installed, control, None, full_installed_skills=False, baseline_mode="migrated")
            MODULE.copy_common(installed, candidate, None, full_installed_skills=False, baseline_mode="migrated")
            baseline = root / "baseline.exe"
            baseline.write_bytes(b"baseline")
            current = root / "current.exe"
            current.write_bytes(b"current")
            MODULE.install_incremental_bundle(control, candidate, baseline, current)

            self.assertEqual(b"baseline", (control / "bin" / "srcq.exe").read_bytes())
            self.assertEqual(b"current", (candidate / "bin" / "srcq.exe").read_bytes())
            self.assertEqual(
                "baseline:source-query\n",
                (control / "skills" / "source-query" / "marker.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (MODULE.PROJECT_ROOT / "skills" / "source-query" / "SKILL.md").read_bytes(),
                (candidate / "skills" / "source-query" / "SKILL.md").read_bytes(),
            )
            for name in ("powershell-usage", "symbol-structure-workflow"):
                self.assertEqual(
                    (control / "skills" / name / "marker.txt").read_bytes(),
                    (candidate / "skills" / name / "marker.txt").read_bytes(),
                )

    def test_current_route_comes_from_project_global_truth(self) -> None:
        route = MODULE.current_route()
        self.assertTrue(route.startswith(MODULE.CURRENT_ROUTE_PREFIX))
        self.assertIn("`srcq fd <fd argv...>`", route)
        self.assertIn("`srcq rg <rg argv...>`", route)
        self.assertIn("全集、不存在或唯一结论先从最近正式来源确认权威源码范围", route)
        self.assertIn("且只查该范围", route)
        self.assertIn("已知符号后停止搜索", route)
        self.assertIn("文本不足才经 srcq 升级 AST", route)
        self.assertIn("符号语义仍不足才用 LSP", route)
        self.assertIn("证据充分即停止", route)
        self.assertNotIn("当前查询快照", route)

    def test_previous_migrated_route_is_replaced_only_in_candidate_text(self) -> None:
        previous = MODULE.PREVIOUS_MIGRATED_ROUTE_PREFIX + "上一版正文"
        previous_scope = MODULE.LEGACY_AUXILIARY_ROUTE_PREFIXES[0] + "上一版范围正文"
        previous_escalation = MODULE.LEGACY_AUXILIARY_ROUTE_PREFIXES[1] + "上一版升级正文"
        previous_conclusion = MODULE.LEGACY_AUXILIARY_ROUTE_PREFIXES[2] + "上一版结论正文"
        installed = "\n\n".join(
            (previous, previous_scope, previous_escalation, previous_conclusion)
        ) + "\n"
        migrated = MODULE.replace_migrated_route(installed)
        self.assertEqual(MODULE.current_route_block() + "\n", migrated)
        self.assertEqual(previous, MODULE.migrated_route(installed))

    def test_two_rule_authority_candidate_collapses_to_one_current_route(self) -> None:
        previous = MODULE.PREVIOUS_AUTHORITY_ROUTE_PREFIX + "上一版正文"
        evidence = MODULE.CURRENT_EVIDENCE_ROUTE_PREFIX + "上一版范围正文"
        migrated = MODULE.replace_migrated_route(previous + "\n\n" + evidence + "\n")
        self.assertEqual(MODULE.current_route_block() + "\n", migrated)
        self.assertEqual(previous, MODULE.migrated_route(previous + "\n"))

    def test_minimal_skill_scope_is_the_default_causal_set(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installed = root / "installed"
            installed.mkdir()
            (installed / "AGENTS.md").write_text(
                MODULE.current_route_block() + "\n",
                encoding="utf-8",
            )
            skills = installed / "skills"
            for name in (*sorted(MODULE.MIGRATED_SKILLS), "ue-kb"):
                source = skills / name
                source.mkdir(parents=True, exist_ok=True)
                (source / "marker.txt").write_text(name, encoding="utf-8")
            target = root / "target"
            MODULE.copy_common(installed, target, None, full_installed_skills=False, baseline_mode="migrated")
            self.assertFalse((target / "skills" / "ue-kb").exists())
            self.assertEqual(MODULE.MIGRATED_SKILLS, {
                path.name for path in (target / "skills").iterdir() if path.name != ".system"
            })

    def test_srcq_ingress_probe_rejects_stale_command_shape(self) -> None:
        executable = Path("srcq.exe")
        version = subprocess_result(0, "srcq 0.3.0\n", "")
        ingress = subprocess_result(0, "probe.rs:1:SRCQ_INGRESS_SENTINEL_7F39\n", "")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=[version, ingress]) as run:
            self.assertEqual("srcq 0.3.0", MODULE.verify_srcq_ingress(executable))
            self.assertEqual("rg", run.call_args_list[1].args[0][1])
        stale = subprocess_result(2, "", "unexpected argument '--fixed-strings'")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=[version, stale]):
            with self.assertRaisesRegex(SystemExit, "does not support intuitive rg ingress"):
                MODULE.verify_srcq_ingress(executable)


def subprocess_result(returncode: int, stdout: str, stderr: str):
    return MODULE.subprocess.CompletedProcess([], returncode, stdout, stderr)


if __name__ == "__main__":
    unittest.main()
