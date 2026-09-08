from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALUATION_ROOT.parents[1]
if str(EVALUATION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATION_ROOT))

import agentbase_codex  # noqa: E402


class EvoComponentTests(unittest.TestCase):
    def _projection(self, workspace: Path) -> dict:
        fixture = "development/agent-evaluation/tests/fixtures/evo/components"
        return agentbase_codex.stage_codex_component_projection(
            project_root=PROJECT_ROOT,
            workspace=workspace,
            selected={
                "hooks": [{"id": "fixture-hook", "source": f"{fixture}/hooks"}],
                "mcp": [{"id": "fixture-mcp", "source": f"{fixture}/mcp"}],
                "tools": [{"id": "fixture-tools", "source": f"{fixture}/tools"}],
            },
            max_agents=1,
        )

    def test_projection_generates_native_hook_mcp_and_tool_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            projection = self._projection(workspace)
            config = tomllib.loads((workspace / ".codex" / "config.toml").read_text(encoding="utf-8"))
            server = config["mcp_servers"]["evo-fixture"]
            self.assertEqual(server["command"], "python.exe")
            self.assertTrue(Path(server["args"][0]).is_file())
            hooks = json.loads((workspace / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            command = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["commandWindows"]
            self.assertIn(str(workspace), command)
            self.assertTrue(projection["hooks_enabled"])
            self.assertIn(".agentbase/evo-codex-projection.json", projection["managed_paths"])

            environment = dict(os.environ)
            environment["PATH"] = os.pathsep.join([*projection["tool_paths"], environment["PATH"]])
            tool = subprocess.run(
                ["cmd.exe", "/d", "/c", "evo-fixture-tool.cmd"], cwd=workspace, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
            )
            self.assertEqual(tool.returncode, 0, tool.stderr.decode(errors="replace"))
            self.assertEqual(json.loads(tool.stdout), {"tool": "selected-candidate", "ok": True})

            requests = "".join(json.dumps(value) + "\n" for value in [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "selected_component", "arguments": {}}},
            ])
            mcp = subprocess.run(
                [server["command"], *server["args"]], cwd=workspace, input=requests.encode(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
            )
            self.assertEqual(mcp.returncode, 0, mcp.stderr.decode(errors="replace"))
            responses = [json.loads(line) for line in mcp.stdout.decode().splitlines()]
            self.assertEqual(responses[2]["result"]["content"][0]["text"], "EVO_MCP_VALUE=23")

            hook_script = workspace / ".agentbase" / "components" / "hooks" / "fixture-hook" / "hook.ps1"
            hook = subprocess.run(
                ["pwsh.exe", "-NoProfile", "-NonInteractive", "-File", str(hook_script), "-Workspace", str(workspace)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
            )
            self.assertEqual(hook.returncode, 0, hook.stderr.decode(errors="replace"))
            self.assertEqual((workspace / "evo-hook-observed.txt").read_text(), "EVO_HOOK_VALUE=31")

    def test_projection_reuses_exact_manifest_and_replaces_changed_managed_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            first = self._projection(workspace)
            second = self._projection(workspace)
            self.assertEqual(second["disposition"], "reused")
            self.assertEqual(first["identity_sha256"], second["identity_sha256"])
            projected_tool = workspace / ".agentbase" / "components" / "tools" / "fixture-tools" / "bin" / "evo-fixture-tool.cmd"
            projected_tool.write_text("changed\n", encoding="utf-8")
            third = self._projection(workspace)
            self.assertEqual(third["disposition"], "replaced")
            self.assertEqual(first["identity_sha256"], third["identity_sha256"])


if __name__ == "__main__":
    unittest.main()
