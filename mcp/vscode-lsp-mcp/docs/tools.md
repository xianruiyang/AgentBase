# MCP tool reference

The server exposes exactly 19 tools. MCP `tools/list` is authoritative for descriptions, input JSON Schema, and mutation annotations; clients should discover schemas instead of copying them from this overview. Tool descriptions encode the minimum routing decision: use bounded source or AST evidence first, invoke only the missing semantic operation, and stop once the result is sufficient. Health and capability probes are diagnostic, not mandatory preflight.

| Tool | Class | Purpose |
|---|---|---|
| `list_workspaces` | read | Resolve an unknown workspace and root aliases. |
| `health_check` | read | Diagnose bridge or document activation after uncertainty or failure. |
| `get_capabilities` | read | Probe only capabilities that change the next action. |
| `workspace_symbols` | read | After scoped text/AST cannot locate a symbol, return bounded semantic candidates. |
| `document_symbols` | read | Only when source/AST cannot supply the required outline, return bounded Provider document symbols; do not use it for an ordinary C/C++ function list. |
| `symbol_info` | read | At a known position, request only semantics unresolved by source/AST. |
| `get_references` | read | At a known symbol, return complete semantic references when text matches are insufficient. |
| `verify_symbol_candidates` | read | Verify bounded text/AST candidates against one target identity. |
| `get_call_hierarchy` | read | Return bounded overload-aware call relations only when source/AST is insufficient; cold C/C++ requires a current compile_commands entry. |
| `get_type_hierarchy` | read | Return bounded type relations only when source/AST is insufficient. |
| `get_diagnostics` | read | Read diagnostics from the smallest needed scope. |
| `rename_preview` | preview | Preview a complete semantic rename within an explicit path scope. |
| `rename_apply` | mutation | Apply one unexpired rename preview after change validation. |
| `code_actions` | read | For one known range, list bounded code actions only when provider assistance is needed. |
| `code_action_preview` | preview | Resolve one code action into an edit preview without applying it. |
| `code_action_apply` | mutation | Apply one unexpired code-action preview after change validation. |
| `format_preview` | preview | Preview formatting for one known document or range without applying it. |
| `format_apply` | mutation | Apply one unexpired formatting preview after change validation. |
| `execute_command` | mutation | Execute one selected standard command, trusted task, or authorized custom command; never arbitrary shell. |

Only `rename_apply`, `code_action_apply`, `format_apply`, and `execute_command` are marked destructive. Preview and read tools are read-only/idempotent; the four mutation tools are not treated as idempotent.

## Response contract

Every `tools/call` response exposes exactly one YAML `TextContent` payload. Successful responses use `ok: true` with `data`; expected tool failures use `ok: false` with `error.code`, `error.message`, and `error.retryable`, and set the MCP error indicator when appropriate. The server validates the underlying DTO against an internal output schema before YAML serialization, but does not return `structuredContent` or advertise `outputSchema`, so model contexts do not receive duplicate YAML and JSON payloads.

Collections report `results` and `available`, with optional `warnings`. Result ordering is deterministic before applying the 1-based inclusive result window. The default window is 20 and the maximum window is 100. Symbol collections may also return `provider: {status, elapsedMs, attempts}`; this is an observation of that invocation, not an availability promise or SLA. Expected workspace/document symbol Provider failures retain their existing error code and may carry the same observation.

`document_symbols.nameEquals` compares the final path component by ordinal exact equality; `pathEquals` compares the complete path the same way. Both filters run before the result window and preserve every exact duplicate or overload. `includeRange` defaults to false. When true, each available Provider range is returned as 1-based, end-exclusive `startLine/startColumn/endLine/endColumn`; `provider_range_unavailable` warns that at least one displayed symbol lacked a usable full range. Read source before relying on a range, and use syntax tooling when a Provider range is absent or unsuitable.

Common error categories include invalid input/path/range, unavailable or not-ready providers, unknown/stale workspace registration, timeout/disconnect/protocol failures, stale or missing previews, unauthorized commands/tasks, and failed edits. The internal output schemas and this reference remain the source of truth for exact fields.

## Mutations

Rename, code-action, and formatting writes are two-step operations. A preview records source versions and normalized edits; apply revalidates the preview, rejects stale or reused IDs, and returns the logical changed-file list. Preview IDs are scoped to the current local server session and are not durable capabilities.

`rename_preview` requires `includeGlobs` and accepts `excludeGlobs` plus an optional `timeoutMs` from 1,000 through 300,000. Omit `timeoutMs` for the window's configured provider timeout (60 seconds by default); use a larger per-call value only for a known slow provider without changing persistent VS Code settings. The globs are a complete-edit safety boundary, not a request to discard unwanted edits: after the provider edit is normalized, scope is checked before slower symbol-identity queries. If even one target is outside the declared scope, the whole preview fails immediately with a bounded `RENAME_SCOPE_VIOLATION`, no `previewId` is issued, and nothing is cached. Before caching, every edit must preserve the prepared symbol text and resolve through definition/declaration to the same identity. If a provider intentionally edits a semantic string position that has no definition (for example a Python `__all__` entry), the position must instead appear exactly in one bounded Reference Provider result for the target; this is corroboration, not a general unresolved-edit exemption. Mixed, ambiguous, uncorroborated, provider-timed-out, or over-budget results fail with `RENAME_IDENTITY_UNVERIFIED`; identity-provider timeouts use the `providerTimedOut` reason instead of being misreported as a general rename-provider timeout. An effective edit set must be non-empty or the call fails with `RENAME_NO_EDITS`. A complete rename that exceeds 50 changed files, 100 edits, 50,000 old/new text characters, or 65,536 bytes in its final YAML tool response fails with `PREVIEW_TOO_LARGE`; these errors never expose a truncated applicable preview.

`execute_command` supports either a VS Code command target or a named task target. Trusted workspaces enable bounded save/debug/reload commands and discovered foreground tasks by default; custom commands still require exact policy authorization. It does not accept a free-form shell command. Task targets are resolved by folder/name, checked for non-interactive execution, and awaited through process-end and task-end. On Windows, a dependency-free `ProcessExecution` task is run through a bounded tee wrapper: failure can return `error.details.outputLog`; success discards the capture by default, or returns `data.outputLog` when `retainOutputLog: true`. The metadata contains a workspace-logical path, line/byte counts, UTF-8 encoding, and truncation state; output text is never inlined. Retained logs live below `.vscode-lsp-mcp/task-logs`, are capped at 64 MiB, and only the newest ten managed logs are kept. Shell tasks, dependency graphs, and failures before process start retain their original execution semantics but may have no `outputLog`. Window or Extension Host reload is acknowledged and scheduled before the expected bridge disconnect; call `list_workspaces` again after reconnection.

## Provider limitations

Tool availability is based on the VS Code APIs that the active language extensions actually provide. A language may support definition and rename but publish no diagnostics, or return an empty valid result. Empty results are not automatically provider failures. `get_capabilities` performs bounded probes and is advisory: `unknown` or `timedOut` is insufficient evidence to block a direct, scoped tool call. Use it together with `health_check`, the requested semantic operation, and the installer `doctor` command to distinguish unsupported, not-ready, empty, and transport-failure states.

`get_references.searchMode` defaults to `auto`. For C/C++, `auto` first performs a bounded workspace candidate scan over standard C/C++ source extensions, excludes comments and literals, and verifies every remaining token against the target definition/declaration identity. Other languages use the public Reference Provider. `scoped` requires the C/C++ fast path; `provider` explicitly selects full Provider enumeration. `timeoutMs` is the total budget for the selected mode. A full Provider call may use up to 300,000 ms; the server bridge keeps five seconds of transport headroom, so the MCP client timeout must exceed it.

For a large workspace, pass `scopePaths` as existing logical files or directories, for example `['Source/MyModule', 'Plugins/MyPlugin/Source']`. It needs no glob syntax and is the preferred way to edit the fast search boundary. `scopePaths` and `includeGlobs` are alternative scope forms; `excludeGlobs` can remove subtrees from either. A successful scoped result is complete for that requested scope. If the default workspace scan exceeds its bounded file, text, candidate, or time budget, it fails promptly and asks for narrower `scopePaths`; it never hides a second global Provider scan behind the request.

On a cold C/C++ workspace, candidate discovery now runs while the target translation unit is being resolved, and temporary empty Provider results are retried within the request budget. `scopePaths` reduces candidate discovery and verification, but it cannot reduce the language Provider's cost to parse the target itself. Keep the active `compile_commands` current, ensure it contains the target file, and remove entries for deleted files; otherwise cpptools falls back to the broader `includePath` configuration and cold target resolution can dominate the request. The default fast-search budget is 60 seconds. Increase `timeoutMs` only after the target compile command is valid and the translation unit remains intrinsically slow.

`verify_symbol_candidates` remains useful when the caller already has a smaller text/AST candidate set. It resolves the target once and classifies only submitted positions; that tool proves candidate identity, not search completeness.

Most read-tool filters run after the VS Code provider returns; they reduce response size, not Provider enumeration time. `get_references` is the exception only in `auto`/`scoped` C/C++ mode, where `scopePaths` or `includeGlobs` determine candidate discovery before semantic verification. A full-workspace fast result carries `references_fast_workspace_identity_search`; an explicit bounded result carries `references_scoped_identity_search`. Incomplete proof returns an error rather than a partial set.

For an ordinary C/C++ function outline, query the source AST before `document_symbols`; the Provider outline remains the fallback for semantic symbol kinds or nesting that syntax evidence cannot supply. A cold C/C++ `get_call_hierarchy` call retries a transient empty prepare result inside the same bounded request, so the caller should not issue unchanged retries. Once cpptools has parsed the target translation unit, hierarchy expansion reuses that state; keeping the active `compile_commands` complete and current is therefore the main cold-start control.
