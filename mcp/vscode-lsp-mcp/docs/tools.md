# MCP tool reference

The server exposes exactly 18 tools. MCP `tools/list` is authoritative for input JSON Schema and mutation annotations; clients should discover schemas instead of copying them from this overview.

| Tool | Class | Purpose |
|---|---|---|
| `list_workspaces` | read | List usable VS Code windows/workspaces and their public IDs and root aliases. |
| `health_check` | read | Check server, bridge, workspace, and optional document activation health. |
| `get_capabilities` | read | Report effective language-provider, command, and task capabilities. |
| `workspace_symbols` | read | Search symbols across a selected workspace and report the current Provider observation. |
| `document_symbols` | read | Return one logical file's symbol tree with optional exact filters, full ranges, and Provider observation. |
| `symbol_info` | read | Query hover, declaration, definition, type definition, implementation, and signature information at a position, with optional path filters for location results. |
| `get_references` | read | Find references with declaration/path filters and an optional per-call 1,000–90,000 ms timeout. |
| `get_call_hierarchy` | read | Traverse incoming, outgoing, or both call-hierarchy directions. |
| `get_type_hierarchy` | read | Traverse supertypes, subtypes, or both type-hierarchy directions. |
| `get_diagnostics` | read | Read diagnostics already published by active language providers; supplying `files` implies file scope. |
| `rename_preview` | preview | Prepare a rename inside required include globs, with an optional per-call 1,000–90,000 ms provider timeout, and return a bounded immutable preview. |
| `rename_apply` | mutation | Apply one unexpired rename preview by `previewId`. |
| `code_actions` | read | List bounded code-action candidates for a range. |
| `code_action_preview` | preview | Resolve one action and return its edit preview without applying it. |
| `code_action_apply` | mutation | Apply one unexpired code-action preview by `previewId`. |
| `format_preview` | preview | Preview document or range formatting edits. |
| `format_apply` | mutation | Apply one unexpired formatting preview by `previewId`. |
| `execute_command` | mutation | Execute a standard user command, trusted-workspace task, or explicitly authorized custom command. |

Only `rename_apply`, `code_action_apply`, `format_apply`, and `execute_command` are marked destructive. Preview and read tools are read-only/idempotent; the four mutation tools are not treated as idempotent.

## Response contract

Every `tools/call` response exposes exactly one YAML `TextContent` payload. Successful responses use `ok: true` with `data`; expected tool failures use `ok: false` with `error.code`, `error.message`, and `error.retryable`, and set the MCP error indicator when appropriate. The server validates the underlying DTO against an internal output schema before YAML serialization, but does not return `structuredContent` or advertise `outputSchema`, so model contexts do not receive duplicate YAML and JSON payloads.

Collections report `results` and `available`, with optional `warnings`. Result ordering is deterministic before applying the 1-based inclusive result window. The default window is 20 and the maximum window is 100. Symbol collections may also return `provider: {status, elapsedMs, attempts}`; this is an observation of that invocation, not an availability promise or SLA. Expected workspace/document symbol Provider failures retain their existing error code and may carry the same observation.

`document_symbols.nameEquals` compares the final path component by ordinal exact equality; `pathEquals` compares the complete path the same way. Both filters run before the result window and preserve every exact duplicate or overload. `includeRange` defaults to false. When true, each available Provider range is returned as 1-based, end-exclusive `startLine/startColumn/endLine/endColumn`; `provider_range_unavailable` warns that at least one displayed symbol lacked a usable full range. Read source before relying on a range, and use syntax tooling when a Provider range is absent or unsuitable.

Common error categories include invalid input/path/range, unavailable or not-ready providers, unknown/stale workspace registration, timeout/disconnect/protocol failures, stale or missing previews, unauthorized commands/tasks, and failed edits. The internal output schemas and this reference remain the source of truth for exact fields.

## Mutations

Rename, code-action, and formatting writes are two-step operations. A preview records source versions and normalized edits; apply revalidates the preview, rejects stale or reused IDs, and returns the logical changed-file list. Preview IDs are scoped to the current local server session and are not durable capabilities.

`rename_preview` requires `includeGlobs` and accepts `excludeGlobs` plus an optional `timeoutMs` from 1,000 through 90,000. Omit `timeoutMs` for the window's configured provider timeout (60 seconds by default); use a larger per-call value only for a known slow provider without changing persistent VS Code settings. The globs are a complete-edit safety boundary, not a request to discard unwanted edits: after the provider edit is normalized, scope is checked before slower symbol-identity queries. If even one target is outside the declared scope, the whole preview fails immediately with a bounded `RENAME_SCOPE_VIOLATION`, no `previewId` is issued, and nothing is cached. Before caching, every edit must preserve the prepared symbol text and resolve through definition/declaration to the same identity. If a provider intentionally edits a semantic string position that has no definition (for example a Python `__all__` entry), the position must instead appear exactly in one bounded Reference Provider result for the target; this is corroboration, not a general unresolved-edit exemption. Mixed, ambiguous, uncorroborated, provider-timed-out, or over-budget results fail with `RENAME_IDENTITY_UNVERIFIED`; identity-provider timeouts use the `providerTimedOut` reason instead of being misreported as a general rename-provider timeout. An effective edit set must be non-empty or the call fails with `RENAME_NO_EDITS`. A complete rename that exceeds 50 changed files, 100 edits, 50,000 old/new text characters, or 65,536 bytes in its final YAML tool response fails with `PREVIEW_TOO_LARGE`; these errors never expose a truncated applicable preview.

`execute_command` supports either a VS Code command target or a named task target. Trusted workspaces enable bounded save/debug/reload commands and discovered foreground tasks by default; custom commands still require exact policy authorization. It does not accept a free-form shell command. Task targets are resolved by folder/name, checked for non-interactive execution, and awaited through process-end and task-end. On Windows, a dependency-free `ProcessExecution` task is run through a bounded tee wrapper: failure can return `error.details.outputLog`; success discards the capture by default, or returns `data.outputLog` when `retainOutputLog: true`. The metadata contains a workspace-logical path, line/byte counts, UTF-8 encoding, and truncation state; output text is never inlined. Retained logs live below `.vscode-lsp-mcp/task-logs`, are capped at 64 MiB, and only the newest ten managed logs are kept. Shell tasks, dependency graphs, and failures before process start retain their original execution semantics but may have no `outputLog`. Window or Extension Host reload is acknowledged and scheduled before the expected bridge disconnect; call `list_workspaces` again after reconnection.

## Provider limitations

Tool availability is based on the VS Code APIs that the active language extensions actually provide. A language may support definition and rename but publish no diagnostics, or return an empty valid result. Empty results are not automatically provider failures. `get_capabilities` performs bounded probes and is advisory: `unknown` or `timedOut` is insufficient evidence to block a direct, scoped tool call. Use it together with `health_check`, the requested semantic operation, and the installer `doctor` command to distinguish unsupported, not-ready, empty, and transport-failure states.

`get_references.timeoutMs` overrides the provider timeout for one call without changing VS Code settings. Omit it for the 60-second default. For a known slow C++ index, use one bounded call such as `timeoutMs: 90000`; an explicit timeout reserves the whole interval for the public Reference Provider instead of first attempting the optional scoped C++ fallback. The server bridge allows 95 seconds, so the documented maximum leaves transport cleanup headroom.

Large workspaces should use `includeGlobs` or `excludeGlobs` on workspace symbols, symbol-location queries, and references to remove generated, saved, vendored, or duplicate source trees before applying the result window. Most read-tool filters, including document-symbol exact filters, run after the VS Code provider returns; they reduce response size, not Provider enumeration time. For C/C++ references, an explicit include glob with a fixed directory prefix enables a bounded scoped fallback: the extension discovers exact identifier tokens only inside that scope and retains candidates whose definition/declaration identity matches the target. A fully verified fallback result carries the `references_scoped_identity_fallback` warning; if its file, text, occurrence, time, or semantic-verification budget cannot prove completeness, the extension falls back to the public Reference Provider instead of returning a partial result. Prefer a precise file, position, and narrow source-tree scope.
