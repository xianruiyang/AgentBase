# Doctor and diagnostic logs

The release installer includes a read-only `doctor` command. It checks the installed package, the VS Code companion extension, workspace registrations, authenticated IPC health, and optional language-provider readiness.

## Run

From an extracted release directory:

```powershell
.\install.ps1 doctor --json
```

```cmd
install.cmd doctor --json
```

```sh
./install.sh doctor --json
```

To probe document-scoped language providers, provide the public workspace ID and a logical workspace path. The logical path uses the same `<root-alias>/<relative-path>` form as MCP tools and is not a physical path.

```powershell
.\install.ps1 doctor --workspace-id <workspace-id> --file root/src/example.ts --json
```

The command completes with exit code 0 when the diagnostic run itself succeeds, even when the report status is `degraded` or `unavailable`. Invocation, unsafe-path, or log-write failures return a nonzero exit code and a structured error with `--json`.

## Report states

- `healthy`: all executed checks passed; skipped document-provider checks do not lower health.
- `degraded`: inspection completed but found warnings such as no workspace, stale registration, unavailable language Provider, or no published diagnostics.
- `unavailable`: an installation, version, security, extension, or IPC check failed.

Important diagnostic codes include:

- Installation: `INSTALL_NOT_FOUND`, `INVALID_INSTALL_STATE`, `TARGET_MISMATCH`, `NODE_VERSION_MISMATCH`, `VERSION_MISMATCH`, `SERVER_VERSION_MISMATCH`.
- VS Code: `EXTENSION_NOT_INSTALLED`, `EXTENSION_VERSION_MISMATCH`, `VSCODE_VERSION_MISMATCH`, `CODE_CLI_NOT_FOUND`, `CODE_CLI_UNSUPPORTED`, `CODE_CLI_FAILED`.
- Registration: `NO_REGISTRATIONS`, `NO_WORKSPACE`, `WORKSPACE_NOT_FOUND`, `INVALID_REGISTRATION`, `REGISTRATION_VERSION_MISMATCH`, `STALE_REGISTRATION`, `REGISTRY_SECURITY_UNAVAILABLE`.
- IPC: `IPC_AUTHENTICATION_FAILED`, `IPC_TIMEOUT`, `IPC_PROTOCOL_FAILURE`, `IPC_DISCONNECTED`, `IPC_REMOTE_FAILURE`.
- Language services: `LANGUAGE_PROVIDER_NOT_READY`, `DIAGNOSTICS_NOT_PUBLISHED`, `DIAGNOSTICS_PROVIDER_NOT_READY`.

`NO_REGISTRATIONS` means no trustworthy Extension Host record exists. `NO_WORKSPACE` is different: the extension activated and explicitly published that no workspace folder is open. An empty Provider result is not treated as proof that a Provider is unavailable; doctor reports the evidence state returned by the extension.

The installed manifest records the Node engine, VS Code compatibility range, server/protocol build version, and bundled MCP SDK version. Doctor checks those records together with the live extension version, registered VS Code version, server `--version`, and IPC protocol version.

## Read-only and privacy boundary

Doctor does not install, upgrade, repair, quarantine, delete, or rewrite registrations and configuration. It authenticates temporary IPC sessions and closes them after each check. Existing stale or invalid registrations are reported but left unchanged.

Reports and logs never include authentication tokens, nonces, IPC endpoints, Extension Host PIDs, or physical workspace roots. Public workspace IDs, workspace names, root aliases, VS Code versions, capability states, and bounded issue codes may be included.

Each run writes a JSON Lines log under the separate configuration root:

```text
<config-root>/logs/doctor-<timestamp>-<pid>.jsonl
```

Each file is limited to 256 KiB, and only five managed doctor logs are retained. `--log-file` may select a filename only inside `<config-root>/logs`; it cannot write elsewhere. Diagnostic logs never use MCP stdout, and normal MCP stdio remains protocol-only.

## Advanced runtime override

`--runtime-root <dir>` inspects an existing alternate runtime registry. Security checks still apply: on Windows every registration file must pass the installed native ACL verifier; on Linux/macOS ownership and mode `0600` are required. The override does not enable an insecure test mode.
