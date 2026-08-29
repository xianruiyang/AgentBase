# VS Code LSP MCP

VS Code LSP MCP is an independent local MCP server and VS Code companion extension. It exposes the language providers already active in a VS Code Extension Host, so MCP clients can query symbols, references, hierarchies, diagnostics, previews, and explicitly authorized mutations without reimplementing each language server protocol.

The component does not replace the existing `vscode-mcp` or AST MCP integrations in the parent project. They can be installed and used side by side.

## Delivery status

- Source candidate: `0.2.0`; it is not installed or released by this change.
- Large C/C++ reference queries default to bounded workspace identity search, support path-based scopes, and reserve the slow full Provider for explicit use.
- Current verified release target: Windows x64.
- Runtime requirements: Node.js `>=22.9.0 <27` and VS Code `^1.125.0`.
- Language behavior depends on the language extensions installed and activated in the selected VS Code window.
- MCP stdio is a machine-only JSON channel; logs and diagnostic prose are written elsewhere.

## Start here

- [Install, upgrade, and uninstall](docs/installation.md)
- [Configure VS Code and an MCP client](docs/configuration.md)
- [Tool reference](docs/tools.md)
- [Security model](docs/security.md)
- [Troubleshooting and doctor](docs/troubleshooting.md)
- [Development and release verification](docs/development.md)
- [Dependency and license audit](docs/dependencies.md)

The authoritative per-tool JSON Schemas are advertised through MCP `tools/list` and maintained in `packages/protocol/src/tool-registry.ts`. `MCP_TOOL_SCHEMAS.md` is the checked-in generated schema reference for repository review.

## Architecture

```text
MCP client --stdio--> local server --authenticated local IPC--> VS Code companion
                                                               |
                                                               +--> active VS Code language providers
```

The server uses opaque workspace IDs and logical paths: root-relative paths for single-root workspaces, and `<root-alias>/<relative-path>` for multi-root workspaces. Physical workspace roots, IPC endpoints, and authentication material are not part of MCP responses.

## License and third parties

See `LICENSE`, `NOTICE`, and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The third-party notice file is generated from the exact inputs bundled into the extension, server, and installer.
