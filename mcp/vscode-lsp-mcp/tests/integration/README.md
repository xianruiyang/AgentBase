# Integration suites

## Extension Host read and hierarchy

Run `npm run test:integration:read-hierarchy` for the P6-002 gate. The suite composes the existing real Stage B and Stage C paths and validates:

- a workspace route is absent before companion activation and discoverable afterwards;
- definition, references, document symbols, diagnostics, capabilities, call hierarchy and type hierarchy against initially closed or dirty documents;
- workspace symbols as a workspace-scoped operation, where document visibility and dirty state are not applicable;
- unsupported/empty Provider results, timeout, cancellation, Host restart and stale-route non-replay;
- result windows and removal of internal paths, URIs, Provider commands and IPC metadata.

Set `P6_002_REPORT_PATH` to persist the aggregate JSON evidence. All VS Code workspaces, user-data directories and intermediate reports otherwise live below the OS temporary directory and are removed on exit.

## Extension Host mutation and command

Run `npm run test:integration:mutation-command` for the P6-003 gate. It validates real Rename, Code Action and document/range formatting Providers through preview/apply, stale-preview rejection, dirty multi-file edits, save modes, Unicode output truncation, process-task success/non-zero/timeout, default success-log deletion, opt-in success-log retention, failure-log stdout/stderr capture with preserved exit code and `${workspaceFolder}` expansion, and input/command-variable rejection before task start or UI API invocation.

Set `P6_003_REPORT_PATH` to persist the JSON evidence. The fixture workspace, generated task configuration, task markers and isolated VS Code profile are removed on exit.

## Real stdio all-tool, multi-workspace, and recovery gate

Run `npm run test:integration:all-tools` for the P6-004 gate. One long-lived official MCP Client starts before two concurrent isolated VS Code Extension Hosts and validates:

- the frozen 18-tool `tools/list` registry and both success/failure output envelopes for every tool;
- exactly one YAML TextContent payload and no `structuredContent` on every `tools/call` response;
- semantic, mutation, and command routing isolation across two simultaneous workspaces;
- a 140-reference result set windowed to entries 41 through 60;
- Host restart, a restored dead endpoint, malformed-registration quarantine, stale-route non-replay, and recovery under a new workspace ID;
- captured raw server stdout containing JSON-RPC frames only, with diagnostics confined to stderr and no internal connection metadata in public results.

Set `P6_004_REPORT_PATH` to persist the JSON evidence. The runner removes both workspace/profile trees and its exact stale/quarantine registry artifacts on exit.

## Installed-provider multi-language audit

Run `npm run test:manual:multilanguage` for the P6-005 Windows audit. The runner links only the currently installed C/C++/clangd/C# extension directories into an isolated Extension Host, restores a temporary .NET project, and records both direct VS Code Provider readiness and companion results for definition, references, diagnostics, and rename preview/apply.

The audit never installs or updates extensions. Missing extensions or Provider capabilities remain explicit report states rather than fabricated success. Set `P6_005_REPORT_PATH` to persist the JSON evidence; `P6_005_EXTENSIONS_DIR` and `P6_005_CPP_COMPILER_PATH` may select an existing extension directory or compiler without modifying them.

## Existing MCP coexistence gate

Run `npm run test:integration:coexistence` for the optional P7-005 Windows gate. The external components are not vendored by this repository: set `P7_005_VSCODE_MCP_ROOT` and `P7_005_AST_MCP_ROOT` to their exact installation/source roots first; `P7_005_AST_MCP_WORKSPACE_ROOT` may override the AST server workspace root. Missing inputs fail with an explicit prerequisite error instead of probing former sibling directories. The gate freezes the distinct Codex registration names, extension IDs, configuration prefixes, managed roots and Named Pipe prefixes, then starts the existing `vscode-mcp`, existing `simplechat-ast` and new `vscode-lsp-mcp` stdio servers concurrently. All three must initialize and expose their required tool registries, including the frozen 18-tool registry for the new server.

Set `P7_005_COEXIST_REPORT_PATH` to persist the bounded JSON evidence. The runner closes every MCP client and child transport before exit and does not install, unregister or edit either existing component. Because this gate depends on separately managed installations, it remains outside the self-contained `verify:release` entry.
