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
  -Archive .\tools\workflow-cli\dist\workflow-cli-0.1.0.zip
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
