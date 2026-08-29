# Configuration

## Language-provider timeout

The window-scoped `vscodeLspMcp.providerTimeoutMs` setting bounds each VS Code language-provider invocation. It defaults to 60,000 milliseconds and accepts integers from 1,000 through 300,000. Configure it in user or workspace settings, for example `{ "vscodeLspMcp.providerTimeoutMs": 180000 }`, then reload the VS Code window. `get_references`, `verify_symbol_candidates`, and `rename_preview` also accept a per-call `timeoutMs` in the same range; use that when only one known-slow query needs a larger budget and no reload or persistent setting change is desirable. A result that repeatedly arrives at this exact boundary usually means the underlying language Provider remained pending for the whole interval.

VS Code does not expose a cancellation token on the public execute-provider commands. After a timed-out or caller-cancelled C/C++ references or rename invocation, the companion therefore sends a bounded call-hierarchy preparation pulse at a whitespace position. cpptools treats that new reference-family request as cancellation of its current references/rename operation. The companion then waits up to three seconds for the original Provider promise to settle and releases the single-flight slot only after that real settlement. If the active C/C++ Provider does not support this interruption behavior, the slot remains protected until its original promise ends; it is never force-cleared in a way that could stack duplicate background scans.

For cpptools, a small candidate-file count does not imply a cheap references query: every candidate can require parsing a large C++ translation unit and its transitive Unreal Engine headers. Validate the compile database and every referenced response file first. Repeated queries may also be expensive because `C_Cpp.references.maxCachedProcesses` defaults to `0`; the machine-scoped `C_Cpp.references.maxConcurrentThreads`, `C_Cpp.references.maxCachedProcesses`, and `C_Cpp.references.maxMemory` settings trade RAM for references/rename throughput. Tune them only against available memory and observed process usage instead of hiding an invalid compile configuration with a longer MCP timeout.

Rename preview has an additional bounded identity-verification stage after the provider returns an edit. A definition/declaration timeout during that stage is reported as `RENAME_IDENTITY_UNVERIFIED` with reason `providerTimedOut`, rather than as a generic rename-provider timeout. Scope violations are rejected before identity verification, so narrowing `includeGlobs` can reject a polluted provider edit promptly but cannot make an in-scope identity query faster.

## VS Code command and task policy

Read-only language tools are available once the companion is active for an open workspace. In a trusted workspace, `execute_command` enables two normal VS Code workflows without per-item allowlist maintenance:

- bounded save and debug-control commands, plus window and Extension Host reload;
- discovered foreground `ProcessExecution` and `ShellExecution` tasks, including verified dependencies.

The runtime still rejects untrusted workspaces, task input/command variables, background tasks, `CustomExecution`, ambiguous task identity, interactive UI commands, authentication, extension management, VS Code exit, and bridge lifecycle commands. A task may run the shell command declared by the trusted workspace, but the MCP tool never accepts a free-form shell command line.

Example workspace or user `settings.json`:

```json
{
  "vscodeLspMcp.commandPolicy": {
    "allowStandardCommands": true,
    "allowWorkspaceTasks": true,
    "commands": [
      {
        "commandId": "publisher.extension.customCommand",
        "nonInteractive": true,
        "completion": "promise",
        "maxTimeoutMs": 30000,
        "argumentSchema": {
          "$schema": "https://json-schema.org/draft/2020-12/schema",
          "type": "array",
          "maxItems": 0
        }
      }
    ],
    "tasks": []
  }
}
```

Command policy rules:

- `allowStandardCommands` defaults to `true`. It covers argument-free save, debug start/run/control, `workbench.action.reloadWindow`, and `workbench.action.restartExtensionHost`. Reload commands return an accepted/scheduled result before the bridge disconnects; reacquire the workspace with `list_workspaces` afterward.
- `allowWorkspaceTasks` defaults to `true`. Task identity must still resolve to one workspace folder and one discovered task. Each task and dependency passes the non-interactive and completion-verification checks above.
- Set either default to `false` for a locked-down environment. Entries under `commands` and `tasks` then provide exact custom authorization; standard lifecycle commands remain disabled when `allowStandardCommands` is false.
- `nonInteractive` must be `true`; commands that can display UI, request input, or require human confirmation must not be authorized.
- `completion` must be `promise`; fire-and-forget commands are rejected.
- `argumentSchema`, when present, validates the complete arguments array using JSON Schema Draft 2020-12. Object schemas must be closed.
- `maxTimeoutMs` is an upper bound from 1,000 through 600,000 milliseconds. A request may choose a smaller timeout but not a larger one.
- A custom task entry is the exact pair of logical `rootAlias` and VS Code task name. It can impose a smaller `maxTimeoutMs`; `allowDependencies` controls its dependency traversal.

Policy changes are read on each invocation. `get_capabilities` reports whether command/task execution is exposed, while the target-specific runtime preflight remains authoritative.

### Task output logs

On Windows, a dependency-free `ProcessExecution` task uses a controlled PowerShell tee wrapper that preserves VS Code variable expansion, the visible terminal stream, problem matchers, and the child exit code. Successful runs remove their temporary capture by default. Set `retainOutputLog: true` on `execute_command` only when successful task output is needed; success then returns `data.outputLog`. A non-zero, cancelled, timed-out, or otherwise started-but-unverifiable run retains its output without that opt-in and may return `error.details.outputLog`. Both forms point to normalized UTF-8 output under `<task-root>/.vscode-lsp-mcp/task-logs/` and contain `path`, `lineCount`, `byteCount`, `encoding`, and `truncated`; the output body is not placed in the MCP response.

Each log is limited to 64 MiB. The companion keeps at most ten managed logs per task root and removes stale managed temporary files after 24 hours. It never edits the repository ignore rules. Add this to the task root's existing `.gitignore` when logs must remain local:

```gitignore
/.vscode-lsp-mcp/
```

The public VS Code Task API still has no stdout/stderr stream. Capture is therefore unavailable for `ShellExecution`, dependency graphs, unsupported platforms, and failures before process launch; those cases keep the original task behavior and omit `outputLog` rather than returning unrelated terminal content. Treat retained logs as potentially sensitive build output.

The installer-managed `config.json` is reserved for backup/restore compatibility and is not read by the current Extension Host runtime. Configure the VS Code setting above; do not rely on edits to the installed file.

## Codex MCP client

The installer creates a stable Node launcher under the managed program root. In PowerShell, register it without hard-coding a user profile path:

```powershell
codex mcp add vscode-lsp-mcp -- node "$env:LOCALAPPDATA\SimpleChat\vscode-lsp-mcp\bin\vscode-lsp-mcp.cjs"
codex mcp list
```

Restart the Codex UI after changing MCP configuration, then use `/mcp` to inspect the connection. Codex stores user configuration in `~/.codex/config.toml`; trusted projects may also use `.codex/config.toml`. The equivalent resolved configuration is:

```toml
[mcp_servers.vscode-lsp-mcp]
command = "node"
args = ["<resolved-managed-install-root>/bin/vscode-lsp-mcp.cjs"]
startup_timeout_sec = 10
tool_timeout_sec = 330
enabled = true
```

The 330-second client ceiling permits the documented 300-second provider budget plus bridge cleanup. It does not make ordinary calls wait longer: the extension still uses its 60-second default unless a per-call timeout or the window setting deliberately raises it.

Replace the placeholder with the actual resolved path; TOML does not expand PowerShell environment-variable syntax. Current Codex MCP configuration syntax is documented in the [official Codex MCP guide](https://learn.chatgpt.com/docs/extend/mcp.md).

## Workspace and path identity

Call `list_workspaces` first. A workspace is selected with its opaque `workspaceId`, not a physical root. In a single-root workspace, files are root-relative and must not include the returned root alias, for example `src/index.ts`. In a multi-root workspace, files use `<root-alias>/<relative-path>`, for example `root/src/index.ts`.

Paths are slash-separated logical identifiers. Do not send drive letters, UNC paths, `..`, encoded traversal, or physical absolute paths. Multi-root windows can have several aliases; use the alias returned by `list_workspaces`.

Positions and ranges use 1-based lines and columns. Range ends are exclusive. Result windows use 1-based inclusive `resultStart`/`resultEnd`, default to 20 items, and contain at most 100 items.
