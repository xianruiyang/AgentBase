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

The normal developer verifier is the deterministic static and unit gate. It checks workspace structure, types, lint, unit tests, documentation, and bundled dependency/license metadata; it does not package or launch VS Code:

```powershell
npm run verify
```

The complete Windows x64 release gate builds twice for reproducibility, validates Stage B/C plus install and doctor lifecycles, and runs the supported VS Code Extension Host suites:

```powershell
npm run verify:release
```

Build a deterministic Windows release:

```powershell
npm run release:build
npm run release:verify
```

`release:verify` is the reproducible package sub-gate: it builds twice and compares every output hash, then rejects undeclared files, unsafe archive paths, manifest/hash mismatches, version drift, and extension/server smoke failures. `verify:release` owns the broader install, doctor, and Extension Host lifecycle contract. The current release implementation requires Windows and produces the current process architecture target; only Windows x64 has formal signoff.

The manual installed-language matrix is intentionally separate because results depend on machine extensions:

```powershell
npm run test:manual:multilanguage
```

Do not interpret missing diagnostics as a universal language failure. Record the exact VS Code and language-extension versions when using manual results for release decisions.
