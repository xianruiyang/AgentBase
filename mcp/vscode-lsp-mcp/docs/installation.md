# Installation, upgrade, and removal

## Supported release

The currently verified binary release is `win32-x64`. The installer includes POSIX entry scripts for lifecycle testing and future targets, but Linux, macOS, and Windows ARM64 are not release-signoff targets yet.

A fresh Windows machine needs:

- 64-bit Windows;
- Node.js `>=22.9.0 <27` available as `node`;
- VS Code `^1.125.0` with its CLI available as `code`, or supplied with `--code-cli`;
- the complete extracted release directory, including `release-manifest.json`, `checksums.sha256`, the VSIX, server archive, and installer files.

Install the language extensions needed by the workspace before testing language-specific tools. This component neither installs nor upgrades language extensions.

## Install from an extracted release

Open PowerShell in the extracted release directory:

```powershell
.\install.ps1 install --json
```

The installer verifies the release target, Node/VS Code version ranges, manifest entries, SHA-256 hashes, archive safety, and staged server version before atomically switching the managed installation. It then installs the companion VSIX unless `--skip-extension` is specified.

Restart VS Code, open the intended workspace, and run:

```powershell
.\install.ps1 status --json
.\install.ps1 doctor --json
```

`status` verifies managed installation state. `doctor` also checks live extension registrations, authenticated IPC, and optional language providers. See [doctor.md](doctor.md).

## Default managed locations

On Windows, program files are under `%LOCALAPPDATA%\SimpleChat\vscode-lsp-mcp` and configuration is under `%APPDATA%\SimpleChat\vscode-lsp-mcp`. The roots are deliberately separate so uninstall and upgrade can preserve user configuration.

Use `--install-root`, `--config-root`, `--extensions-dir`, or `--user-data-dir` for an isolated deployment. Pass the same overrides to later status, doctor, backup, restore, and uninstall commands.

## Upgrade and rollback safety

Run `install` from the new complete release directory. Installation is staged and validated before activation. If extension installation or activation fails, the installer restores the prior managed version and extension when possible. Do not mix files from different release directories.

Back up the managed configuration before a policy migration:

```powershell
.\install.ps1 backup-config --output .\vscode-lsp-mcp-config-backup.json --json
```

Restore it with:

```powershell
.\install.ps1 restore-config --input .\vscode-lsp-mcp-config-backup.json --json
```

The installed `config.json` is currently a reserved lifecycle boundary. Runtime command and task authorization is controlled by the VS Code setting described in [configuration.md](configuration.md); editing the installed file does not change the live policy.

## Uninstall

From a compatible extracted release directory:

```powershell
.\install.ps1 uninstall --json
```

This removes managed program files and the companion extension while preserving configuration. To explicitly remove `config.json` too:

```powershell
.\install.ps1 uninstall --remove-config --json
```

Remove the MCP client entry separately, for example `codex mcp remove vscode-lsp-mcp`. Close or restart the MCP client and VS Code after removal.
