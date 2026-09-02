# AgentBase Workflow CLI

This package provides the Windows `workctl` and `taskctl` command-line
entry points used by the delivery-workflow and task-table-manager skills.

The package is a local runtime, not a release downloader. Build a validated
ZIP with `scripts/build-workflow-cli.ps1`, then install it with
`scripts/install-workflow-cli.ps1`. The installer keeps the machine view
complete for programs and emits a small model view for Codex.

The runtime contains `src/workctl.py`, `src/taskctl.py`, and the six
`assets/templates` files required by `workctl init`.

The runtime requires Python 3 available through `py -3` or `python`.

## Ownership and model surfaces

`tools/workflow-cli` is the only source owner for both commands, their tests,
templates, version, package contract, and installer. The installed `current`
directory is a verified consumer copy and is never used to reconstruct source.

Command handlers compute the complete machine result from workflow Markdown,
task records, and their declared derived indexes. `delivery-workflow` and
`task-table-manager` consume a command-owned model projection that keeps only
the current decision, action, location, and recovery evidence. Model output is
ephemeral and is not a second state source. Persistent `source-*` receipts map
to immutable task source assets; bounded `review-*` receipts live only in a
rebuildable cache. Missing or conflicting receipts are recovered by capturing
the source again or restarting the review query, never by guessing an identity.

The installer state and package manifest are machine-owned lifecycle records.
Use installer `Status` to repair an invalid install; use workflow/task commands
or their formal Markdown/JSON owners to repair command input. Do not edit an
installed copy, generated view, receipt index, or cache to change workflow
semantics.
