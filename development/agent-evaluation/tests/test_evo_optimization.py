from __future__ import annotations

import copy
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

from evo.optimization import _apply, _evaluation_spec, export, run_optimization, start, status, validate_optimization
from evo.spec import EvoError, load_spec
from evo.store import Store


def proposal_argv(*, path: str = "rules.txt", hypothesis: str = "tighten rule", content: str = "candidate\n") -> list[str]:
    proposal = {
        "schema": "agentbase-evo-proposal/v1",
        "hypothesis": hypothesis,
        "edits": [{"kind": "agents_md", "id": "rules", "path": path, "content": content}],
    }
    return [sys.executable, "-X", "utf8", "-c", f"import json; print(json.dumps({proposal!r}))"]


def subject_argv(reward: int = 1) -> list[str]:
    return [sys.executable, "-X", "utf8", "-c", f"import json; print(json.dumps({{'quality.reward': {reward}}}))"]


def component_subject_argv() -> list[str]:
    script = (
        "import json,pathlib,sys; text=(pathlib.Path(sys.argv[1])/'rules.txt').read_text(encoding='utf-8').strip(); "
        "quality=2 if text=='candidate' else (0 if text=='bad' else 1); "
        "cost=10 if text=='candidate' else (1 if text=='bad' else 20); "
        "print(json.dumps({'quality.reward':quality,'cost.tokens':cost,'observed.rule':text}))"
    )
    return [sys.executable, "-X", "utf8", "-c", script, "{component_source:agents_md/rules}"]


def make_spec(controller: list[str] | None = None) -> dict:
    return {
        "schema": "agentbase-evo-research/v1", "id": "bounded-opt", "version": "1",
        "components": {
            "agents_md": [{"id": "rules", "source": "component"}],
            "skills": [], "hooks": [], "mcp": [], "tools": [], "agents": [], "codex_settings": [],
        },
        "combinations": [{"id": "seed", "members": {"agents_md": ["rules"]}}],
        "evaluations": {
            "items": [
                {"id": "dev", "family": "dev-family", "input_version": "1", "protocol": "command-v1",
                 "observations": ["quality"], "runtime": {"adapter": "command", "argv": subject_argv(), "timeout_seconds": 10}},
                {"id": "select", "family": "selection-family", "input_version": "1", "protocol": "command-v1",
                 "observations": ["quality"], "runtime": {"adapter": "command", "argv": subject_argv(), "timeout_seconds": 10}},
                {"id": "final", "family": "final-family", "input_version": "1", "protocol": "command-v1",
                 "observations": ["quality"], "runtime": {"adapter": "command", "argv": subject_argv(), "timeout_seconds": 10}},
            ],
            "groups": [
                {"id": "development", "active": False, "items": ["dev"]},
                {"id": "selection", "active": True, "items": ["select"]},
                {"id": "final", "active": False, "items": ["final"]},
            ],
        },
        "fields": [{"id": "quality.reward", "type": "number", "unit": "ratio", "grain": "attempt", "source": "command"}],
        "scoring": [{"id": "quality", "version": "1", "group_by": ["combination", "family"],
                     "metrics": [{"id": "reward", "unit": "ratio", "expression": {"aggregate": "mean", "field": "quality.reward"}}]}],
        "selection": {"combinations": ["seed"], "groups": ["selection"], "replicates": 1},
        "budget": {"concurrency": 1, "max_tokens": 1000},
        "grading": [],
        "optimization": {
            "controller": {"adapter": "command", "argv": controller or proposal_argv(), "timeout_seconds": 10},
            "mutable": [{"kind": "agents_md", "id": "rules", "paths": ["rules.txt"]}],
            "rounds": {"max": 1, "patience": 1, "duplicate_hypothesis_limit": 1},
            "budget": {"max_total_tokens": 1000, "max_controller_tokens": 100},
            "grading": [],
            "splits": {"development": ["development"], "selection": ["selection"], "final": ["final"]},
            "promotion": {
                "quality_metrics": [{"scoring": "quality", "metric": "reward", "direction": "max"}],
                "objectives": [{"scoring": "quality", "metric": "reward", "direction": "max"}],
                "required_families": ["selection-family"], "non_regression_tolerance": 0,
                "require_complete_cost": True,
            },
        },
    }


class Fixture:
    def __init__(self, test: unittest.TestCase):
        self.temp = tempfile.TemporaryDirectory()
        test.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project, self.state, self.work = root / "project", root / "state", root / "work"
        self.project.mkdir()
        (self.project / "component").mkdir()
        (self.project / "component" / "rules.txt").write_text("baseline\n", encoding="utf-8")
        self.store = Store(self.state)
        self.store.initialize(concurrency=1, model_capacity=2, max_disk_mb=64, min_free_mb=1)

    def freeze(self, spec: dict) -> dict:
        path = self.project / "optimization.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return start(self.store, path, self.project, self.work)


class EvoOptimizationTests(unittest.TestCase):
    def test_requires_explicit_baseline_for_multiple_combinations(self) -> None:
        spec = make_spec()
        spec["combinations"].append({"id": "other", "members": {"agents_md": ["rules"]}})
        spec["selection"]["combinations"].append("other")
        with self.assertRaisesRegex(EvoError, "baseline_combination"):
            validate_optimization(spec)

    def test_one_command_challenger_closes_and_rejects_equal_candidate(self) -> None:
        fixture = Fixture(self)
        frozen = fixture.freeze(make_spec())
        result = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(result["state"], "stopped", result)
        self.assertIn("no-improvement", result["stop_reason"])
        self.assertEqual(result["round"], 1)
        self.assertEqual(result["champion"], result["baseline"])
        self.assertEqual(result["controller_tokens"], 0)
        self.assertEqual(result["subject_tokens"], 0)
        self.assertIsNone(result["final_study"])
        controller_studies = _state(fixture, frozen)["controller_studies"]
        self.assertEqual(len(controller_studies), 1)
        self.assertEqual(fixture.store.status(controller_studies[0])["counts"], {"completed": 1})
        exported = export(fixture.store, frozen["id"])
        self.assertIn("does not deploy", exported["note"])

    def test_completed_resume_does_not_repeat_controller_or_subject(self) -> None:
        fixture = Fixture(self)
        frozen = fixture.freeze(make_spec())
        first = run_optimization(fixture.store, frozen["id"])
        before = len(fixture.store.jobs())
        second = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(first, second)
        self.assertEqual(len(fixture.store.jobs()), before)

    def test_crash_after_candidate_freeze_resumes_without_repeating_controller(self) -> None:
        import evo.optimization as optimization
        fixture = Fixture(self)
        frozen = fixture.freeze(make_spec())
        original_apply = optimization._apply
        crashed = False

        def crash_once(state, proposal):
            nonlocal crashed
            candidate = original_apply(state, proposal)
            if not crashed:
                crashed = True
                raise RuntimeError("synthetic crash after immutable candidate")
            return candidate

        with mock.patch.object(optimization, "_apply", side_effect=crash_once):
            with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                run_optimization(fixture.store, frozen["id"])
        self.assertEqual(len(fixture.store.jobs()), 1)
        resumed = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(resumed["round"], 1)
        state = _state(fixture, frozen)
        self.assertEqual(len(state["controller_studies"]), 1)
        self.assertEqual(len([job for job in fixture.store.jobs() if job["plan"]["combination"] == "controller"]), 1)

    def test_candidate_component_is_consumed_and_improvement_is_promoted(self) -> None:
        fixture = Fixture(self)
        spec = make_spec()
        for item in spec["evaluations"]["items"]:
            item["runtime"]["argv"] = component_subject_argv()
        spec["fields"].extend([
            {"id": "cost.tokens", "type": "integer", "unit": "token", "grain": "attempt", "source": "candidate consumer"},
            {"id": "observed.rule", "type": "string", "unit": "text", "grain": "attempt", "source": "candidate consumer"},
        ])
        spec["scoring"].append({"id": "cost", "version": "1", "group_by": ["combination", "family"],
                                "metrics": [{"id": "tokens", "unit": "token", "expression": {"aggregate": "mean", "field": "cost.tokens"}}]})
        spec["optimization"]["promotion"]["objectives"] = [{"scoring": "cost", "metric": "tokens", "direction": "min"}]
        frozen = fixture.freeze(spec)
        result = run_optimization(fixture.store, frozen["id"])
        self.assertNotEqual(result["champion"], result["baseline"])
        champion = Path(export(fixture.store, frozen["id"])["candidate_root"])
        self.assertEqual((champion / "agents_md" / "rules" / "rules.txt").read_text(encoding="utf-8"), "candidate\n")
        selection_studies = _state(fixture, frozen)["evaluation_studies"][1:3]
        observed = []
        from evo.runtime import artifacts
        for study in selection_studies:
            observed.extend(row["values"]["observed.rule"] for row in artifacts(fixture.store, study)["rows"])
        self.assertEqual(set(observed), {"baseline", "candidate"})

    def test_lower_cost_cannot_promote_quality_regression(self) -> None:
        fixture = Fixture(self)
        spec = make_spec(proposal_argv(content="bad\n"))
        for item in spec["evaluations"]["items"]:
            item["runtime"]["argv"] = component_subject_argv()
        spec["fields"].extend([
            {"id": "cost.tokens", "type": "integer", "unit": "token", "grain": "attempt", "source": "candidate consumer"},
            {"id": "observed.rule", "type": "string", "unit": "text", "grain": "attempt", "source": "candidate consumer"},
        ])
        spec["scoring"].append({"id": "cost", "version": "1", "group_by": ["combination", "family"],
                                "metrics": [{"id": "tokens", "unit": "token", "expression": {"aggregate": "mean", "field": "cost.tokens"}}]})
        spec["optimization"]["promotion"]["objectives"] = [{"scoring": "cost", "metric": "tokens", "direction": "min"}]
        frozen = fixture.freeze(spec)
        result = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(result["champion"], result["baseline"])
        self.assertIn("quality regressed", _state(fixture, frozen)["feedback"][0]["reason"])

    def test_explicit_independent_grader_uses_queue_and_is_not_repeated(self) -> None:
        fixture = Fixture(self)
        spec = make_spec()
        grader_script = (
            "import json,sys; data=json.loads(sys.argv[1]); "
            "print(json.dumps({'assessments':[{'row':r['row'],'field':'model.quality','value':r['values']['quality.reward']} for r in data['rows']]}))"
        )
        spec["fields"].append({"id": "model.quality", "type": "number", "unit": "ratio",
                               "grain": "assessment", "source": "independent grader"})
        spec["scoring"].append({"id": "model-score", "version": "1", "group_by": ["combination", "family"],
                                "metrics": [{"id": "quality", "unit": "ratio", "expression": {"aggregate": "mean", "field": "model.quality"}}]})
        spec["grading"] = [{
            "id": "independent", "version": "1", "rubric": "copy the observed quality for this fixture",
            "select": {"grains": ["attempt"], "fields": ["quality.reward"]},
            "outputs": [{"field": "model.quality", "minimum": 0, "maximum": 2}],
            "controller": {"adapter": "command", "argv": [sys.executable, "-X", "utf8", "-c", grader_script, "{grading_json}"],
                           "token_budget": 100, "timeout_seconds": 10},
        }]
        spec["optimization"]["grading"] = ["independent"]
        spec["optimization"]["promotion"]["quality_metrics"] = [{"scoring": "model-score", "metric": "quality", "direction": "max"}]
        frozen = fixture.freeze(spec)
        first = run_optimization(fixture.store, frozen["id"])
        state = _state(fixture, frozen)
        self.assertEqual(len(state["grader_studies"]), 3)
        self.assertTrue(all(fixture.store.status(study)["counts"] == {"completed": 1} for study in state["grader_studies"]))
        before = len(fixture.store.jobs())
        second = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(second, first)
        self.assertEqual(len(fixture.store.jobs()), before)

    def test_out_of_scope_edit_fails_before_candidate_evaluation(self) -> None:
        fixture = Fixture(self)
        frozen = fixture.freeze(make_spec(proposal_argv(path="other.txt")))
        with self.assertRaisesRegex(EvoError, "outside mutable scope"):
            run_optimization(fixture.store, frozen["id"])
        state = _state(fixture, frozen)
        self.assertEqual(state["round"], 0)
        self.assertEqual(state["evaluation_studies"], [])

    def test_budget_stops_before_controller_without_creating_jobs(self) -> None:
        fixture = Fixture(self)
        spec = make_spec()
        spec["optimization"]["controller"]["token_reservation"] = 101
        frozen = fixture.freeze(spec)
        result = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(result["state"], "stopped")
        self.assertIn("budget", result["stop_reason"])
        self.assertEqual(fixture.store.jobs(), [])

    def test_human_wait_is_persisted_and_resume_does_not_restart_work(self) -> None:
        fixture = Fixture(self)
        spec = make_spec()
        spec["fields"].append({"id": "human.score", "type": "number", "unit": "ratio",
                               "grain": "assessment", "source": "human review"})
        spec["evaluations"]["items"][0]["runtime"]["rubric"] = {
            "scoring": "quality", "fields": ["human.score"], "blind": True,
        }
        frozen = fixture.freeze(spec)
        first = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(first["state"], "awaiting_human", first)
        self.assertEqual(first["awaiting"]["split"], "development")
        before = [(job["id"], job["state"], job["receipt"]) for job in fixture.store.jobs()]
        second = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(second, first)
        self.assertEqual([(job["id"], job["state"], job["receipt"]) for job in fixture.store.jobs()], before)

    def test_family_cannot_leak_between_splits(self) -> None:
        spec = make_spec()
        spec["evaluations"]["items"][2]["family"] = "selection-family"
        with self.assertRaisesRegex(EvoError, "leaks"):
            validate_optimization(spec)

    def test_patience_stops_before_an_extra_controller_or_final(self) -> None:
        fixture = Fixture(self)
        spec = make_spec()
        spec["optimization"]["rounds"]["max"] = 3
        frozen = fixture.freeze(spec)
        result = run_optimization(fixture.store, frozen["id"])
        state = _state(fixture, frozen)
        self.assertEqual(result["state"], "stopped")
        self.assertEqual(result["round"], 1)
        self.assertEqual(len(state["controller_studies"]), 1)
        self.assertIsNone(result["final_study"])

    def test_two_selection_studies_cannot_reserve_the_same_remaining_budget(self) -> None:
        import evo.optimization as optimization
        fixture = Fixture(self)
        spec = make_spec()
        spec["optimization"]["splits"]["development"] = []
        spec["optimization"]["budget"]["max_total_tokens"] = 100
        for item in spec["evaluations"]["items"]:
            item["runtime"] = {"adapter": "codex", "model": "synthetic", "reasoning_effort": "low",
                               "prompt": "unused", "timeout_seconds": 10, "max_agents": 1, "token_reservation": 60}
        frozen = fixture.freeze(spec)
        original_run = optimization.runtime.run

        def hold_codex(store, *, study=None, installed_codex_root=None):
            jobs = store.jobs(study)
            if jobs and jobs[0]["runtime"]["adapter"] == "codex":
                return store.status(study)
            return original_run(store, study=study, installed_codex_root=installed_codex_root)

        with mock.patch.object(optimization.runtime, "run", side_effect=hold_codex):
            result = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(result["state"], "stopped")
        self.assertIn("budget", result["stop_reason"])
        self.assertEqual(len(_state(fixture, frozen)["evaluation_studies"]), 1)

    def test_final_threshold_rejects_failed_quality_without_relabeling_execution(self) -> None:
        fixture = Fixture(self)
        spec = make_spec()
        for item in spec["evaluations"]["items"][:2]:
            item["runtime"]["argv"] = component_subject_argv()
        final_script = "import json; print(json.dumps({'quality.reward':0,'cost.tokens':0,'observed.rule':'failed-final'}))"
        spec["evaluations"]["items"][2]["runtime"]["argv"] = [sys.executable, "-X", "utf8", "-c", final_script]
        spec["fields"].extend([
            {"id": "cost.tokens", "type": "integer", "unit": "token", "grain": "attempt", "source": "candidate consumer"},
            {"id": "observed.rule", "type": "string", "unit": "text", "grain": "attempt", "source": "candidate consumer"},
        ])
        spec["optimization"]["final_acceptance"] = {
            "thresholds": [{"scoring": "quality", "metric": "reward", "minimum": 1}]
        }
        frozen = fixture.freeze(spec)
        result = run_optimization(fixture.store, frozen["id"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["final_acceptance"]["status"], "rejected")
        self.assertIn("below threshold", result["final_acceptance"]["reason"])

    def test_real_model_fixture_is_structurally_valid_without_running_models(self) -> None:
        path = EVALUATION_ROOT / "tests" / "fixtures" / "evo" / "optimization" / "research-codex-controller.json"
        spec = load_spec(path)
        config = validate_optimization(spec)
        self.assertEqual(config["controller"]["model"], "gpt-5.6-sol")
        self.assertEqual(config["grading"], ["marker-grader"])
        self.assertEqual(config["budget"], {"max_total_tokens": 500000, "max_controller_tokens": 150000})

    def test_real_fixture_agents_file_is_consumed_by_command_without_models(self) -> None:
        source = EVALUATION_ROOT / "tests" / "fixtures" / "evo" / "optimization" / "research-codex-controller.json"
        spec = load_spec(source)
        spec["optimization"]["controller"] = {
            "adapter": "command", "argv": proposal_argv(path="AGENTS.md", content="MODE=optimized\n"), "timeout_seconds": 10,
        }
        spec["optimization"]["grading"] = []
        spec["optimization"]["promotion"]["quality_metrics"] = [
            {"scoring": "behavior-quality", "metric": "pass", "direction": "max"}
        ]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            store = Store(temporary / "state")
            store.initialize(concurrency=1, model_capacity=2, max_disk_mb=64, min_free_mb=1)
            local_spec = temporary / "research.json"
            local_spec.write_text(json.dumps(spec), encoding="utf-8")
            repository = EVALUATION_ROOT.parents[1]
            frozen = start(store, local_spec, repository, temporary / "work")
            result = run_optimization(store, frozen["id"])
            self.assertNotEqual(result["champion"], result["baseline"])
            candidate = Path(export(store, frozen["id"])["candidate_root"]) / "agents_md" / "rules" / "AGENTS.md"
            self.assertEqual(candidate.read_text(encoding="utf-8"), "MODE=optimized\n")

    def test_single_file_codex_setting_preserves_toml_name_and_projects(self) -> None:
        import agentbase_codex
        fixture = Fixture(self)
        settings = fixture.project / "settings.toml"
        settings.write_text('model = "baseline-model"\n', encoding="utf-8")
        spec = make_spec()
        spec["components"]["agents_md"] = []
        spec["components"]["codex_settings"] = [{"id": "settings", "source": "settings.toml"}]
        spec["combinations"][0]["members"] = {"codex_settings": ["settings"]}
        spec["optimization"]["mutable"] = [{"kind": "codex_settings", "id": "settings", "paths": ["settings.toml"]}]
        frozen = fixture.freeze(spec)
        state = _state(fixture, frozen)
        state["state_root"] = str(fixture.state)
        candidate = _apply(state, {
            "schema": "agentbase-evo-proposal/v1", "hypothesis": "change selected model",
            "edits": [{"kind": "codex_settings", "id": "settings", "path": "settings.toml",
                       "content": 'model = "candidate-model"\n'}],
        })
        candidate_file = Path(state["candidate_sources"][candidate]["codex_settings/settings"])
        self.assertEqual(candidate_file.name, "settings.toml")
        generated = _evaluation_spec(state, [candidate], "selection", 1)
        combo = generated["combinations"][0]
        members = set(combo["members"]["codex_settings"])
        selected = {"codex_settings": [entry for entry in generated["components"]["codex_settings"] if entry["id"] in members]}
        workspace = Path(fixture.temp.name) / "projection"
        workspace.mkdir()
        agentbase_codex.stage_codex_component_projection(
            project_root=fixture.project, workspace=workspace, selected=selected,
            candidate_source_roots=[fixture.state / "candidates" / candidate],
        )
        projected = tomllib.loads((workspace / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(projected["model"], "candidate-model")

    def test_initial_mutable_source_outside_project_is_rejected_by_shared_owner(self) -> None:
        fixture = Fixture(self)
        outside = Path(fixture.temp.name) / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        spec = make_spec()
        spec["components"]["agents_md"][0]["source"] = str(outside)
        path = fixture.project / "outside-source.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaisesRegex(EvoError, "outside allowed roots"):
            start(fixture.store, path, fixture.project, fixture.work)


def _state(fixture: Fixture, frozen: dict) -> dict:
    return json.loads((fixture.state / "optimizations" / f"{frozen['id']}.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
