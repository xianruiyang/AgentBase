# Development and release verification

## Prerequisites

- Node.js `>=22.9.0 <27` and npm 11;
- VS Code compatible with `^1.125.0`;
- on Windows, Visual Studio 2022 C++ build tools and Python for `node-gyp`;
- language extensions required by any manual multi-language checks.

Install the exact lockfile and build all workspaces:

```powershell
npm ci
npm run build
```

The workspace contains shared protocol/schema code, the VS Code extension, the stdio MCP server, and a Windows native registration/ACL verifier. Keep MCP stdout protocol-only and keep public path values logical rather than physical.

## Focused checks

```powershell
npm run typecheck
npm run lint
npm test
npm run dependency:audit
```

`dependency:audit` reconstructs the exact esbuild input graphs for the extension, server, and installer, verifies every bundled external package has reviewed permissive license metadata and upstream license text, and checks that `THIRD_PARTY_NOTICES.md` is current. Regenerate after a dependency or bundle change:

```powershell
npm run dependency:audit:write
```

Run npm's registry vulnerability checks separately because they are time-sensitive:

```powershell
npm audit --omit=dev
npm audit
```

## Integration and release

The complete verification runner builds, checks, tests, packages, validates install/doctor lifecycles, and runs the available VS Code Extension Host suites:

```powershell
npm run verify
```

Build a deterministic Windows release:

```powershell
npm run release:build
npm run release:verify
```

Release verification builds twice and compares every output hash. It also rejects undeclared files, unsafe archive paths, manifest/hash mismatches, version drift, extension/server smoke failures, and installation lifecycle failures. The current release implementation requires Windows and produces the current process architecture target; only Windows x64 has formal signoff.

The manual installed-language matrix is intentionally separate because results depend on machine extensions:

```powershell
npm run test:manual:multilanguage
```

Do not interpret missing diagnostics as a universal language failure. Record the exact VS Code and language-extension versions when using manual results for release decisions.
