# Troubleshooting

Start with the packaged read-only diagnostic:

```powershell
.\install.ps1 doctor --json
```

See [doctor.md](doctor.md) for report states, codes, privacy rules, document-provider probes, and managed log locations.

## No workspace appears

Restart VS Code after installing the VSIX, open a folder or multi-root workspace, and wait for `onStartupFinished`. `NO_REGISTRATIONS` means no trustworthy Extension Host record exists; `NO_WORKSPACE` means the extension activated but the window has no workspace folder.

If doctor reports `REGISTRATION_VERSION_MISMATCH`, the running window and Server are from different releases. Updating files on disk is not enough for an already-open Extension Host: install both artifacts from one release and reload or restart the window. Source-server testing must likewise use the companion built from the same checkout; incompatible registrations are ignored rather than called.

## A language tool is unavailable or empty

Confirm the relevant language extension is installed and active, open the target document once, then call `get_capabilities`. Run doctor with `--workspace-id` and a logical `--file` to probe document-scoped providers. Diagnostics are event-driven: `DIAGNOSTICS_NOT_PUBLISHED` can be a degraded state even when definitions or rename work.

## C++ references repeatedly time out

The default `auto` mode now attempts a bounded full-workspace C/C++ identity search before any global Reference Provider call. It scans standard C/C++ source extensions, ignores comments and literals, and verifies every remaining token against the target definition/declaration identity. A complete workspace result carries `references_fast_workspace_identity_search`. If the project exceeds the file, text, occurrence, time, or identity budget, the call fails promptly instead of silently starting a second global scan.

First retry with a directly editable boundary such as `scopePaths: ["Source/MyModule", "Plugins/MyPlugin/Source"]`; no glob syntax is required, and success is complete for those paths. `includeGlobs` remains the advanced pattern form and cannot be combined with `scopePaths`. Existing text/AST candidates can instead go to `verify_symbol_candidates`, whose completeness remains limited to the caller's search scope. If Provider-owned full enumeration is indispensable, choose `searchMode: "provider"`, set an explicit timeout up to 300,000 ms, and configure the MCP client above that budget (330 seconds is recommended). Provider-mode include/exclude globs filter output only; VS Code's public Reference Provider API has no scope parameter.

For a compile database, verify that every relevant `file` entry still exists at the recorded path. Moved sources can leave a syntactically valid but stale database that silently falls back to broad `includePath` analysis. Regenerate or repair the database, configure `C_Cpp.files.exclude` for build outputs, caches, generated mirrors, and source copies, then reload the window so cpptools rebuilds its navigation state. Raising `vscodeLspMcp.providerTimeoutMs` alone does not repair a stale index.

After a timeout, an immediate reference retry may report the Provider as not ready. This is intentional: VS Code cannot cancel the original public Provider promise, and the companion prevents a second cpptools reference process from being stacked while the first is still finishing. Retry once after cpptools has completed workspace analysis; do not poll continuously.

## Workspace or file is rejected

Refresh `list_workspaces`; registrations change when windows restart. Use the returned opaque `workspaceId`. In a single-root workspace, logical files are root-relative, for example `src/example.ts`, and must not be prefixed with the value shown in `roots`. A multi-root workspace requires `rootAlias/src/example.ts`. Do not use a drive letter or filesystem absolute path.

## Apply reports a missing or stale preview

Create a new preview and review it again. Preview IDs are session-scoped, single-use, expire, and bind to source document versions. Editing a referenced file or restarting the MCP server invalidates the old preview.

## Command or task is denied

Confirm the workspace is trusted and inspect `vscodeLspMcp.commandPolicy`. Standard save/debug/reload commands require `allowStandardCommands`; discovered foreground tasks require `allowWorkspaceTasks`. Custom commands and locked-down task policies require an exact entry. Interactive variables, background/custom tasks, ambiguous task names, UI prompts, and timeouts beyond the effective policy remain denied. Policy changes apply to the next invocation.

## MCP client cannot start the server

Run the stable launcher directly with `--version`, verify Node satisfies the installed manifest, and confirm the client configuration points to the managed install root. MCP clients must launch the server over stdio; redirecting or wrapping stdout with diagnostic text corrupts the protocol.

## A closed MCP client still appears to occupy a bridge connection

Update both the managed Server and VS Code extension, then reload the VS Code window. The Server closes its workspace sessions when the parent stdio stream ends, and the extension admits at most four authenticated or authenticating connections without permanently stopping its accept loop. After an unclean termination, run doctor again; a stale pre-fix process can be stopped once its parent process is confirmed absent.
