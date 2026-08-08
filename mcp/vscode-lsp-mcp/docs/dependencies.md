# Dependency, license, and vulnerability audit

The release dependency audit is based on exact esbuild input graphs, not only `package.json`. This matters because the standalone installer bundles packages such as `yauzl` even though they are development dependencies in the source workspace.

As of the P7-004 delivery audit, the extension, server, and installer bundle 12 external packages: 9 MIT, 2 ISC, and 1 BSD-3-Clause. All 12 have non-empty upstream license text in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), and none use an unreviewed or copyleft license expression.

The inventory includes the MCP SDK, Ajv and its runtime helpers, YAML, Zod and its schema adapter, and the installer ZIP reader stack. Run `npm run dependency:audit` for the authoritative package/version/artifact mapping and notice hash.

On 2026-07-15, both `npm audit --omit=dev --json` and full-workspace `npm audit --json` reported zero low, moderate, high, or critical vulnerabilities after upgrading esbuild from 0.28.0 to 0.28.1. Registry audit results are time-sensitive; release candidates must rerun both commands and retain the JSON evidence.

The dependency licenses are permissive and compatible with the component's Apache-2.0 license. The project license text, copyright attribution, and all bundled third-party license texts are included in every distributable package. This is an engineering compatibility conclusion, not legal advice.
