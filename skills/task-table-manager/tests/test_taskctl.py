from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "taskctl.py"
SPEC = importlib.util.spec_from_file_location("taskctl_under_test", SCRIPT)
assert SPEC and SPEC.loader
TASKCTL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TASKCTL)

SEMANTIC_IDENTITIES = [
    "historical:alpha",
    "historical:beta",
    "historical:delta",
    "historical:gamma",
]


def claim_rule() -> dict[str, object]:
    return {
        "producers": ["machine"],
        "source_classes": ["registered_machine"],
        "freshness_keys": ["contract", "production_scope", "test_scope"],
        "min_evidence": 1,
    }


def task(
    task_id: str,
    requirement_id: str,
    claims: list[str],
    *,
    depends_on: list[dict[str, object]] | None = None,
    tests_first: str = "prequalified",
) -> dict[str, object]:
    acceptance_clause_id = f"AC-{requirement_id}"
    solution_step_id = f"SOL-{task_id}"
    gap_id = f"GAP-{task_id}"
    boundary = {
        "owner": f"owner:{task_id}",
        "identity": f"identity:{task_id}",
        "lifecycle": f"lifecycle:{task_id}",
        "persistence": f"persistence:{task_id}",
        "build": f"build:{task_id}",
    }
    return {
        "id": task_id,
        "outcome": f"Verified outcome for {task_id}",
        "completion_level": "module_ready",
        "claim_scope": [f"asset:{task_id}"],
        "scope_enforced": False,
        "requirement_ids": [requirement_id],
        "acceptance_clause_ids": [acceptance_clause_id],
        "solution_step_ids": [solution_step_id],
        "gap_ids": [gap_id],
        "uncertainty_boundary": boundary,
        "depends_on": depends_on or [],
        "context_refs": ["docs/design.md"],
        "mutation_scope": [f"src/{task_id}.txt"],
        "test_scope": [f"tests/{task_id}.txt"],
        "freshness_scopes": {},
        "build_profile": "local",
        "rollback_scope": f"scope:{task_id}",
        "package_key": "package:default",
        "claim_profile": "default",
        "claim_overrides": {
            "required_claims": claims,
            "automation_test_ids": [f"test.{task_id}"],
            "readback_subjects": [f"asset:{task_id}"],
        },
        "tests_first": {
            "mode": tests_first,
            "reason": "already qualified" if tests_first != "required" else "",
            "expected_red_producer": "machine" if tests_first == "required" else "",
        },
    }


def make_plan(
    *,
    first_claims: list[str] | None = None,
    two_tasks: bool = False,
    tests_first: str = "prequalified",
) -> dict[str, object]:
    first_claims = first_claims or ["behavior"]
    all_claims = set(first_claims) | {"integration"}
    requirements: list[dict[str, object]] = [
        {
            "id": "R1",
            "source_ref": "design:R1",
            "source_fingerprint": "design-v1",
            "status": "in_scope",
            "verification_mode": "task_evidence",
            "acceptance_scope": ["asset:T1"],
            "observable_claims": first_claims,
        }
    ]
    tasks = [task("T1", "R1", first_claims, tests_first=tests_first)]
    qualifications: dict[str, object] = {
        "test.T1": {
            "requirement_ids": ["R1"],
            "subject": "asset:T1",
            "oracle_source": "design:R1",
            "baseline": "before implementation",
            "claim_dimensions": first_claims,
            "negative_paths": ["invalid input"],
            "trust_state": "qualified",
            "source_fingerprint": "test-t1-v1",
        }
    }
    if two_tasks:
        requirements.append(
            {
                "id": "R2",
                "source_ref": "design:R2",
                "source_fingerprint": "design-v1",
                "status": "in_scope",
                "verification_mode": "task_evidence",
                "acceptance_scope": ["asset:T2"],
                "observable_claims": ["integration"],
            }
        )
        tasks.append(
            task(
                "T2",
                "R2",
                ["integration"],
                depends_on=[{"task_id": "T1", "claims": [first_claims[0]]}],
            )
        )
        qualifications["test.T2"] = {
            "requirement_ids": ["R2"],
            "subject": "asset:T2",
            "oracle_source": "design:R2",
            "baseline": "before implementation",
            "claim_dimensions": ["integration"],
            "negative_paths": ["invalid dependency"],
            "trust_state": "qualified",
            "source_fingerprint": "test-t2-v1",
        }
    requirement_ids = [item["id"] for item in requirements]
    acceptance_clauses = [
        {
            "id": f"AC-{requirement_id}",
            "requirement_id": requirement_id,
            "statement": f"The observable outcome for {requirement_id} is satisfied",
            "verification_scope": [f"asset:T{index + 1}"],
            "required_claims": requirements[index]["observable_claims"],
            "source_ref": f"design:AC-{requirement_id}",
            "source_fingerprint": "pending",
            "origin_kind": "user_explicit",
            "origin_ref": f"user:{requirement_id}",
        }
        for index, requirement_id in enumerate(requirement_ids)
    ]
    design_clauses = [
        {
            "id": f"DES-{requirement_id}",
            "statement": f"Design decision for {requirement_id}",
            "source_ref": f"design:DES-{requirement_id}",
            "source_fingerprint": "pending",
            "acceptance_clause_ids": [f"AC-{requirement_id}"],
        }
        for requirement_id in requirement_ids
    ]
    solution_steps = []
    gap_items = []
    for task_value in tasks:
        requirement_id = task_value["requirement_ids"][0]
        task_id = task_value["id"]
        solution_steps.append(
            {
                "id": f"SOL-{task_id}",
                "action": f"Implement the solution for {task_id}",
                "expected_result": f"Produce the verified outcome for {task_id}",
                "source_ref": f"design:SOL-{task_id}",
                "source_fingerprint": "pending",
                "design_clause_ids": [f"DES-{requirement_id}"],
                "depends_on": [
                    f"SOL-{edge['task_id']}" for edge in task_value["depends_on"]
                ],
                "must_not_depend_on": [],
                "uncertainty_boundary": task_value["uncertainty_boundary"],
            }
        )
        gap_items.append(
            {
                "id": f"GAP-{task_id}",
                "finding": f"The outcome for {task_id} is not yet implemented",
                "source_ref": f"design:GAP-{task_id}",
                "source_fingerprint": "pending",
                "solution_step_ids": [f"SOL-{task_id}"],
                "status": "missing",
            }
        )
    trace_ids = [
        *requirement_ids,
        *(item["id"] for item in acceptance_clauses),
        *(item["id"] for item in design_clauses),
        *(item["id"] for item in solution_steps),
        *(item["id"] for item in gap_items),
    ]
    source_payload = ("\n".join(trace_ids) + "\n").encode("utf-8")
    source_fingerprint = TASKCTL._sha256_bytes(source_payload)
    for requirement in requirements:
        requirement["source_fingerprint"] = source_fingerprint
    for item in [*acceptance_clauses, *design_clauses, *solution_steps, *gap_items]:
        item["source_fingerprint"] = source_fingerprint
    return {
        "schema": "task.plan.v1",
        "plan_id": "fixture-plan",
        "design_revision": "design-v1",
        "enforcement_profile": "strict_v2",
        "scope_sources": [
            {
                "id": "design",
                "ref": "docs/design.md",
                "fingerprint": source_fingerprint,
                "inventory_mode": "exact",
                "requirement_ids": requirement_ids,
                "fingerprint_mode": "file_sha256",
                "root": "project",
                "source_audit_ref": "user:fixture-design-audit",
                "inventory_prefix": "R",
                "acceptance_clause_ids": [item["id"] for item in acceptance_clauses],
                "acceptance_clause_prefix": "AC-",
                "design_clause_ids": [item["id"] for item in design_clauses],
                "design_clause_prefix": "DES-",
                "solution_step_ids": [item["id"] for item in solution_steps],
                "solution_step_prefix": "SOL-",
                "gap_ids": [item["id"] for item in gap_items],
                "gap_prefix": "GAP-",
            }
        ],
        "requirements": requirements,
        "acceptance_clauses": acceptance_clauses,
        "design_clauses": design_clauses,
        "solution_steps": solution_steps,
        "gap_items": gap_items,
        "planning_audit": {"receipt_ref": "planning-audit.json"},
        "semantic_preflight": {
            "mode": "not_applicable",
            "reason": "fixture plan has no bulk identity migration",
        },
        "producers": {
            "machine": {
                "version": "1",
                "source_class": "registered_machine",
                "source_ref": "tests.fixture:machine",
                "allowed_claims": sorted(all_claims),
                "envelope_schema": "task.evidence.v1",
                "requires_raw_artifacts": False,
            }
        },
        "evidence_profiles": {
            "default": {
                "required_claims": [first_claims[0]],
                "claim_rules": {claim: claim_rule() for claim in sorted(all_claims)},
            }
        },
        "test_qualifications": qualifications,
        "groups": [{"id": "G1", "title": "Fixture", "task_ids": [item["id"] for item in tasks]}],
        "tasks": tasks,
    }


def declare_semantic_preflight(
    plan: dict[str, object],
    *,
    receipt_ref: str = "semantic-preflight.design-v1.json",
    dimensions: list[str] | None = None,
) -> None:
    semantic_sources = {
        "semantic-identities": "semantic-identities.json",
        "semantic-verifier": "task_tools/semantic-verifier.py",
    }
    known_sources = {source["id"] for source in plan["scope_sources"]}
    for source_id, source_ref in semantic_sources.items():
        if source_id in known_sources:
            continue
        plan["scope_sources"].append(
            {
                "id": source_id,
                "ref": source_ref,
                "fingerprint": "sha256:" + "0" * 64,
                "inventory_mode": "advisory",
                "requirement_ids": [],
                "fingerprint_mode": "file_sha256",
                "root": "task",
            }
        )
    plan["semantic_preflight"] = {
        "mode": "required",
        "reason": "fixture exercises bulk historical identity migration",
        "receipt_ref": receipt_ref,
        "identity_source_id": "semantic-identities",
        "producer_source_id": "semantic-verifier",
        "scope_source_ids": ["semantic-identities", "semantic-verifier"],
        "expected_total_count": len(SEMANTIC_IDENTITIES),
        "identity_set_fingerprint": TASKCTL._json_identity(
            SEMANTIC_IDENTITIES
        ),
        "required_dimensions": dimensions
        or sorted(TASKCTL.SEMANTIC_PREFLIGHT_CORE_DIMENSIONS),
    }


def declare_legacy_semantic_preflight(plan: dict[str, object]) -> None:
    declare_semantic_preflight(plan)
    semantic = plan["semantic_preflight"]
    plan["semantic_preflight"] = {
        key: semantic[key]
        for key in (
            "receipt_ref",
            "producer_source_id",
            "scope_source_ids",
            "required_dimensions",
        )
    }


class TaskCtlTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.plan_dir = self.project / "docs" / "plan" / "20260804_FIXTURE"
        self.plan_dir.mkdir(parents=True)
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs" / "design.md").write_text("design", encoding="utf-8")

    def write_plan(self, plan: dict[str, object], *, sync_sources: bool = True) -> None:
        if sync_sources:
            for source in plan.get("scope_sources", []):
                if (
                    source.get("fingerprint_mode") != "file_sha256"
                    or source.get("root") not in {"project", "task"}
                ):
                    continue
                root = self.project if source["root"] == "project" else self.plan_dir
                source_path = root / source["ref"]
                source_path.parent.mkdir(parents=True, exist_ok=True)
                if source.get("requirement_ids"):
                    inventory_ids = [
                        *source.get("requirement_ids", []),
                        *source.get("acceptance_clause_ids", []),
                        *source.get("design_clause_ids", []),
                        *source.get("solution_step_ids", []),
                        *source.get("gap_ids", []),
                    ]
                    source_path.write_bytes(
                        ("\n".join(inventory_ids) + "\n").encode("utf-8")
                    )
                elif source["id"] == "semantic-identities":
                    source_path.write_bytes(TASKCTL._pretty_bytes(SEMANTIC_IDENTITIES))
                else:
                    source_path.write_text(
                        "# deterministic fixture verifier\n", encoding="utf-8"
                    )
                fingerprint = TASKCTL._sha256_file(source_path)
                source["fingerprint"] = fingerprint
                source_id = source["id"]
                for requirement in plan["requirements"]:
                    if requirement["source_ref"] == source_id or requirement[
                        "source_ref"
                    ].startswith(source_id + ":"):
                        requirement["source_fingerprint"] = fingerprint
                for collection_name in (
                    "acceptance_clauses",
                    "design_clauses",
                    "solution_steps",
                    "gap_items",
                ):
                    for item in plan.get(collection_name, []):
                        if item["source_ref"] == source_id or item["source_ref"].startswith(
                            source_id + ":"
                        ):
                            item["source_fingerprint"] = fingerprint
        for item in plan["tasks"]:
            task_id = item["id"]
            source = self.project / "src" / f"{task_id}.txt"
            test_source = self.project / "tests" / f"{task_id}.txt"
            source.parent.mkdir(exist_ok=True)
            test_source.parent.mkdir(exist_ok=True)
            source.write_text(f"source {task_id}", encoding="utf-8")
            test_source.write_text(f"test {task_id}", encoding="utf-8")
        self.write_json(self.plan_dir / "plan.json", plan)

    def make_source_exact(self, plan: dict[str, object]) -> dict[str, object]:
        requirement_ids = [item["id"] for item in plan["requirements"]]
        trace_ids = [
            *requirement_ids,
            *(item["id"] for item in plan.get("acceptance_clauses", [])),
            *(item["id"] for item in plan.get("design_clauses", [])),
            *(item["id"] for item in plan.get("solution_steps", [])),
            *(item["id"] for item in plan.get("gap_items", [])),
        ]
        design_path = self.project / "docs" / "design.md"
        design_path.write_bytes(("\n".join(trace_ids) + "\n").encode("utf-8"))
        fingerprint = TASKCTL._sha256_file(design_path)
        plan["scope_sources"][0].update(
            {
                "fingerprint": fingerprint,
                "inventory_mode": "exact",
                "requirement_ids": requirement_ids,
                "fingerprint_mode": "file_sha256",
                "root": "project",
                "source_audit_ref": "user:fixture-design-audit",
                "inventory_prefix": "R",
            }
        )
        for requirement in plan["requirements"]:
            requirement["source_fingerprint"] = fingerprint
        for collection_name in (
            "acceptance_clauses",
            "design_clauses",
            "solution_steps",
            "gap_items",
        ):
            for item in plan.get(collection_name, []):
                item["source_fingerprint"] = fingerprint
        return plan

    def set_requirement_acceptance(
        self,
        plan: dict[str, object],
        requirement_id: str,
        clauses: list[tuple[str, str]],
    ) -> None:
        requirement = next(
            item for item in plan["requirements"] if item["id"] == requirement_id
        )
        old_clause_ids = {
            item["id"]
            for item in plan["acceptance_clauses"]
            if item["requirement_id"] == requirement_id
        }
        clause_ids = [clause_id for clause_id, _scope in clauses]
        scope_by_clause_id = dict(clauses)
        requirement["acceptance_scope"] = [scope for _clause_id, scope in clauses]

        plan["acceptance_clauses"] = [
            item
            for item in plan["acceptance_clauses"]
            if item["id"] not in old_clause_ids
        ]
        plan["acceptance_clauses"].extend(
            {
                "id": clause_id,
                "requirement_id": requirement_id,
                "source_ref": f"design:{clause_id}",
                "source_fingerprint": "pending",
                "origin_kind": "user_explicit",
                "origin_ref": f"user:{clause_id}",
            }
            for clause_id, scope in clauses
        )
        for clause in plan["acceptance_clauses"]:
            if clause["id"] not in clause_ids:
                continue
            scope = scope_by_clause_id[clause["id"]]
            clause.update(
                {
                    "statement": f"Verify {scope} for {requirement_id}",
                    "verification_scope": [scope],
                    "required_claims": requirement["observable_claims"],
                }
            )
        for design_clause in plan["design_clauses"]:
            if old_clause_ids & set(design_clause["acceptance_clause_ids"]):
                design_clause["acceptance_clause_ids"] = clause_ids
        for task_value in plan["tasks"]:
            if requirement_id in task_value["requirement_ids"]:
                task_value["acceptance_clause_ids"] = clause_ids
        source = plan["scope_sources"][0]
        source["acceptance_clause_ids"] = [
            item["id"] for item in plan["acceptance_clauses"]
        ]

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_semantic_receipt(
        self,
        plan: dict[str, object] | None = None,
        *,
        count_overrides: dict[str, object] | None = None,
        status: str | None = None,
        source_fingerprints: dict[str, str] | None = None,
        identities: list[str] | None = None,
        identity_set_fingerprint: str | None = None,
        schema: str = "task.semantic-preflight.v2",
    ) -> Path:
        plan = plan or self.read_json(self.plan_dir / "plan.json")
        semantic = plan["semantic_preflight"]
        sources = {source["id"]: source for source in plan["scope_sources"]}
        dimensions = semantic["required_dimensions"]
        identities = (
            list(SEMANTIC_IDENTITIES) if identities is None else identities
        )
        counts: dict[str, object] = {
            "total_count": len(identities),
            "resolved_count": len(identities),
            "unresolved_count": 0,
            "placeholder_count": 0,
            "duplicate_count": 0,
            "dimension_unresolved_counts": {
                dimension: 0 for dimension in dimensions
            },
        }
        if count_overrides:
            dimension_overrides = count_overrides.get(
                "dimension_unresolved_counts"
            )
            counts.update(
                {
                    key: value
                    for key, value in count_overrides.items()
                    if key != "dimension_unresolved_counts"
                }
            )
            if dimension_overrides is not None:
                counts["dimension_unresolved_counts"].update(
                    dimension_overrides
                )
        blocked = (
            counts["unresolved_count"] != 0
            or counts["placeholder_count"] != 0
            or counts["duplicate_count"] != 0
            or any(counts["dimension_unresolved_counts"].values())
        )
        receipt = {
            "schema": schema,
            "plan_id": plan["plan_id"],
            "design_revision": plan["design_revision"],
            "producer_source_id": semantic["producer_source_id"],
            "source_fingerprints": source_fingerprints
            or {
                source_id: sources[source_id]["fingerprint"]
                for source_id in semantic["scope_source_ids"]
            },
            "status": status or ("blocked" if blocked else "pass"),
            "counts": counts,
        }
        if schema == "task.semantic-preflight.v2":
            receipt.update(
                {
                    "identity_set_fingerprint": identity_set_fingerprint
                    or TASKCTL._json_identity(identities),
                    "identities": identities,
                }
            )
        path = self.plan_dir / semantic["receipt_ref"]
        self.write_json(path, receipt)
        return path

    def command(self, *arguments: str, ok: bool = True) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=self.project,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        stream = result.stdout if result.stdout.strip() else result.stderr
        payload = json.loads(stream)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["ok"], payload)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertFalse(payload["ok"], payload)
        return payload

    def activate(self) -> dict[str, object]:
        self.command("audit-plan", "--task-dir", str(self.plan_dir))
        return self.command("activate", "--plan-dir", str(self.plan_dir))

    def audit_candidate(self, candidate: Path) -> dict[str, object]:
        return self.command(
            "audit-plan",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate),
        )

    def state(self) -> dict[str, object]:
        return self.read_json(self.plan_dir / "state.json")

    def begin(self, task_id: str) -> dict[str, object]:
        return self.command(
            "begin",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            task_id,
            "--expected-revision",
            str(self.state()["revision"]),
        )

    def evidence(
        self,
        evidence_id: str,
        task_id: str,
        claims: list[str],
        *,
        phase: str = "verification",
        result: str = "pass",
        started_at: str = "2026-08-04T00:02:00Z",
        completed_at: str = "2026-08-04T00:03:00Z",
        producer: str = "machine",
        raw_artifacts: list[dict[str, str]] | None = None,
        freshness: dict[str, str] | None = None,
        test_ids: list[str] | None = None,
        subjects: list[str] | None = None,
    ) -> Path:
        plan = self.read_json(self.plan_dir / "plan.json")
        state = self.state()
        task_by_id = {item["id"]: item for item in plan["tasks"]}
        identities = TASKCTL._task_identities(plan, task_by_id[task_id], self.project)
        envelope = {
            "schema": "task.evidence.v1",
            "evidence_id": evidence_id,
            "plan_id": plan["plan_id"],
            "plan_revision": state["plan_revision"],
            "task_ids": [task_id],
            "type": "fixture",
            "phase": phase,
            "source_class": "registered_machine",
            "producer": {"id": producer, "version": "1"},
            "result": result,
            "claims": claims,
            "subjects": (
                (task_by_id[task_id]["claim_scope"] if result == "pass" else [])
                if subjects is None
                else subjects
            ),
            "test_ids": [f"test.{task_id}"] if test_ids is None else test_ids,
            "freshness_identity": freshness
            or {key: identities[key] for key in ("contract", "production_scope", "test_scope")},
            "raw_artifacts": raw_artifacts or [],
            "started_at": started_at,
            "completed_at": completed_at,
            "summary": {"fixture": True},
        }
        path = self.project / "reports" / f"{evidence_id}.json"
        self.write_json(path, envelope)
        return path

    def close(self, *evidence: Path) -> dict[str, object]:
        arguments = [
            "close",
            "--plan-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
        ]
        for path in evidence:
            arguments.extend(["--evidence", str(path)])
        return self.command(*arguments)

    def test_task_dir_is_explicit_absolute_and_plan_dir_alias_is_compatible(self) -> None:
        self.write_plan(make_plan())
        relative_task_dir = self.plan_dir.relative_to(self.project)
        rejected = self.command(
            "validate", "--task-dir", str(relative_task_dir), ok=False
        )
        self.assertEqual(rejected["error"]["code"], "task_dir_not_absolute")

        canonical = self.command("validate", "--task-dir", str(self.plan_dir))
        compatibility = self.command("validate", "--plan-dir", str(self.plan_dir))
        self.assertEqual(canonical["plan_revision"], compatibility["plan_revision"])

    def test_relative_task_inputs_resolve_from_task_dir(self) -> None:
        self.write_plan(make_plan())
        self.activate()

        candidate = make_plan()
        candidate["design_revision"] = "candidate"
        self.write_json(self.plan_dir / "candidate.json", candidate)
        preview = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            "candidate.json",
        )
        self.assertTrue(preview["preview"])

        self.begin("T1")
        self.write_json(
            self.plan_dir / "unresolved.json",
            {
                "items": [
                    {
                        "type": "missing_input",
                        "subject": "fixture",
                        "next_action": "provide fixture",
                    }
                ]
            },
        )
        self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--next-action",
            "continue",
            "--unresolved",
            "unresolved.json",
        )
        self.assertEqual(
            self.state()["active_package"]["unresolved"][0]["subject"], "fixture"
        )

    def test_relative_evidence_resolves_from_task_dir(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        self.begin("T1")
        report = self.evidence("task-relative", "T1", ["behavior"])
        relative_report = self.plan_dir / "inputs" / "task-relative.json"
        self.write_json(relative_report, self.read_json(report))

        result = self.command(
            "close",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            "inputs/task-relative.json",
        )
        self.assertEqual(result["completed"], ["T1"])

    def test_checkpoint_release_allows_contract_amendment(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        self.begin("T1")

        released = self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--next-action",
            "expand the production scope",
            "--release",
        )
        self.assertTrue(released["ok"])
        self.assertIsNone(self.state()["active_package"])
        self.assertEqual(self.state()["task_states"]["T1"]["status"], "ready")
        self.assertEqual(
            self.state()["task_states"]["T1"]["baseline_identity"], {}
        )

        candidate = make_plan()
        candidate["tasks"][0]["mutation_scope"].append("src/new_header.h")
        candidate_path = self.plan_dir / "candidate.json"
        self.write_json(candidate_path, candidate)
        self.audit_candidate(candidate_path)
        amended = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            "candidate.json",
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
        )
        self.assertFalse(amended["preview"])

    def test_checkpoint_release_is_the_recovery_edge_for_source_drift(self) -> None:
        plan = self.make_source_exact(make_plan())
        self.write_plan(plan)
        self.activate()
        self.begin("T1")

        design_path = self.project / "docs" / "design.md"
        design_path.write_text(
            design_path.read_text(encoding="utf-8") + "upstream changed\n",
            encoding="utf-8",
        )
        blocked = self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--next-action",
            "continue",
            ok=False,
        )
        self.assertEqual(blocked["error"]["code"], "source_drift")

        released = self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--next-action",
            "amend the changed upstream source",
            "--release",
        )
        self.assertTrue(released["ok"])
        self.assertIsNone(self.state()["active_package"])

    def test_relative_project_root_is_rejected(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        rejected = self.command(
            "resume",
            "--task-dir",
            str(self.plan_dir),
            "--project-root",
            ".",
            ok=False,
        )
        self.assertEqual(rejected["error"]["code"], "project_root_not_absolute")

    def test_candidate_and_checkpoint_inputs_must_stay_in_task_dir(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        outside_candidate = self.project / "candidate.json"
        self.write_json(outside_candidate, make_plan())
        rejected_candidate = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(outside_candidate),
            ok=False,
        )
        self.assertEqual(rejected_candidate["error"]["code"], "task_input_outside_root")

        self.begin("T1")
        outside_unresolved = self.project / "unresolved.json"
        self.write_json(outside_unresolved, {"items": []})
        rejected_unresolved = self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--next-action",
            "continue",
            "--unresolved",
            str(outside_unresolved),
            ok=False,
        )
        self.assertEqual(rejected_unresolved["error"]["code"], "task_input_outside_root")

    def test_validate_rejects_unknown_fields_and_cycles(self) -> None:
        plan = make_plan()
        plan["unexpected"] = True
        self.write_plan(plan)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("unknown fields", payload["error"]["message"])

        cyclic = make_plan(two_tasks=True)
        cyclic["tasks"][0]["depends_on"] = [{"task_id": "T2", "claims": ["integration"]}]
        self.write_plan(cyclic)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("cycle", payload["error"]["message"])

    def test_plan_requires_registered_sources_and_observable_in_scope_claims(self) -> None:
        plan = make_plan()
        plan["scope_sources"] = []
        self.write_plan(plan)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("scope_sources", payload["error"]["message"])

        plan = make_plan()
        plan["requirements"][0]["observable_claims"] = []
        self.write_plan(plan)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("observable_claims", payload["error"]["message"])

    def test_new_plan_requires_strict_profile_and_legacy_state_cannot_complete(self) -> None:
        plan = make_plan()
        plan.pop("enforcement_profile")
        plan.pop("semantic_preflight")
        self.write_plan(plan)
        rejected = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertEqual(rejected["error"]["code"], "strict_profile_required")

        strict_plan = make_plan()
        self.write_plan(strict_plan)
        self.activate()
        legacy_plan = self.read_json(self.plan_dir / "plan.json")
        legacy_plan.pop("enforcement_profile")
        legacy_plan.pop("semantic_preflight")
        self.write_json(self.plan_dir / "plan.json", legacy_plan)
        state = self.state()
        state["plan_revision"] = TASKCTL._plan_hash(legacy_plan)
        self.write_json(self.plan_dir / "state.json", state)

        resumed = self.command("resume", "--task-dir", str(self.plan_dir))
        self.assertEqual(resumed["enforcement_profile"], "legacy_compat")
        self.assertFalse(resumed["completion_allowed"])
        audit = self.command("audit", "--task-dir", str(self.plan_dir), "--all", ok=False)
        self.assertEqual(audit["plan_failures"][0]["type"], "pipeline_profile_required")
        self.assertIsNone(audit["completion_receipt"])

    def test_migrate_strict_makes_implicit_legacy_contract_explicit(self) -> None:
        plan = make_plan()
        plan.pop("enforcement_profile")
        plan.pop("semantic_preflight")
        requirement = plan["requirements"][0]
        task_value = plan["tasks"][0]
        task_value.pop("completion_level")
        task_value.pop("claim_scope")
        task_value.pop("scope_enforced")
        self.write_plan(plan)

        migrated = self.command("migrate-strict", "--task-dir", str(self.plan_dir))
        self.assertGreater(migrated["inferred_field_count"], 0)
        self.assertNotIn("inferred_fields", migrated)
        candidate = self.read_json(Path(migrated["candidate"]))
        self.assertEqual(candidate["enforcement_profile"], "strict_v1")
        self.assertEqual(candidate["requirements"][0]["verification_mode"], "task_evidence")
        self.assertEqual(candidate["tasks"][0]["completion_level"], "module_ready")
        self.assertEqual(candidate["tasks"][0]["claim_scope"], ["asset:T1"])
        self.assertFalse(candidate["tasks"][0]["scope_enforced"])
        TASKCTL._validate_plan(candidate)

    def test_migrate_strict_rejects_non_durable_requirement_source(self) -> None:
        plan = make_plan()
        plan.pop("enforcement_profile")
        plan.pop("semantic_preflight")
        source = plan["scope_sources"][0]
        source.update(
            {
                "fingerprint": "design-v1",
                "inventory_mode": "exact",
                "fingerprint_mode": "label",
            }
        )
        source.pop("root")
        for ids_field, prefix_field in TASKCTL.TRACE_SOURCE_INVENTORIES.values():
            source.pop(ids_field, None)
            source.pop(prefix_field, None)
        plan["requirements"][0]["source_fingerprint"] = "design-v1"
        self.write_plan(plan, sync_sources=False)

        rejected = self.command(
            "migrate-strict", "--task-dir", str(self.plan_dir), ok=False
        )
        self.assertIn("non_file_sha256=design", rejected["error"]["message"])

    def test_strict_profile_rejects_implicit_sources_requirements_and_tasks(self) -> None:
        cases = (
            (
                "source inventory",
                lambda plan: plan["scope_sources"][0].pop("inventory_mode"),
                "inventory_mode",
            ),
            (
                "requirement verification",
                lambda plan: plan["requirements"][0].pop("verification_mode"),
                "verification_mode",
            ),
            (
                "task completion",
                lambda plan: plan["tasks"][0].pop("completion_level"),
                "completion_level",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(label=label):
                plan = make_plan()
                mutate(plan)
                self.write_plan(plan)
                rejected = self.command(
                    "validate", "--task-dir", str(self.plan_dir), ok=False
                )
                self.assertIn(expected, rejected["error"]["message"])

    def test_strict_profile_requires_durable_sources_for_owned_requirements(self) -> None:
        plan = make_plan()
        source = plan["scope_sources"][0]
        source.update(
            {
                "fingerprint": "design-v1",
                "inventory_mode": "advisory",
                "fingerprint_mode": "label",
            }
        )
        for field in ("root", "source_audit_ref", "inventory_prefix"):
            source.pop(field)
        for ids_field, prefix_field in TASKCTL.TRACE_SOURCE_INVENTORIES.values():
            source.pop(ids_field, None)
            source.pop(prefix_field, None)
        plan["requirements"][0]["source_fingerprint"] = "design-v1"
        self.write_plan(plan, sync_sources=False)

        rejected = self.command(
            "validate", "--task-dir", str(self.plan_dir), ok=False
        )
        self.assertIn("non_exact=design", rejected["error"]["message"])

    def test_strict_v2_rejects_rewritten_acceptance_scope(self) -> None:
        plan = make_plan()
        plan["requirements"][0]["acceptance_scope"] = ["AC-R1-NARROWED"]
        self.write_plan(plan)

        rejected = self.command(
            "validate", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(rejected["error"]["code"], "acceptance_scope_drift")
        self.assertIn("source-owned clause", rejected["error"]["message"])

    def test_strict_v2_rejects_unconfirmed_derived_acceptance_clause(self) -> None:
        plan = make_plan()
        plan["acceptance_clauses"][0]["origin_kind"] = "derived_proposal"
        self.write_plan(plan)

        rejected = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(
            rejected["error"]["code"], "unconfirmed_acceptance_clause"
        )

    def test_strict_v2_rejects_solution_dependency_missing_from_tasks(self) -> None:
        plan = make_plan(two_tasks=True)
        plan["tasks"][1]["depends_on"] = []
        self.write_plan(plan)

        rejected = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(rejected["error"]["code"], "solution_dependency_drift")
        self.assertIn("SOL-T1", rejected["error"]["message"])

    def test_strict_v2_rejects_forbidden_solution_dependency(self) -> None:
        plan = make_plan(two_tasks=True)
        plan["solution_steps"][1]["depends_on"] = []
        plan["solution_steps"][1]["must_not_depend_on"] = ["SOL-T1"]
        self.write_plan(plan)

        rejected = self.command(
            "validate", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(
            rejected["error"]["code"], "forbidden_solution_dependency"
        )
        self.assertIn("T1", rejected["error"]["message"])

    def test_strict_v2_rejects_heterogeneous_task_boundary(self) -> None:
        plan = make_plan()
        second_boundary = dict(plan["tasks"][0]["uncertainty_boundary"])
        second_boundary["owner"] = "owner:other"
        plan["solution_steps"].append(
            {
                "id": "SOL-T1-OTHER",
                "action": "Implement a conflicting owner path",
                "expected_result": "Produce the same outcome through another owner",
                "source_ref": "design:SOL-T1-OTHER",
                "source_fingerprint": "pending",
                "design_clause_ids": ["DES-R1"],
                "depends_on": [],
                "must_not_depend_on": [],
                "uncertainty_boundary": second_boundary,
            }
        )
        plan["gap_items"].append(
            {
                "id": "GAP-T1-OTHER",
                "finding": "A conflicting owner path is also missing",
                "source_ref": "design:GAP-T1-OTHER",
                "source_fingerprint": "pending",
                "solution_step_ids": ["SOL-T1-OTHER"],
                "status": "missing",
            }
        )
        plan["scope_sources"][0]["solution_step_ids"].append("SOL-T1-OTHER")
        plan["scope_sources"][0]["gap_ids"].append("GAP-T1-OTHER")
        plan["tasks"][0]["solution_step_ids"].append("SOL-T1-OTHER")
        plan["tasks"][0]["gap_ids"].append("GAP-T1-OTHER")
        self.write_plan(plan)

        rejected = self.command(
            "validate", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(rejected["error"]["code"], "heterogeneous_work_package")

    def test_strict_v2_activation_requires_current_planning_audit(self) -> None:
        plan = make_plan()
        self.write_plan(plan)
        missing = self.command(
            "activate", "--task-dir", str(self.plan_dir), ok=False
        )
        self.assertEqual(missing["error"]["code"], "planning_audit_required")

        audit = self.command("audit-plan", "--task-dir", str(self.plan_dir))
        self.assertEqual(
            audit["audit_scope"], "machine_structural_traceability"
        )
        plan["tasks"][0]["outcome"] = "Changed after planning audit"
        self.write_json(self.plan_dir / "plan.json", plan)
        stale = self.command(
            "activate", "--task-dir", str(self.plan_dir), ok=False
        )
        self.assertEqual(stale["error"]["code"], "planning_audit_required")

    def test_candidate_planning_audit_does_not_replace_active_receipt(self) -> None:
        plan = make_plan()
        self.write_plan(plan)
        active_audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir)
        )
        self.command("activate", "--task-dir", str(self.plan_dir))

        candidate = make_plan()
        candidate["design_revision"] = "design-v2"
        candidate["tasks"][0]["mutation_scope"].append("src/extra.txt")
        candidate_path = self.plan_dir / "candidate.json"
        self.write_json(candidate_path, candidate)
        candidate_audit = self.audit_candidate(candidate_path)

        self.assertNotEqual(active_audit["receipt"], candidate_audit["receipt"])
        self.assertTrue((self.plan_dir / active_audit["receipt"]).is_file())
        self.assertTrue((self.plan_dir / candidate_audit["receipt"]).is_file())
        TASKCTL._verify_planning_audit(
            self.plan_dir,
            self.read_json(self.plan_dir / "plan.json"),
            allow_legacy_missing=False,
        )

    def test_candidate_amend_requires_explicit_semantic_policy(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        candidate = make_plan()
        candidate.pop("semantic_preflight")
        candidate_path = self.plan_dir / "candidate-without-policy.json"
        self.write_json(candidate_path, candidate)

        audit = self.command(
            "audit-plan",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
            ok=False,
        )
        amend = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
            ok=False,
        )

        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_policy_required"
        )
        self.assertEqual(
            amend["error"]["code"], "semantic_preflight_policy_required"
        )

    def test_new_plan_without_semantic_policy_is_blocked(self) -> None:
        plan = make_plan()
        plan.pop("semantic_preflight")
        self.write_plan(plan)

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["structural_status"], "pass")
        self.assertEqual(audit["execution_readiness"], "blocked")
        self.assertFalse(audit["ready_for_execution"])
        self.assertEqual(
            audit["semantic_preflight"]["status"], "not_declared"
        )
        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_policy_required"
        )
        rejected = self.command(
            "activate", "--task-dir", str(self.plan_dir), ok=False
        )
        self.assertEqual(
            rejected["error"]["code"], "semantic_preflight_policy_required"
        )

    def test_not_applicable_policy_is_explicit_and_ready(self) -> None:
        plan = make_plan()
        self.write_plan(plan)

        audit = self.command("audit-plan", "--task-dir", str(self.plan_dir))

        self.assertEqual(audit["execution_readiness"], "ready")
        self.assertTrue(audit["ready_for_execution"])
        self.assertEqual(
            audit["semantic_preflight"]["status"], "not_applicable"
        )
        self.command("activate", "--task-dir", str(self.plan_dir))

    def test_activated_legacy_plan_can_continue_without_policy(self) -> None:
        plan = make_plan()
        plan.pop("semantic_preflight")
        self.write_plan(plan)
        state = {
            "schema": "task.state.v1",
            "plan_id": plan["plan_id"],
            "plan_revision": TASKCTL._plan_hash(plan),
            "revision": 1,
            "active_package": None,
            "task_states": {
                task["id"]: TASKCTL._new_task_state() for task in plan["tasks"]
            },
        }
        TASKCTL._recompute_ready(plan, state)
        self.write_json(self.plan_dir / "state.json", state)

        audit = self.command("audit-plan", "--task-dir", str(self.plan_dir))
        resumed = self.command("resume", "--task-dir", str(self.plan_dir))

        self.assertEqual(
            audit["execution_readiness"], "legacy_structural_only"
        )
        self.assertFalse(audit["ready_for_execution"])
        self.assertTrue(audit["legacy_continuation_allowed"])
        self.assertEqual(resumed["ready_ids"], ["T1"])
        self.assertTrue(resumed["completion_allowed"])

    def test_activated_v1_semantic_plan_continues_only_as_legacy(self) -> None:
        plan = make_plan()
        declare_legacy_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(
            plan, schema="task.semantic-preflight.v1"
        )
        state = {
            "schema": "task.state.v1",
            "plan_id": plan["plan_id"],
            "plan_revision": TASKCTL._plan_hash(plan),
            "revision": 1,
            "active_package": None,
            "task_states": {
                task["id"]: TASKCTL._new_task_state() for task in plan["tasks"]
            },
        }
        TASKCTL._recompute_ready(plan, state)
        self.write_json(self.plan_dir / "state.json", state)

        audit = self.command("audit-plan", "--task-dir", str(self.plan_dir))
        resumed = self.command("resume", "--task-dir", str(self.plan_dir))

        self.assertEqual(audit["execution_readiness"], "legacy_semantic_v1")
        self.assertFalse(audit["ready_for_execution"])
        self.assertTrue(audit["legacy_continuation_allowed"])
        self.assertEqual(resumed["ready_ids"], ["T1"])

        self.write_semantic_receipt(
            plan,
            schema="task.semantic-preflight.v1",
            count_overrides={
                "resolved_count": 3,
                "unresolved_count": 1,
                "dimension_unresolved_counts": {"owner": 1},
            },
        )
        blocked_resume = self.command(
            "resume", "--task-dir", str(self.plan_dir)
        )
        rejected_begin = self.command(
            "begin",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--expected-revision",
            "1",
            ok=False,
        )
        self.assertEqual(blocked_resume["execution_readiness"], "blocked")
        self.assertEqual(blocked_resume["semantic_blocked_ids"], ["T1"])
        self.assertEqual(
            rejected_begin["error"]["code"], "semantic_preflight_unresolved"
        )

    def test_new_v1_semantic_plan_requires_explicit_v2_policy(self) -> None:
        plan = make_plan()
        declare_legacy_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(
            plan, schema="task.semantic-preflight.v1"
        )

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )
        rejected = self.command(
            "activate", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["execution_readiness"], "blocked")
        self.assertEqual(
            rejected["error"]["code"], "semantic_preflight_policy_required"
        )

    def test_declared_semantic_preflight_blocks_when_receipt_is_missing(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["structural_status"], "pass")
        self.assertEqual(audit["execution_readiness"], "blocked")
        self.assertIsNone(audit["semantic_preflight"]["unresolved_count"])
        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_missing"
        )
        rejected = self.command(
            "activate", "--task-dir", str(self.plan_dir), ok=False
        )
        self.assertEqual(
            rejected["error"]["code"], "semantic_preflight_missing"
        )

    def test_semantic_preflight_negative_dimensions_block_readiness(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        cases = {
            "placeholder": {
                "resolved_count": 3,
                "unresolved_count": 1,
                "placeholder_count": 1,
            },
            "wrong_owner": {
                "resolved_count": 3,
                "unresolved_count": 1,
                "dimension_unresolved_counts": {"owner": 1},
            },
            "unknown_successor": {
                "resolved_count": 3,
                "unresolved_count": 1,
                "dimension_unresolved_counts": {"successor_contract": 1},
            },
            "missing_row": {
                "resolved_count": 3,
                "unresolved_count": 1,
                "dimension_unresolved_counts": {"input_output": 1},
            },
            "duplicate_row": {"duplicate_count": 1},
            "irrelevant_evidence": {
                "resolved_count": 3,
                "unresolved_count": 1,
                "dimension_unresolved_counts": {"evidence_binding": 1},
            },
        }
        for label, overrides in cases.items():
            with self.subTest(label=label):
                self.write_semantic_receipt(plan, count_overrides=overrides)
                audit = self.command(
                    "audit-plan", "--task-dir", str(self.plan_dir), ok=False
                )
                self.assertEqual(audit["execution_readiness"], "blocked")
                self.assertEqual(
                    audit["semantic_preflight"]["status"], "blocked"
                )
                self.assertEqual(
                    audit["semantic_preflight"]["error_code"],
                    "semantic_preflight_unresolved",
                )

    def test_semantic_preflight_rejects_a_false_pass(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(
            plan,
            count_overrides={
                "resolved_count": 3,
                "unresolved_count": 1,
                "placeholder_count": 1,
            },
            status="pass",
        )

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["semantic_preflight"]["status"], "invalid")
        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_invalid"
        )

    def test_semantic_preflight_rejects_source_fingerprint_mismatch(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(
            plan,
            source_fingerprints={
                "semantic-identities": "sha256:" + "0" * 64,
                "semantic-verifier": next(
                    source["fingerprint"]
                    for source in plan["scope_sources"]
                    if source["id"] == "semantic-verifier"
                ),
            },
        )

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["semantic_preflight"]["status"], "invalid")
        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_invalid"
        )

    def test_required_policy_rejects_missing_core_dimension(self) -> None:
        plan = make_plan()
        dimensions = sorted(
            TASKCTL.SEMANTIC_PREFLIGHT_CORE_DIMENSIONS - {"lifecycle"}
        )
        declare_semantic_preflight(plan, dimensions=dimensions)
        self.write_plan(plan)

        rejected = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(rejected["error"]["code"], "invalid")
        self.assertIn("missing core dimensions", rejected["error"]["message"])

    def test_required_policy_rejects_inventory_verifier_file_alias(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        identity_source = next(
            source
            for source in plan["scope_sources"]
            if source["id"] == "semantic-identities"
        )
        verifier_source = next(
            source
            for source in plan["scope_sources"]
            if source["id"] == "semantic-verifier"
        )
        verifier_source["root"] = identity_source["root"]
        verifier_source["ref"] = identity_source["ref"]
        self.write_plan(plan)

        rejected = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(rejected["error"]["code"], "invalid")
        self.assertIn("different files", rejected["error"]["message"])

    def test_semantic_preflight_rejects_incomplete_identity_set(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(plan, identities=SEMANTIC_IDENTITIES[:-1])

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["semantic_preflight"]["status"], "invalid")
        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_invalid"
        )

    def test_semantic_preflight_rejects_duplicate_identity(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(
            plan,
            identities=[*SEMANTIC_IDENTITIES, SEMANTIC_IDENTITIES[-1]],
        )

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["semantic_preflight"]["status"], "invalid")
        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_invalid"
        )

    def test_semantic_preflight_rejects_wrong_total_count(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(
            plan,
            count_overrides={"total_count": 1, "resolved_count": 1},
        )

        audit = self.command(
            "audit-plan", "--task-dir", str(self.plan_dir), ok=False
        )

        self.assertEqual(audit["semantic_preflight"]["status"], "invalid")
        self.assertEqual(
            audit["error"]["code"], "semantic_preflight_invalid"
        )

    def test_semantic_preflight_pass_is_reported_and_rechecked_before_begin(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(plan)

        audit = self.command("audit-plan", "--task-dir", str(self.plan_dir))
        self.assertEqual(audit["execution_readiness"], "ready")
        self.assertTrue(audit["ready_for_execution"])
        self.command("activate", "--task-dir", str(self.plan_dir))

        resumed = self.command("resume", "--task-dir", str(self.plan_dir))
        self.assertEqual(
            resumed["semantic_preflight"]["unresolved_count"], 0
        )
        rendered = self.command("render", "--task-dir", str(self.plan_dir))
        self.assertEqual(
            rendered["semantic_preflight"]["unresolved_count"], 0
        )
        markdown = (self.plan_dir / "TASK_TABLE.md").read_text(encoding="utf-8")
        self.assertIn(
            "semantic_preflight: mode=required, status=pass, total=4, unresolved=0",
            markdown,
        )

        self.write_semantic_receipt(
            plan,
            count_overrides={
                "resolved_count": 3,
                "unresolved_count": 1,
                "dimension_unresolved_counts": {"owner": 1},
            },
        )
        blocked_resume = self.command(
            "resume", "--task-dir", str(self.plan_dir)
        )
        self.assertFalse(blocked_resume["completion_allowed"])
        self.assertEqual(blocked_resume["ready_count"], 0)
        self.assertEqual(blocked_resume["semantic_blocked_ids"], ["T1"])
        rejected = self.command(
            "begin",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--expected-revision",
            str(self.state()["revision"]),
            ok=False,
        )
        self.assertEqual(
            rejected["error"]["code"], "semantic_preflight_unresolved"
        )

    def test_semantic_preflight_debt_does_not_orphan_an_active_package(self) -> None:
        plan = make_plan()
        declare_semantic_preflight(plan)
        self.write_plan(plan)
        self.write_semantic_receipt(plan)
        self.activate()
        self.begin("T1")
        self.write_semantic_receipt(
            plan,
            count_overrides={
                "resolved_count": 3,
                "unresolved_count": 1,
                "dimension_unresolved_counts": {"owner": 1},
            },
        )

        resumed = self.command("resume", "--task-dir", str(self.plan_dir))

        self.assertEqual(resumed["active_package"]["task_ids"], ["T1"])
        self.assertTrue(resumed["completion_allowed"])
        self.assertTrue(resumed["new_work_blocked_by_semantic_preflight"])

    def test_direct_flow_requires_exact_scope_task_and_qualified_tests(self) -> None:
        plan = make_plan()
        scope_id = "public:fixture:create-readback"
        self.set_requirement_acceptance(
            plan, "R1", [("AC-R1-PUBLIC-CREATE-READBACK", scope_id)]
        )
        plan["requirements"][0].update(
            {
                "verification_mode": "direct_flow",
            }
        )
        plan["tasks"][0].update(
            {
                "completion_level": "production_ready",
                "claim_scope": [scope_id],
                "scope_enforced": True,
            }
        )
        plan["tasks"][0]["claim_overrides"]["readback_subjects"] = [scope_id]
        plan["test_qualifications"]["test.T1"].update(
            {
                "evidence_shape": "vertical",
                "observed_scopes": [scope_id],
            }
        )
        plan["acceptance_flows"] = [
            {
                "id": "FLOW-1",
                "title": "Public fixture vertical",
                "scope": "public create through persisted readback",
                "requirement_ids": ["R1"],
                "verification_task_id": "T1",
                "required_claims": ["behavior"],
                "direct_test_ids": ["test.T1"],
                "evidence_mode": "single_receipt",
                "scope_coverage": {scope_id: ["test.T1"]},
            }
        ]
        self.make_source_exact(plan)
        self.write_plan(plan)
        self.command("validate", "--plan-dir", str(self.plan_dir))
        self.activate()
        self.command("render", "--task-dir", str(self.plan_dir))
        markdown = (self.plan_dir / "TASK_TABLE.md").read_text(encoding="utf-8")
        self.assertIn("FLOW-1", markdown)
        self.assertNotIn("精确范围：", markdown)

        self.command("render", "--task-dir", str(self.plan_dir), "--details")
        markdown = (self.plan_dir / "TASK_TABLE.md").read_text(encoding="utf-8")
        self.assertIn("## 验收流程", markdown)
        self.assertIn("FLOW-1", markdown)
        self.assertIn("精确范围：public create through persisted readback", markdown)
        self.assertIn("完成级别：production_ready", markdown)
        self.assertIn(f"Claim scope：{scope_id}", markdown)
        audit = self.command("audit", "--plan-dir", str(self.plan_dir), "--all", ok=False)
        self.assertEqual(audit["audited_flows"], 1)
        self.assertEqual(audit["failed_flow_ids"], ["FLOW-1"])

        plan["tasks"][0]["claim_scope"] = []
        self.write_plan(plan)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("claim_scope", payload["error"]["message"])

    def strict_single_receipt_plan(self) -> dict[str, object]:
        plan = make_plan()
        scope_id = "public:fixture:create-readback"
        self.set_requirement_acceptance(
            plan, "R1", [("AC-R1-PUBLIC-CREATE-READBACK", scope_id)]
        )
        plan["requirements"][0].update(
            {
                "verification_mode": "direct_flow",
            }
        )
        plan["tasks"][0].update(
            {
                "completion_level": "production_ready",
                "claim_scope": [scope_id],
                "scope_enforced": True,
            }
        )
        plan["tasks"][0]["claim_overrides"]["readback_subjects"] = [scope_id]
        plan["test_qualifications"]["test.T1"].update(
            {
                "evidence_shape": "vertical",
                "observed_scopes": [scope_id],
            }
        )
        plan["acceptance_flows"] = [
            {
                "id": "FLOW-STRICT",
                "title": "One real public vertical",
                "scope": "public input through independent readback",
                "requirement_ids": ["R1"],
                "verification_task_id": "T1",
                "required_claims": ["behavior"],
                "direct_test_ids": ["test.T1"],
                "evidence_mode": "single_receipt",
                "scope_coverage": {scope_id: ["test.T1"]},
            }
        ]
        return self.make_source_exact(plan)

    def test_exact_source_inventory_and_file_fingerprint_are_enforced(self) -> None:
        plan = make_plan()
        (self.project / "docs" / "design.md").write_text("R1\n", encoding="utf-8")
        fingerprint = TASKCTL._sha256_file(self.project / "docs" / "design.md")
        plan["scope_sources"][0].update(
            {
                "inventory_mode": "exact",
                "requirement_ids": ["R1"],
                "fingerprint_mode": "file_sha256",
                "root": "project",
                "source_audit_ref": "user:fixture-design-audit",
                "inventory_prefix": "R",
                "fingerprint": fingerprint,
            }
        )
        plan["requirements"][0].update(
            {
                "source_fingerprint": fingerprint,
                "verification_mode": "task_evidence",
            }
        )
        self.write_plan(plan)
        self.command("validate", "--task-dir", str(self.plan_dir))
        self.activate()

        design_path = self.project / "docs" / "design.md"
        design_path.write_text(
            design_path.read_text(encoding="utf-8") + "changed design\n",
            encoding="utf-8",
        )
        drift = self.command("resume", "--task-dir", str(self.plan_dir), ok=False)
        self.assertEqual(drift["error"]["code"], "source_drift")

        repaired = self.read_json(self.plan_dir / "plan.json")
        new_fingerprint = TASKCTL._sha256_file(self.project / "docs" / "design.md")
        repaired["scope_sources"][0]["fingerprint"] = new_fingerprint
        repaired["requirements"][0]["source_fingerprint"] = new_fingerprint
        for collection_name in (
            "acceptance_clauses",
            "design_clauses",
            "solution_steps",
            "gap_items",
        ):
            for item in repaired[collection_name]:
                item["source_fingerprint"] = new_fingerprint
        self.write_json(self.plan_dir / "candidate-without-design-revision.json", repaired)
        rejected_revision = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            "candidate-without-design-revision.json",
            ok=False,
        )
        self.assertEqual(
            rejected_revision["error"]["code"], "design_revision_required"
        )
        repaired["design_revision"] = "design-v2"
        self.write_json(self.plan_dir / "candidate.json", repaired)
        preview = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            "candidate.json",
        )
        self.assertEqual(preview["impact"]["changed_scope_sources"], ["design"])
        self.assertEqual(preview["impact"]["changed_requirements"], [])
        self.assertEqual(preview["impact"]["affected_tasks"], [])
        self.audit_candidate(self.plan_dir / "candidate.json")
        self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            "candidate.json",
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
        )
        self.command("validate", "--task-dir", str(self.plan_dir))

    def test_exact_source_inventory_rejects_an_omitted_requirement(self) -> None:
        plan = make_plan(two_tasks=True)
        (self.project / "docs" / "design.md").write_text("R1\nR2\n", encoding="utf-8")
        fingerprint = TASKCTL._sha256_file(self.project / "docs" / "design.md")
        plan["scope_sources"][0].update(
            {
                "inventory_mode": "exact",
                "requirement_ids": ["R1"],
                "fingerprint_mode": "file_sha256",
                "root": "project",
                "source_audit_ref": "user:fixture-design-audit",
                "inventory_prefix": "R",
                "fingerprint": fingerprint,
            }
        )
        for requirement in plan["requirements"]:
            requirement.update(
                {
                    "source_fingerprint": fingerprint,
                    "verification_mode": "task_evidence",
                }
            )
        self.write_plan(plan, sync_sources=False)
        rejected = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertIn("requirement inventory mismatch", rejected["error"]["message"])

    def test_exact_source_inventory_is_extracted_from_the_design_file(self) -> None:
        plan = make_plan()
        (self.project / "docs" / "design.md").write_text("R1\nR-OMITTED\n", encoding="utf-8")
        fingerprint = TASKCTL._sha256_file(self.project / "docs" / "design.md")
        plan["scope_sources"][0].update(
            {
                "inventory_mode": "exact",
                "requirement_ids": ["R1"],
                "inventory_prefix": "R",
                "fingerprint_mode": "file_sha256",
                "root": "project",
                "source_audit_ref": "user:fixture-design-audit",
                "fingerprint": fingerprint,
            }
        )
        plan["requirements"][0].update(
            {
                "source_fingerprint": fingerprint,
                "verification_mode": "task_evidence",
            }
        )
        for collection_name in (
            "acceptance_clauses",
            "design_clauses",
            "solution_steps",
            "gap_items",
        ):
            for item in plan[collection_name]:
                item["source_fingerprint"] = fingerprint
        self.write_plan(plan, sync_sources=False)
        rejected = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertEqual(rejected["error"]["code"], "source_inventory_drift")
        self.assertIn("R-OMITTED", rejected["error"]["message"])

    def test_scope_enforced_task_cannot_claim_beyond_its_readback(self) -> None:
        plan = make_plan()
        plan["tasks"][0].update(
            {
                "completion_level": "integration_ready",
                "claim_scope": ["asset:T1", "asset:not-read-back"],
                "scope_enforced": True,
            }
        )
        self.write_plan(plan)
        rejected = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertIn("without required readback", rejected["error"]["message"])

    def test_scope_enforced_domain_complete_requires_a_strict_flow(self) -> None:
        plan = make_plan()
        plan["tasks"][0].update(
            {
                "completion_level": "domain_complete",
                "claim_scope": ["asset:T1"],
                "scope_enforced": True,
            }
        )
        self.write_plan(plan)
        rejected = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertIn("must verify a strict acceptance flow", rejected["error"]["message"])

    def test_strict_flow_rejects_horizontal_test_qualification(self) -> None:
        plan = self.strict_single_receipt_plan()
        plan["test_qualifications"]["test.T1"].pop("evidence_shape")
        plan["test_qualifications"]["test.T1"].pop("observed_scopes")
        self.write_plan(plan)
        rejected = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertIn("vertical test evidence", rejected["error"]["message"])

    def test_strict_flow_scope_claims_must_match_the_mapped_test(self) -> None:
        plan = self.strict_single_receipt_plan()
        scope_id = "public:fixture:create-readback"
        plan["acceptance_flows"][0]["scope_claims"] = {scope_id: ["behavior"]}
        self.write_plan(plan)
        self.command("validate", "--task-dir", str(self.plan_dir))

        plan["acceptance_flows"][0]["scope_claims"] = {scope_id: ["integration"]}
        self.write_plan(plan)
        rejected = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertIn("scope_claims", rejected["error"]["message"])

    def test_strict_flow_does_not_union_disconnected_horizontal_receipts(self) -> None:
        plan = self.strict_single_receipt_plan()
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        test_only = self.evidence(
            "test-only",
            "T1",
            ["behavior"],
            test_ids=["test.T1"],
            subjects=[],
        )
        readback_only = self.evidence(
            "readback-only",
            "T1",
            ["behavior"],
            test_ids=[],
            subjects=["public:fixture:create-readback"],
        )
        closed = self.close(test_only, readback_only)
        self.assertEqual(closed["completed"], ["T1"])
        audit = self.command(
            "audit", "--task-dir", str(self.plan_dir), "--all", "--details", ok=False
        )
        self.assertEqual(audit["failed_task_ids"], [])
        self.assertEqual(audit["failed_flow_ids"], ["FLOW-STRICT"])
        self.assertEqual(
            audit["flow_cards"][0]["missing"][0]["type"],
            "missing_vertical_receipt",
        )
        applied = self.command(
            "audit",
            "--task-dir",
            str(self.plan_dir),
            "--all",
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
            ok=False,
        )
        self.assertEqual(applied["changed_to_needs_review"], ["T1"])
        self.assertEqual(self.state()["task_states"]["T1"]["status"], "needs_review")

    def test_strict_flow_accepts_one_complete_vertical_receipt(self) -> None:
        plan = self.strict_single_receipt_plan()
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        receipt = self.evidence(
            "vertical-receipt",
            "T1",
            ["behavior"],
            test_ids=["test.T1"],
            subjects=["public:fixture:create-readback"],
        )
        self.close(receipt)
        audit = self.command("audit", "--task-dir", str(self.plan_dir), "--all")
        self.assertEqual(audit["failed_flow_ids"], [])
        self.assertEqual(audit["task_status_counts"]["done"], 1)
        self.assertEqual(audit["semantic_preflight"]["status"], "not_applicable")
        self.assertEqual(audit["product_evidence"]["closed_task_count"], 1)
        self.assertEqual(audit["product_evidence"]["unresolved_task_count"], 0)
        self.assertTrue(
            audit["product_evidence"]["completion_receipt_issued"]
        )
        completion = audit["completion_receipt"]
        self.assertTrue(completion["id"].startswith("sha256:"))
        completion_path = self.plan_dir / completion["path"]
        self.assertTrue(completion_path.is_file())
        stored = self.read_json(completion_path)
        self.assertEqual(stored["schema"], "task.completion.v2")
        self.assertEqual(stored["receipt_id"], completion["id"])
        self.assertEqual(stored["plan_revision"], self.state()["plan_revision"])
        self.assertEqual(
            stored["semantic_preflight"]["status"], "not_applicable"
        )

    def test_coverage_matrix_requires_a_vertical_receipt_for_each_scope(self) -> None:
        plan = make_plan()
        scope_a = "domain:fixture:a"
        scope_b = "domain:fixture:b"
        self.set_requirement_acceptance(
            plan,
            "R1",
            [("AC-R1-DOMAIN-A", scope_a), ("AC-R1-DOMAIN-B", scope_b)],
        )
        plan["requirements"][0].update(
            {
                "verification_mode": "direct_flow",
            }
        )
        plan["tasks"][0].update(
            {
                "completion_level": "domain_complete",
                "claim_scope": [scope_a, scope_b],
                "scope_enforced": True,
            }
        )
        plan["tasks"][0]["claim_overrides"].update(
            {
                "automation_test_ids": ["test.T1", "test.T1.second"],
                "readback_subjects": [scope_a, scope_b],
            }
        )
        plan["test_qualifications"]["test.T1"].update(
            {"evidence_shape": "vertical", "observed_scopes": [scope_a]}
        )
        plan["test_qualifications"]["test.T1.second"] = {
            **plan["test_qualifications"]["test.T1"],
            "subject": scope_b,
            "observed_scopes": [scope_b],
            "source_fingerprint": "test-t1-second-v1",
        }
        plan["acceptance_flows"] = [
            {
                "id": "FLOW-MATRIX",
                "title": "Every domain scope",
                "scope": "two independently proven domain routes",
                "requirement_ids": ["R1"],
                "verification_task_id": "T1",
                "required_claims": ["behavior"],
                "direct_test_ids": ["test.T1", "test.T1.second"],
                "evidence_mode": "coverage_matrix",
                "scope_coverage": {
                    scope_a: ["test.T1"],
                    scope_b: ["test.T1.second"],
                },
            }
        ]
        self.make_source_exact(plan)
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        scope_a_receipt = self.evidence(
            "scope-a-receipt",
            "T1",
            ["behavior"],
            test_ids=["test.T1"],
            subjects=[scope_a],
        )
        scope_b_test_only = self.evidence(
            "scope-b-test-only",
            "T1",
            ["behavior"],
            test_ids=["test.T1.second"],
            subjects=[],
        )
        scope_b_readback_only = self.evidence(
            "scope-b-readback-only",
            "T1",
            ["behavior"],
            test_ids=[],
            subjects=[scope_b],
        )
        closed = self.close(
            scope_a_receipt,
            scope_b_test_only,
            scope_b_readback_only,
        )
        self.assertEqual(closed["completed"], ["T1"])
        audit = self.command(
            "audit", "--task-dir", str(self.plan_dir), "--all", "--details", ok=False
        )
        self.assertEqual(audit["failed_task_ids"], [])
        self.assertEqual(audit["failed_flow_ids"], ["FLOW-MATRIX"])
        self.assertEqual(audit["flow_cards"][0]["missing"][0]["subject"], scope_b)

    def test_plan_rejects_impossible_producer_class_and_tests_first_contracts(self) -> None:
        plan = make_plan()
        plan["producers"]["machine"]["source_class"] = "human_decision"
        self.write_plan(plan)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("source_class", payload["error"]["message"])

        plan = make_plan(tests_first="required")
        plan["tasks"][0]["claim_overrides"]["automation_test_ids"] = []
        self.write_plan(plan)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("automation_test_ids", payload["error"]["message"])

    def test_resume_is_compact_and_render_has_five_columns(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        payload = self.command("resume", "--plan-dir", str(self.plan_dir))
        self.assertEqual(payload["ready_ids"], ["T1"])
        self.assertNotIn("actionable", payload)
        self.assertNotIn("package_suggestions", payload)
        self.assertEqual(payload["recommended_package"]["tasks"][0]["id"], "T1")
        self.assertIn("outcome", payload["recommended_package"]["tasks"][0])
        self.assertTrue((self.plan_dir / "TASK_TABLE.md").exists())
        rendered = self.command("render", "--task-dir", str(self.plan_dir))
        self.assertEqual(
            rendered["status_counts"],
            {
                "active": 0,
                "blocked": 0,
                "done": 0,
                "needs_review": 0,
                "ready": 1,
                "todo": 1,
            },
        )
        markdown = (self.plan_dir / "TASK_TABLE.md").read_text(encoding="utf-8")
        self.assertIn("| ID | 交付结果 | 必要依赖 | 完成证据 | 状态 |", markdown)
        self.assertIn(
            "- totals: active=0, blocked=0, done=0, needs_review=0, ready=1, todo=1",
            markdown,
        )
        self.assertNotIn("done 100%", markdown)

    def test_state_changes_automatically_refresh_task_table(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        task_table = self.plan_dir / "TASK_TABLE.md"
        self.assertIn("| `T1` |", task_table.read_text(encoding="utf-8"))
        self.assertIn("| `ready` |", task_table.read_text(encoding="utf-8"))

        self.begin("T1")
        active_markdown = task_table.read_text(encoding="utf-8")
        self.assertIn("active_package: T1 / tests /", active_markdown)
        self.assertIn("| `active` |", active_markdown)

        closed = self.close(self.evidence("auto-render-green", "T1", ["behavior"]))
        self.assertEqual(closed["completed"], ["T1"])
        done_markdown = task_table.read_text(encoding="utf-8")
        self.assertIn("active_package: none", done_markdown)
        self.assertIn("| `done` |", done_markdown)

    def test_render_status_counts_preserve_an_active_state(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        self.begin("T1")
        state_path = self.plan_dir / "state.json"
        state_before = state_path.read_bytes()

        rendered = self.command("render", "--task-dir", str(self.plan_dir))

        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(
            rendered["status_counts"],
            {
                "active": 1,
                "blocked": 0,
                "done": 0,
                "needs_review": 0,
                "ready": 0,
                "todo": 0,
            },
        )
        self.assertEqual(self.state()["active_package"]["task_ids"], ["T1"])

    def test_render_counts_all_states_while_resume_counts_actionable_tasks(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        state = self.state()
        state["task_states"]["T2"]["status"] = "needs_review"
        self.write_json(self.plan_dir / "state.json", state)

        rendered = self.command("render", "--task-dir", str(self.plan_dir))
        resumed = self.command("resume", "--task-dir", str(self.plan_dir))

        self.assertEqual(rendered["status_counts"]["needs_review"], 1)
        self.assertEqual(resumed["needs_review_count"], 0)
        self.assertEqual(resumed["needs_review_ids"], [])
        self.assertEqual(resumed["dependency_blocked_ids"], ["T2"])

    def test_resume_projection_has_a_regression_size_budget(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()

        payload = self.command("resume", "--task-dir", str(self.plan_dir))
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

        self.assertLessEqual(len(encoded), 9000)
        self.assertIn("recommended_package", payload)

    def test_skill_hot_path_stays_within_its_fixed_context_budget(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertLessEqual(len(skill_text), 2400)
        self.assertIn("resume → begin → close", skill_text)
        self.assertIn("semantic_preflight", skill_text)

    def test_active_package_freezes_controller_and_can_release_after_drift(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        self.begin("T1")
        state = self.state()
        self.assertEqual(
            state["active_package"]["controller_identity"],
            TASKCTL._controller_identity(),
        )

        state["active_package"]["controller_identity"] = "sha256:stale"
        self.write_json(self.plan_dir / "state.json", state)
        resumed = self.command("resume", "--task-dir", str(self.plan_dir))
        self.assertEqual(
            resumed["active_package"]["controller_status"], "drifted"
        )
        rejected = self.command(
            "impact", "--task-dir", str(self.plan_dir), ok=False
        )
        self.assertEqual(rejected["error"]["code"], "controller_drift")

        self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(state["revision"]),
            "--next-action",
            "review controller change",
            "--release",
        )
        self.assertIsNone(self.state()["active_package"])

    def test_render_is_compact_by_default_and_details_are_explicit(self) -> None:
        plan = make_plan()
        long_outcome = "A precise observable result " + "with full detail " * 20
        plan["tasks"][0]["outcome"] = long_outcome
        self.write_plan(plan)
        self.activate()
        self.command("render", "--task-dir", str(self.plan_dir))
        markdown = (self.plan_dir / "TASK_TABLE.md").read_text(encoding="utf-8")
        row = next(line for line in markdown.splitlines() if line.startswith("| `T1` |"))
        self.assertNotIn(long_outcome, row)
        self.assertNotIn("## 任务详情", markdown)

        self.command("render", "--task-dir", str(self.plan_dir), "--details")
        markdown = (self.plan_dir / "TASK_TABLE.md").read_text(encoding="utf-8")
        self.assertIn(" ".join(long_outcome.split()), markdown)
        self.assertIn("## 任务详情", markdown)
        self.assertNotIn("\ufffd", markdown)

    def test_render_remains_available_when_execution_source_gate_is_invalid(self) -> None:
        plan = make_plan(two_tasks=True)
        self.write_plan(plan)
        self.activate()

        plan = self.read_json(self.plan_dir / "plan.json")
        plan["scope_sources"].append(
            {
                "id": "legacy",
                "ref": "legacy conversation source",
                "fingerprint": "legacy-v1",
                "inventory_mode": "advisory",
                "requirement_ids": ["R1"],
                "fingerprint_mode": "label",
            }
        )
        plan["scope_sources"][0]["requirement_ids"] = ["R2"]
        plan["requirements"][0]["source_ref"] = "legacy:R1"
        plan["requirements"][0]["source_fingerprint"] = "legacy-v1"
        self.write_plan(plan, sync_sources=False)
        state = self.state()
        state["plan_revision"] = TASKCTL._plan_hash(plan)
        self.write_json(self.plan_dir / "state.json", state)

        invalid = self.command("validate", "--task-dir", str(self.plan_dir), ok=False)
        self.assertEqual(invalid["error"]["code"], "strict_source_not_durable")

        rendered = self.command("render", "--task-dir", str(self.plan_dir))
        self.assertEqual(rendered["view_scope"], "read_only_projection")
        self.assertEqual(rendered["execution_validity"], "not_checked")
        self.assertTrue((self.plan_dir / "TASK_TABLE.md").is_file())

    def test_final_audit_fails_when_any_planned_task_is_not_done(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        audit = self.command("audit", "--plan-dir", str(self.plan_dir), "--all", ok=False)
        self.assertEqual(audit["failed_task_ids"], ["T1", "T2"])
        self.assertEqual(audit["product_evidence"]["audited_task_count"], 2)
        self.assertEqual(audit["product_evidence"]["unresolved_task_count"], 2)
        self.assertFalse(
            audit["product_evidence"]["completion_receipt_issued"]
        )
        self.assertIsNone(audit["completion_receipt"])

    def test_packaged_plan_template_is_schema_valid(self) -> None:
        template = json.loads(
            (SKILL_ROOT / "assets" / "templates" / "plan.json").read_text(encoding="utf-8")
        )
        with self.assertRaises(TASKCTL.TaskCtlError):
            TASKCTL._validate_plan(template)
        template["semantic_preflight"]["reason"] = (
            "template fixture has no bulk identity migration"
        )
        TASKCTL._validate_plan(template)

    def test_packaged_semantic_preflight_template_matches_the_cli_contract(self) -> None:
        template = json.loads(
            (
                SKILL_ROOT
                / "assets"
                / "templates"
                / "semantic-preflight.json"
            ).read_text(encoding="utf-8")
        )
        dimensions = sorted(
            template["counts"]["dimension_unresolved_counts"]
        )
        plan = make_plan()
        declare_semantic_preflight(plan, dimensions=dimensions)
        self.write_plan(plan)
        sources = {source["id"]: source for source in plan["scope_sources"]}
        template.update(
            {
                "plan_id": plan["plan_id"],
                "design_revision": plan["design_revision"],
                "producer_source_id": "semantic-verifier",
                "source_fingerprints": {
                    source_id: sources[source_id]["fingerprint"]
                    for source_id in plan["semantic_preflight"]["scope_source_ids"]
                },
                "identity_set_fingerprint": TASKCTL._json_identity(
                    SEMANTIC_IDENTITIES
                ),
                "identities": SEMANTIC_IDENTITIES,
                "status": "pass",
            }
        )
        template["counts"].update(
            {
                "total_count": len(SEMANTIC_IDENTITIES),
                "resolved_count": len(SEMANTIC_IDENTITIES),
                "unresolved_count": 0,
                "placeholder_count": 0,
                "duplicate_count": 0,
                "dimension_unresolved_counts": {
                    dimension: 0 for dimension in dimensions
                },
            }
        )
        self.write_json(
            self.plan_dir / plan["semantic_preflight"]["receipt_ref"],
            template,
        )

        audit = self.command("audit-plan", "--task-dir", str(self.plan_dir))

        self.assertEqual(audit["execution_readiness"], "ready")

    def test_scope_and_build_profile_are_part_of_task_contract_identity(self) -> None:
        base = make_plan()
        baseline = TASKCTL._task_contract_identity(base, base["tasks"][0])
        for field, value in (
            ("mutation_scope", ["src/other.txt"]),
            ("test_scope", ["tests/other.txt"]),
            ("build_profile", "release"),
        ):
            with self.subTest(field=field):
                candidate = json.loads(json.dumps(base))
                candidate["tasks"][0][field] = value
                self.assertNotEqual(
                    baseline,
                    TASKCTL._task_contract_identity(candidate, candidate["tasks"][0]),
                )

    def test_custom_freshness_scope_is_recomputed_during_audit(self) -> None:
        plan = make_plan()
        plan["tasks"][0]["freshness_scopes"] = {"runtime": ["runtime/session.json"]}
        plan["evidence_profiles"]["default"]["claim_rules"]["behavior"][
            "freshness_keys"
        ].append("runtime")
        runtime_identity = self.project / "runtime" / "session.json"
        runtime_identity.parent.mkdir(parents=True)
        runtime_identity.write_text("session-1", encoding="utf-8")
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        self.close(self.evidence("runtime-green", "T1", ["behavior"]))
        runtime_identity.write_text("session-2", encoding="utf-8")
        audit = self.command("audit", "--plan-dir", str(self.plan_dir), "--all", ok=False)
        self.assertEqual(audit["failed_task_ids"], ["T1"])

    def test_freshness_key_without_recomputable_scope_is_rejected(self) -> None:
        plan = make_plan()
        plan["evidence_profiles"]["default"]["claim_rules"]["behavior"][
            "freshness_keys"
        ].append("runtime")
        self.write_plan(plan)
        payload = self.command("validate", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("freshness key runtime", payload["error"]["message"])

    def test_evidence_context_rejects_missing_custom_and_test_identity_inputs(self) -> None:
        plan = make_plan()
        plan["tasks"][0]["freshness_scopes"] = {"runtime": ["runtime/session.json"]}
        plan["evidence_profiles"]["default"]["claim_rules"]["behavior"][
            "freshness_keys"
        ].append("runtime")
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        payload = self.command(
            "evidence-context",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
            ok=False,
        )
        self.assertIn("runtime", payload["error"]["message"])

        runtime_identity = self.project / "runtime" / "session.json"
        runtime_identity.parent.mkdir(parents=True)
        runtime_identity.write_text("session", encoding="utf-8")
        (self.project / "tests" / "T1.txt").unlink()
        payload = self.command(
            "evidence-context",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
            ok=False,
        )
        self.assertIn("test_scope", payload["error"]["message"])

    def test_one_claim_cannot_complete_other_dimensions(self) -> None:
        claims = ["binding", "public_ingress", "persistence", "terminal", "cleanup"]
        self.write_plan(make_plan(first_claims=claims))
        self.activate()
        self.begin("T1")
        result = self.close(self.evidence("binding-only", "T1", ["binding"]))
        self.assertEqual(result["completed"], [])
        missing_subjects = {item["subject"] for item in result["completion_cards"][0]["missing"]}
        self.assertTrue(set(claims[1:]) <= missing_subjects)

    def test_duplicate_evidence_facts_do_not_satisfy_minimum_count(self) -> None:
        plan = make_plan()
        plan["evidence_profiles"]["default"]["claim_rules"]["behavior"]["min_evidence"] = 2
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        first = self.evidence("same-fact-1", "T1", ["behavior"])
        second = self.evidence(
            "same-fact-2",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:04:00Z",
            completed_at="2026-08-04T00:05:00Z",
        )
        result = self.close(first, second)
        self.assertEqual(result["remaining"], ["T1"])
        self.assertIn("behavior", {item["subject"] for item in result["completion_cards"][0]["missing"]})

    def test_test_id_only_counts_on_its_qualified_claim_dimension(self) -> None:
        plan = make_plan(first_claims=["binding", "persistence"])
        plan["test_qualifications"]["test.T1"]["claim_dimensions"] = ["binding"]
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        binding = self.evidence("binding-without-test", "T1", ["binding"], test_ids=[])
        persistence = self.evidence("persistence-with-test", "T1", ["persistence"])
        result = self.close(binding, persistence)
        self.assertEqual(result["remaining"], ["T1"])
        self.assertIn("missing_test", {item["type"] for item in result["completion_cards"][0]["missing"]})

    def test_untrusted_legacy_test_cannot_complete_task(self) -> None:
        plan = make_plan()
        plan["test_qualifications"]["test.T1"]["trust_state"] = "untrusted_legacy"
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        result = self.close(self.evidence("legacy-green", "T1", ["behavior"]))
        self.assertEqual(result["remaining"], ["T1"])
        self.assertIn("test_invalid", {item["type"] for item in result["completion_cards"][0]["missing"]})

    def test_tests_first_uses_begin_baseline_and_precedes_verification(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "expected-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        (self.project / "src" / "T1.txt").write_text("implemented", encoding="utf-8")
        green = self.evidence("green", "T1", ["behavior"])
        result = self.close(red, green)
        self.assertEqual(result["completed"], ["T1"])

    def test_tests_first_allows_reverification_after_an_early_green_attempt(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        early_green = self.evidence(
            "early-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        red = self.evidence(
            "expected-red-after-early-attempt",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:02:00Z",
            completed_at="2026-08-04T00:03:00Z",
        )
        (self.project / "src" / "T1.txt").write_text("implemented", encoding="utf-8")
        final_green = self.evidence(
            "final-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:04:00Z",
            completed_at="2026-08-04T00:05:00Z",
        )

        result = self.close(early_green, red, final_green)

        self.assertEqual(result["completed"], ["T1"])

    def test_tests_first_rejects_red_from_a_different_test_revision(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "old-test-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        (self.project / "tests" / "T1.txt").write_text("rewritten test", encoding="utf-8")
        (self.project / "src" / "T1.txt").write_text("implemented", encoding="utf-8")
        green = self.evidence("new-test-green", "T1", ["behavior"])
        result = self.close(red, green)
        self.assertEqual(result["remaining"], ["T1"])
        self.assertIn("tests_first", {item["type"] for item in result["completion_cards"][0]["missing"]})

    def test_evidence_context_prevents_expected_red_after_production_changed(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red_context = self.command(
            "evidence-context",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "expected_red",
        )
        self.assertEqual(
            red_context["freshness_identity"]["production_scope"],
            self.state()["task_states"]["T1"]["baseline_identity"]["production_scope"],
        )
        red = self.evidence(
            "red-before-production",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        (self.project / "src" / "T1.txt").write_text("implementation started", encoding="utf-8")
        self.command(
            "evidence-context",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "expected_red",
            ok=False,
        )
        verification_context = self.command(
            "evidence-context",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
        )
        self.assertNotEqual(
            verification_context["freshness_identity"]["production_scope"],
            red_context["freshness_identity"]["production_scope"],
        )

    def test_seal_red_freezes_test_identity_before_implementation(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "sealed-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        before_revision = self.state()["revision"]

        sealed = self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(before_revision),
            "--evidence",
            str(red),
        )

        self.assertEqual(sealed["sealed_task_ids"], ["T1"])
        self.assertEqual(sealed["state_revision"], before_revision + 1)
        self.assertEqual(self.state()["active_package"]["phase"], "implementation")
        (self.project / "tests" / "T1.txt").write_text(
            "test changed after seal", encoding="utf-8"
        )
        rejected = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
            ok=False,
        )
        self.assertEqual(rejected["error"]["code"], "red_identity_changed")

    def test_completed_task_keeps_historical_red_when_shared_test_changes(self) -> None:
        self.write_plan(make_plan(tests_first="required", two_tasks=True))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "historical-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        (self.project / "src" / "T1.txt").write_text(
            "implemented", encoding="utf-8"
        )
        green = self.evidence(
            "initial-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:02:00Z",
            completed_at="2026-08-04T00:03:00Z",
        )
        self.assertEqual(self.close(green)["completed"], ["T1"])
        self.begin("T2")

        (self.project / "tests" / "T1.txt").write_text(
            "shared test refined by a later consumer", encoding="utf-8"
        )
        context = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
        )
        self.assertEqual(context["task_id"], "T1")

    def test_needs_review_revalidation_keeps_the_completed_task_historical_red(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "initial-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        (self.project / "src" / "T1.txt").write_text(
            "implemented", encoding="utf-8"
        )
        first_green = self.evidence(
            "first-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:02:00Z",
            completed_at="2026-08-04T00:03:00Z",
        )
        self.assertEqual(self.close(first_green)["completed"], ["T1"])

        (self.project / "src" / "T1.txt").write_text(
            "implemented and later refined", encoding="utf-8"
        )
        self.command(
            "audit",
            "--task-dir",
            str(self.plan_dir),
            "--all",
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
            ok=False,
        )
        self.begin("T1")
        second_green = self.evidence(
            "second-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:04:00Z",
            completed_at="2026-08-04T00:05:00Z",
        )

        self.assertEqual(self.close(second_green)["completed"], ["T1"])
        audited = self.command(
            "audit",
            "--task-dir",
            str(self.plan_dir),
            "--all",
        )
        self.assertEqual(audited["failed"], 0)

    def test_amended_completed_task_revalidates_without_rewriting_historical_red(self) -> None:
        self.write_plan(make_plan(tests_first="required", two_tasks=True))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "pre-amend-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        (self.project / "src" / "T1.txt").write_text(
            "implemented", encoding="utf-8"
        )
        first_green = self.evidence(
            "pre-amend-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:02:00Z",
            completed_at="2026-08-04T00:03:00Z",
        )
        self.assertEqual(self.close(first_green)["completed"], ["T1"])

        candidate = make_plan(tests_first="required", two_tasks=True)
        candidate["tasks"][0]["outcome"] += " with an amended verified bound"
        candidate["decision_refs"] = ["user:approved-amended-bound"]
        candidate_path = self.plan_dir / "candidate-amended.json"
        self.write_json(candidate_path, candidate)
        self.audit_candidate(candidate_path)
        self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
            "--decision-ref",
            "user:approved-amended-bound",
        )
        self.assertEqual(self.state()["task_states"]["T1"]["status"], "needs_review")
        self.begin("T1")

        context = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
        )
        self.assertEqual(context["task_id"], "T1")
        second_green = self.evidence(
            "post-amend-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:04:00Z",
            completed_at="2026-08-04T00:05:00Z",
        )
        self.assertEqual(self.close(second_green)["completed"], ["T1"])
        self.begin("T2")

        # Once the amended task is done, a later package may consume and
        # revalidate it without recreating expected-red against green code.
        context = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
        )
        self.assertEqual(context["task_id"], "T1")

    def test_amended_evidenced_incomplete_task_uses_historical_red_for_revalidation(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "incomplete-pre-amend-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        (self.project / "src" / "T1.txt").write_text("implemented", encoding="utf-8")
        incomplete_green = self.evidence(
            "incomplete-pre-amend-green",
            "T1",
            [],
            started_at="2026-08-04T00:02:00Z",
            completed_at="2026-08-04T00:03:00Z",
        )
        self.assertEqual(self.close(incomplete_green)["remaining"], ["T1"])
        self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--next-action",
            "amend the verified contract",
            "--release",
        )

        candidate = make_plan(tests_first="required")
        candidate["tasks"][0]["outcome"] += " with an amended verified bound"
        candidate["decision_refs"] = ["user:approved-incomplete-amended-bound"]
        candidate_path = self.plan_dir / "candidate-incomplete-amended.json"
        self.write_json(candidate_path, candidate)
        self.audit_candidate(candidate_path)
        self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
            "--decision-ref",
            "user:approved-incomplete-amended-bound",
        )
        self.assertEqual(self.state()["task_states"]["T1"]["status"], "ready")

        self.begin("T1")
        self.assertEqual(
            self.state()["active_package"]["revalidation_task_ids"], ["T1"]
        )
        final_green = self.evidence(
            "incomplete-post-amend-green",
            "T1",
            ["behavior"],
            started_at="2026-08-04T00:04:00Z",
            completed_at="2026-08-04T00:05:00Z",
        )
        self.assertEqual(self.close(final_green)["completed"], ["T1"])

    def test_invalidate_red_reopens_tests_without_releasing_package(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "sealed-before-test-correction",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        baseline = self.state()["task_states"]["T1"]["baseline_identity"]

        reopened = self.command(
            "invalidate-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--reason",
            "fixture kept a raw object across collection",
            "--changed-path",
            "tests/T1.txt",
        )

        self.assertEqual(reopened["invalidated_task_ids"], ["T1"])
        state = self.state()
        self.assertEqual(state["active_package"]["phase"], "tests")
        self.assertEqual(
            state["task_states"]["T1"]["baseline_identity"], baseline
        )
        self.assertEqual(state["task_states"]["T1"]["status"], "active")
        (self.project / "tests" / "T1.txt").write_text(
            "corrected fixture", encoding="utf-8"
        )
        context = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "expected_red",
        )
        self.assertEqual(context["test_ids"], ["test.T1"])

    def test_released_unfinished_task_recovers_sealed_red_baseline(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        original_baseline = self.state()["task_states"]["T1"][
            "baseline_identity"
        ]
        red = self.evidence(
            "sealed-before-controller-upgrade",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        (self.project / "src" / "T1.txt").write_text(
            "implemented before controller upgrade", encoding="utf-8"
        )
        self.command(
            "checkpoint",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--next-action",
            "re-enter after controller upgrade",
            "--release",
        )
        self.begin("T1")

        recovered = self.state()["active_package"]["baseline_identity"]["T1"]
        self.assertEqual(
            recovered["production_scope"],
            original_baseline["production_scope"],
        )
        context = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
        )
        self.assertEqual(context["task_id"], "T1")

    def test_planned_test_scope_is_required_only_when_producing_evidence(self) -> None:
        plan = make_plan(tests_first="required")
        plan["tasks"][0]["planned_test_scope"] = ["tests/generated-T1.txt"]
        self.write_plan(plan)
        self.activate()
        resumed = self.command(
            "resume", "--plan-dir", str(self.plan_dir)
        )
        self.assertEqual(resumed["ready_ids"], ["T1"])
        self.begin("T1")

        missing = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "expected_red",
            ok=False,
        )
        self.assertEqual(missing["error"]["code"], "freshness_input_missing")
        (self.project / "tests" / "generated-T1.txt").write_text(
            "generated test", encoding="utf-8"
        )
        context = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "expected_red",
        )
        self.assertIn("test_scope", context["freshness_identity"])

    def test_empty_planned_scope_preserves_existing_contract_identity(self) -> None:
        plan = make_plan()
        task_without_field = plan["tasks"][0]
        identity_without_field = TASKCTL._task_contract_identity(
            plan,
            task_without_field,
        )
        task_without_field["planned_test_scope"] = []
        identity_with_empty_field = TASKCTL._task_contract_identity(
            plan,
            task_without_field,
        )
        self.assertEqual(identity_with_empty_field, identity_without_field)

    def test_closed_evidence_accepts_same_version_runner_change(self) -> None:
        plan = make_plan()
        plan["tasks"][0]["freshness_scopes"] = {
            "runner": ["runner.txt"]
        }
        plan["evidence_profiles"]["default"]["claim_rules"][
            "behavior"
        ]["freshness_keys"].append("runner")
        runner_path = self.project / "runner.txt"
        runner_path.write_text("runner v1", encoding="utf-8")
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        identities = TASKCTL._task_identities(
            plan,
            plan["tasks"][0],
            self.project,
        )
        report = self.evidence(
            "runner-compatible",
            "T1",
            ["behavior"],
            freshness={
                key: identities[key]
                for key in (
                    "contract",
                    "production_scope",
                    "test_scope",
                    "runner",
                )
            },
        )
        self.close(report)
        runner_path.write_text("runner v1 plus diagnostics", encoding="utf-8")
        audit = self.command(
            "audit",
            "--plan-dir",
            str(self.plan_dir),
            "--all",
            "--details",
        )
        self.assertTrue(audit["cards"][0]["complete"])
        self.assertEqual(audit["cards"][0]["stale_evidence"], 0)

    def test_impact_returns_exact_selected_test_ids(self) -> None:
        self.write_plan(make_plan(tests_first="required"))
        self.activate()
        self.begin("T1")
        red = self.evidence(
            "impact-red",
            "T1",
            [],
            phase="expected_red",
            result="expected_fail",
            started_at="2026-08-04T00:00:00Z",
            completed_at="2026-08-04T00:01:00Z",
        )
        self.command(
            "seal-red",
            "--task-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(red),
        )
        impact = self.command(
            "impact", "--task-dir", str(self.plan_dir)
        )
        self.assertEqual(impact["test_ids_by_task"], {"T1": ["test.T1"]})
        self.assertEqual(impact["selected_test_ids"], ["test.T1"])

    def test_stale_dependency_claim_is_revalidated_by_next_package(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        self.begin("T1")
        self.close(self.evidence("t1-green", "T1", ["behavior"]))
        (self.project / "src" / "T1.txt").write_text("changed after proof", encoding="utf-8")
        payload = self.command("resume", "--plan-dir", str(self.plan_dir))
        self.assertEqual(payload["dependency_blocked_ids"], [])
        self.assertEqual(payload["ready_ids"], ["T2"])
        self.assertEqual(payload["recommended_package"]["task_ids"], ["T2"])
        self.command(
            "begin",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T2",
            "--expected-revision",
            str(self.state()["revision"]),
        )
        impact = self.command("impact", "--plan-dir", str(self.plan_dir))
        self.assertEqual(impact["revalidation_task_ids"], ["T1"])

    def test_unfinished_dependency_remains_blocked(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        payload = self.command("resume", "--plan-dir", str(self.plan_dir))
        self.assertEqual(payload["ready_ids"], ["T1"])
        self.assertNotIn("T2", payload["ready_ids"])

    def test_active_task_can_revalidate_its_stale_dependency(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        self.begin("T1")
        self.close(self.evidence("t1-initial", "T1", ["behavior"]))
        self.begin("T2")
        (self.project / "src" / "T1.txt").write_text(
            "changed while dependent is active",
            encoding="utf-8",
        )

        context = self.command(
            "evidence-context",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--phase",
            "verification",
        )
        self.assertEqual(context["task_id"], "T1")

        result = self.close(
            self.evidence("t1-revalidated", "T1", ["behavior"]),
            self.evidence("t2-green", "T2", ["integration"]),
        )
        self.assertEqual(result["completed"], ["T2"])
        self.assertEqual(result["remaining"], [])

    def test_impact_and_package_context_include_only_stale_consumed_dependency(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        self.begin("T1")
        self.close(self.evidence("t1-initial", "T1", ["behavior"]))
        self.begin("T2")
        (self.project / "src" / "T1.txt").write_text(
            "changed while T2 is active", encoding="utf-8"
        )

        impact = self.command(
            "impact",
            "--task-dir",
            str(self.plan_dir),
        )
        self.assertEqual(impact["revalidation_task_ids"], ["T1"])
        self.assertEqual(
            impact["dependency_issues"][0]["subject"],
            "T1:behavior",
        )

        bundle = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--package",
            "--phase",
            "verification",
        )
        self.assertEqual(bundle["task_ids"], ["T1", "T2"])
        self.assertEqual(bundle["revalidation_task_ids"], ["T1"])
        self.assertEqual(
            [item["task_id"] for item in bundle["contexts"]],
            ["T1", "T2"],
        )

        output_dir = self.project / "tmp" / "package-contexts"
        written = self.command(
            "evidence-context",
            "--task-dir",
            str(self.plan_dir),
            "--package",
            "--phase",
            "verification",
            "--output-dir",
            str(output_dir),
        )
        self.assertNotIn("contexts", written)
        self.assertEqual(len(written["context_files"]), 2)
        self.assertEqual(
            [self.read_json(Path(path))["task_id"] for path in written["context_files"]],
            ["T1", "T2"],
        )

    def test_close_imports_package_evidence_in_one_revision(self) -> None:
        self.write_plan(make_plan(two_tasks=True))
        self.activate()
        self.begin("T1")
        self.close(self.evidence("t1-initial", "T1", ["behavior"]))
        self.begin("T2")
        (self.project / "src" / "T1.txt").write_text(
            "changed while T2 is active", encoding="utf-8"
        )
        before_revision = self.state()["revision"]

        result = self.close(
            self.evidence("t1-package-revalidation", "T1", ["behavior"]),
            self.evidence("t2-package-green", "T2", ["integration"]),
        )

        self.assertEqual(result["completed"], ["T2"])
        self.assertEqual(result["remaining"], [])
        self.assertEqual(result["state_revision"], before_revision + 1)

    def test_audit_is_compact_and_reopens_stale_done_task(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        self.begin("T1")
        self.close(self.evidence("t1-green", "T1", ["behavior"]))
        (self.project / "src" / "T1.txt").write_text("stale", encoding="utf-8")
        audit = self.command("audit", "--plan-dir", str(self.plan_dir), "--all", ok=False)
        self.assertEqual(audit["failed_task_ids"], ["T1"])
        self.assertEqual(audit["cards"], [])
        applied = self.command(
            "audit",
            "--plan-dir",
            str(self.plan_dir),
            "--all",
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
            ok=False,
        )
        self.assertEqual(applied["changed_to_needs_review"], ["T1"])
        resumed = self.command("resume", "--plan-dir", str(self.plan_dir))
        self.assertEqual(resumed["needs_review_count"], 1)
        self.assertEqual(resumed["needs_review_ids"], ["T1"])
        rendered = self.command("render", "--task-dir", str(self.plan_dir))
        self.assertEqual(rendered["status_counts"]["needs_review"], 1)
        markdown = (self.plan_dir / "TASK_TABLE.md").read_text(encoding="utf-8")
        self.assertIn("needs_review=1", markdown)

    def assert_evidence_rejected(self, report: Path) -> None:
        self.command(
            "close",
            "--plan-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(report),
            ok=False,
        )

    def test_evidence_rejects_completed_time_before_start(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        self.begin("T1")
        self.assert_evidence_rejected(
            self.evidence(
                "bad-time",
                "T1",
                ["behavior"],
                started_at="2026-08-04T00:03:00Z",
                completed_at="2026-08-04T00:02:00Z",
            )
        )

    def test_evidence_rejects_unknown_producer(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        self.begin("T1")
        self.assert_evidence_rejected(
            self.evidence("bad-producer", "T1", ["behavior"], producer="unknown")
        )

    def test_evidence_rejects_raw_artifact_hash_mismatch(self) -> None:
        plan = make_plan()
        plan["producers"]["machine"]["requires_raw_artifacts"] = True
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        raw = self.project / "reports" / "raw.log"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("raw", encoding="utf-8")
        self.assert_evidence_rejected(
            self.evidence(
                "bad-raw",
                "T1",
                ["behavior"],
                raw_artifacts=[
                    {"root": "project", "path": "reports/raw.log", "sha256": "0" * 64}
                ],
            )
        )

    def test_ingested_evidence_uses_immutable_plan_snapshots(self) -> None:
        plan = make_plan()
        plan["producers"]["machine"]["requires_raw_artifacts"] = True
        self.write_plan(plan)
        self.activate()
        self.begin("T1")
        raw = self.project / "reports" / "raw.log"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("raw", encoding="utf-8")
        report = self.evidence(
            "snapshot-evidence",
            "T1",
            ["behavior"],
            raw_artifacts=[
                {
                    "root": "project",
                    "path": "reports/raw.log",
                    "sha256": TASKCTL._sha256_file(raw),
                }
            ],
        )

        result = self.close(report)

        self.assertEqual(result["completed"], ["T1"])
        evidence_ref = self.state()["task_states"]["T1"]["evidence_refs"][0]
        index = self.read_json(self.plan_dir / evidence_ref)
        self.assertEqual(index["source_envelope"]["root"], "plan")
        self.assertTrue(index["source_envelope"]["path"].startswith("evidence/sources/"))
        indexed_raw = index["envelope"]["raw_artifacts"][0]
        self.assertEqual(indexed_raw["root"], "plan")
        self.assertTrue(indexed_raw["path"].startswith("evidence/artifacts/"))
        self.assertTrue((self.plan_dir / indexed_raw["path"]).is_file())

        raw.write_text("overwritten", encoding="utf-8")
        report.write_text("{}\n", encoding="utf-8")
        audit = self.command("audit", "--plan-dir", str(self.plan_dir), "--all")
        self.assertEqual(audit["failed"], 0)

    def test_evidence_envelope_cannot_leak_claims_across_tasks(self) -> None:
        plan = make_plan(two_tasks=True)
        plan["tasks"][1]["depends_on"] = []
        plan["solution_steps"][1]["depends_on"] = []
        plan["tasks"][1]["rollback_scope"] = plan["tasks"][0]["rollback_scope"]
        self.write_plan(plan)
        self.activate()
        self.command(
            "begin",
            "--plan-dir",
            str(self.plan_dir),
            "--task",
            "T1",
            "--task",
            "T2",
            "--expected-revision",
            str(self.state()["revision"]),
        )
        report = self.evidence("ambiguous-batch", "T1", ["behavior", "integration"])
        envelope = self.read_json(report)
        envelope["task_ids"] = ["T1", "T2"]
        envelope["subjects"] = ["asset:T1", "asset:T2"]
        envelope["test_ids"] = ["test.T1", "test.T2"]
        self.write_json(report, envelope)
        payload = self.command(
            "close",
            "--plan-dir",
            str(self.plan_dir),
            "--expected-revision",
            str(self.state()["revision"]),
            "--evidence",
            str(report),
            ok=False,
        )
        self.assertIn("exactly one task", payload["error"]["message"])

    def test_direct_plan_edit_is_rejected(self) -> None:
        plan = make_plan()
        self.write_plan(plan)
        self.activate()
        plan["design_revision"] = "edited-directly"
        self.write_json(self.plan_dir / "plan.json", plan)
        payload = self.command("resume", "--plan-dir", str(self.plan_dir), ok=False)
        self.assertIn("revision", payload["error"]["message"])

    def test_contract_lowering_requires_decision_and_invalidates_task(self) -> None:
        self.write_plan(make_plan())
        self.activate()
        candidate = make_plan()
        candidate["tasks"][0]["outcome"] = "Smaller outcome"
        candidate_path = self.plan_dir / "candidate.json"
        self.write_json(candidate_path, candidate)
        preview = self.command(
            "amend", "--plan-dir", str(self.plan_dir), "--candidate", str(candidate_path)
        )
        self.assertIn("task T1 changed outcome", preview["impact"]["lowered_contracts"])
        self.command(
            "amend",
            "--plan-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
            ok=False,
        )
        candidate["decision_refs"] = ["user:approved-smaller-outcome"]
        self.write_json(candidate_path, candidate)
        self.audit_candidate(candidate_path)
        applied = self.command(
            "amend",
            "--plan-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
            "--apply",
            "--expected-revision",
            str(self.state()["revision"]),
            "--decision-ref",
            "user:approved-smaller-outcome",
        )
        self.assertTrue(applied["ok"])
        self.assertEqual(self.state()["task_states"]["T1"]["status"], "ready")

    def test_amendment_cannot_silently_weaken_scope_or_flow_evidence_binding(self) -> None:
        plan = self.strict_single_receipt_plan()
        self.write_plan(plan)
        self.activate()
        candidate = self.strict_single_receipt_plan()
        candidate["tasks"][0]["scope_enforced"] = False
        candidate_path = self.plan_dir / "candidate.json"
        self.write_json(candidate_path, candidate)
        rejected = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
            ok=False,
        )
        self.assertIn("must enable scope_enforced", rejected["error"]["message"])

        candidate = self.strict_single_receipt_plan()
        candidate["test_qualifications"]["test.T1"]["observed_scopes"].append(
            "public:fixture:unqualified-extra-scope"
        )
        candidate["acceptance_flows"][0]["evidence_mode"] = "coverage_matrix"
        self.write_json(candidate_path, candidate)

        preview = self.command(
            "amend",
            "--task-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
        )
        lowerings = preview["impact"]["lowered_contracts"]
        self.assertIn("test test.T1 changed observed_scopes", lowerings)
        self.assertIn("acceptance flow FLOW-STRICT changed evidence_mode", lowerings)

    def test_moving_missing_test_to_planned_scope_is_not_a_lowering(self) -> None:
        plan = make_plan()
        plan["tasks"][0]["test_scope"].append("tests/generated-T1.txt")
        self.write_plan(plan)
        self.activate()
        candidate = make_plan()
        candidate["tasks"][0]["planned_test_scope"] = [
            "tests/generated-T1.txt"
        ]
        candidate_path = self.plan_dir / "candidate.json"
        self.write_json(candidate_path, candidate)
        preview = self.command(
            "amend",
            "--plan-dir",
            str(self.plan_dir),
            "--candidate",
            str(candidate_path),
        )
        self.assertFalse(preview["impact"]["lowered_contracts"])


if __name__ == "__main__":
    unittest.main()
