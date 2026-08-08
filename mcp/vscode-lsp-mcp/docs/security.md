# Security model

VS Code LSP MCP is a local bridge with three trust boundaries: MCP stdio, an authenticated local IPC channel, and the VS Code Extension Host. Semantic queries are read-only; mutations and execution use explicit runtime gates.

## Enforced boundaries

- MCP stdout contains protocol JSON only. Diagnostic logs and startup failures use files or stderr, never mixed prose on stdout.
- Workspace routing uses opaque public IDs and logical `<root-alias>/<relative-path>` values. Physical roots, IPC endpoints, process IDs, tokens, and nonces are not returned through MCP.
- Logical paths reject absolute paths, traversal, invalid aliases, and unsafe resolution outside the registered root.
- On Windows, Extension Host registrations are protected and verified with native ACL checks. IPC uses authenticated local Named Pipes with bounded handshakes, request sizes, and timeouts.
- Registration and doctor data redact authentication material and physical paths. Doctor is read-only and retains at most five 256 KiB managed JSONL logs.
- Trusted workspaces may run a bounded set of standard save/debug/reload commands and discovered foreground tasks without per-item entries. Custom commands require exact authorization. Free-form shell input, interactive variables, background tasks, and `CustomExecution` are not exposed.
- On Windows, dependency-free process tasks may use a companion-owned tee wrapper. It preserves child arguments and exit status, caps retained failure output at 64 MiB, stores only workspace-logical failure logs below `.vscode-lsp-mcp/task-logs`, and retains at most ten managed logs per root. It never captures unrelated terminals or edits `.gitignore`.
- Rename, code-action, and formatting changes require preview then apply. Apply rejects expired, stale, mismatched, missing, or already-consumed previews.
- Release installation verifies target, versions, archive entries, manifest coverage, and SHA-256 hashes before activation; managed paths reject symlink/junction components.

## Operator responsibilities

- Trust the MCP client, the opened workspace, installed VS Code extensions, and every task declared by a trusted workspace. Authorized commands and tasks run with the user's VS Code privileges.
- Disable `allowStandardCommands` or `allowWorkspaceTasks` where that default is too broad. Keep custom authorization minimal; never authorize commands that can prompt, open interactive UI, accept uncontrolled arguments, or start unbounded background work.
- Review previews before calling apply. A valid preview can still contain semantically undesirable edits from a language provider.
- Treat source text, symbols, diagnostics, and command results as data disclosed to the configured MCP client. Do not use the bridge on a workspace the client is not allowed to inspect.
- Treat retained task logs as potentially sensitive because compiler command lines and output can contain physical paths, environment-derived values, or source excerpts. Ignore `/.vscode-lsp-mcp/` in repositories where these logs must stay local.
- Verify release hashes through the installer and obtain release directories from a trusted distribution channel. SHA-256 detects corruption; it does not establish publisher identity by itself.

## Explicit limitations

- The boundary does not defend against compromise of the same operating-system user, a malicious trusted workspace task, a malicious VS Code extension, a malicious language server, or an explicitly authorized custom command.
- Language providers can be incomplete, delayed, or version-sensitive. A zero-result query is not proof of safety or correctness.
- The current release target is Windows x64. Other platforms have not received equivalent native security and release validation.
- The server is not a network service and has no remote authentication or multi-user isolation model.
- `execute_command` is intentionally non-idempotent. Client retries may repeat an authorized side effect unless the client confirms the prior request failed before execution.

Report security issues privately to the project maintainers. Do not include authentication tokens, IPC endpoints, physical workspace paths, or sensitive source content in a public report.
