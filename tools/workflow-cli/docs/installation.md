# Workflow CLI installation

## Build a local package

From the repository root:

```powershell
& .\tools\workflow-cli\scripts\build-workflow-cli.ps1 -OutputRoot .\tools\workflow-cli\dist
```

The builder creates a versioned ZIP and a SHA-256 sidecar. The ZIP contains
`src/workctl.py`, `src/taskctl.py`, their `.cmd` launchers, `VERSION`,
`manifest.json`, and `assets/templates/*`.

## Install or upgrade

```powershell
& .\tools\workflow-cli\scripts\install-workflow-cli.ps1 Install `
  -Archive .\tools\workflow-cli\dist\workflow-cli-0.1.1.zip
& .\tools\workflow-cli\scripts\install-workflow-cli.ps1 Status
```

The default location is `%LOCALAPPDATA%\Programs\AgentBase\workflow-cli`,
with its `current` directory added once to the user PATH. PATH changes apply
to newly started terminals. `Upgrade` uses staging and restores the previous
current directory, state, and PATH if any step fails. `Uninstall` removes only
files recorded by the installer and leaves unrelated PATH entries and unknown
files alone.

For tests or portable environments, use `-PathBackend File -PathValueFile
<file>` or `-PathBackend None`. `-View Machine` returns complete JSON for
programs; the default model view contains only decision fields and never
includes install paths, hashes, manifest data, or opaque machine identities.

## Workspace compatibility

Task, state, result, immutable source snapshot, and persistent `source-*`
receipt formats remain unchanged. Existing command names, CAS arguments,
and machine-view `--source-snapshot-ref` / `--snapshot-id` inputs remain
supported. Context queries now include stale-result diagnostics; these do
not change task state or rewrite historical results.

Model review receipts now include a random cache-generation alias:
`review-<generation>-<sequence>`. Pass the returned value unchanged. Old
`review-<sequence>` receipts cannot safely identify a cache generation and
must restart final review from the first page. The next first-page query
replaces the legacy rebuildable review cache with `task.review-receipts.v2`;
permanent records are not migrated. When reverting to an older executable,
remove only `.work-cache/taskctl-review-receipts.json` and restart review;
do not delete `snapshots/` or its persistent source receipts.

Model completion output now preserves `evidence_for` and keeps returned
counts, candidate diagnostics, and continuation cursors aligned with the
budgeted page. Model output is not a machine parsing contract; programmatic
consumers must use `--view machine`.

Markdown fenced code no longer creates workflow entries or relation edges.
Ordinary stage documents retain their meaning; workflows that accidentally
depended on example headings or metadata must put their intended entries
outside code blocks. Rebuild the derived index, or let queries rebuild it
in memory. Previously recorded fingerprints affected by the parser correction
may be diagnosed as stale and need evidence review; no task or result is
automatically reset. Index writes now reject document changes during writing
and concurrent managed writes with the existing snapshot/lock gates; retry
after the reported writer or document edits finish.
