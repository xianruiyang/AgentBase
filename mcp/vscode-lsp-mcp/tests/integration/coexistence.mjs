import assert from 'node:assert/strict';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { TOOL_NAMES } from '@simplechat/vscode-lsp-mcp-protocol';
import {
  COMPONENT_ID,
  EXTENSION_ID,
  defaultRoots,
} from '../../scripts/install-core.mjs';

assert.equal(process.platform, 'win32', 'P7-005 coexistence integration currently targets Windows.');

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const vscodeMcpRootInput = process.env.P7_005_VSCODE_MCP_ROOT;
const astMcpRootInput = process.env.P7_005_AST_MCP_ROOT;
assert.ok(
  vscodeMcpRootInput && astMcpRootInput,
  'P7-005 requires P7_005_VSCODE_MCP_ROOT and P7_005_AST_MCP_ROOT; external components are not vendored by this repository.',
);
const vscodeMcpRoot = path.resolve(vscodeMcpRootInput);
const astMcpRoot = path.resolve(astMcpRootInput);
const astMcpWorkspaceRoot = path.resolve(
  process.env.P7_005_AST_MCP_WORKSPACE_ROOT ?? path.dirname(astMcpRoot),
);
const reportPath = process.env.P7_005_COEXIST_REPORT_PATH;
const normalize = (value) => path.resolve(value).toLowerCase();
const isInside = (parent, candidate) => {
  const relative = path.relative(parent, candidate);
  return relative.length === 0 || (!relative.startsWith('..') && !path.isAbsolute(relative));
};
const readJson = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));
const extensionId = (manifest) => `${manifest.publisher}.${manifest.name}`.toLowerCase();
const inheritedEnvironment = Object.fromEntries(
  Object.entries(process.env).filter((entry) => entry[1] !== undefined),
);

const vscodeMcpExtensionManifestPath = path.join(
  vscodeMcpRoot,
  'bridge-extension',
  'yutengjing.vscode-mcp-bridge-4.9.2',
  'package.json',
);
const vscodeMcpInstallPath = path.join(vscodeMcpRoot, 'scripts', 'install-vscode-mcp.ps1');
const vscodeMcpDoctorPath = path.join(vscodeMcpRoot, 'scripts', 'doctor-vscode-mcp.ps1');
const astMcpInstallPath = path.join(astMcpRoot, 'install-codex-mcp.cmd');
const companionExtensionManifestPath = path.join(componentRoot, 'packages', 'extension', 'package.json');
const runtimeDirectorySourcePath = path.join(
  componentRoot,
  'packages',
  'protocol',
  'src',
  'runtime-directory.ts',
);

const [
  vscodeMcpExtensionManifest,
  companionExtensionManifest,
  vscodeMcpInstall,
  vscodeMcpDoctor,
  astMcpInstall,
  runtimeDirectorySource,
] = await Promise.all([
  readJson(vscodeMcpExtensionManifestPath),
  readJson(companionExtensionManifestPath),
  readFile(vscodeMcpInstallPath, 'utf8'),
  readFile(vscodeMcpDoctorPath, 'utf8'),
  readFile(astMcpInstallPath, 'utf8'),
  readFile(runtimeDirectorySourcePath, 'utf8'),
]);

const identities = Object.freeze({
  vscodeMcp: Object.freeze({
    registration: 'vscode-mcp',
    extension: extensionId(vscodeMcpExtensionManifest),
    configurationPrefix: 'vscode-mcp-bridge.',
    endpointPrefix: '\\\\.\\pipe\\vscode-mcp-',
  }),
  simplechatAst: Object.freeze({
    registration: 'simplechat-ast',
    server: 'simplechat-ast-mcp',
    launcher: 'ast-mcp.cmd',
  }),
  vscodeLspMcp: Object.freeze({
    registration: COMPONENT_ID,
    extension: EXTENSION_ID,
    configurationPrefix: 'vscodeLspMcp.',
    endpointPrefix: '\\\\.\\pipe\\vscode-lsp-mcp-',
  }),
});

assert.equal(identities.vscodeMcp.extension, 'yutengjing.vscode-mcp-bridge');
assert.equal(identities.vscodeLspMcp.extension, 'simplechat.vscode-lsp-mcp-companion');
assert.equal(extensionId(companionExtensionManifest), identities.vscodeLspMcp.extension);
assert.match(vscodeMcpInstall, /\[mcp_servers\.vscode-mcp\]/u);
assert.match(astMcpInstall, /set "MCP_NAME=simplechat-ast"/u);
assert.match(vscodeMcpDoctor, /vscode-mcp-\*/u);
assert.match(runtimeDirectorySource, /vscode-lsp-mcp-/u);

const registrationNames = Object.values(identities).map(({ registration }) => registration);
assert.equal(new Set(registrationNames).size, registrationNames.length);
assert.notEqual(identities.vscodeMcp.extension, identities.vscodeLspMcp.extension);
assert.notEqual(
  identities.vscodeMcp.configurationPrefix,
  identities.vscodeLspMcp.configurationPrefix,
);
assert.notEqual(identities.vscodeMcp.endpointPrefix, identities.vscodeLspMcp.endpointPrefix);

const managedRoots = defaultRoots();
for (const managedRoot of Object.values(managedRoots)) {
  assert.equal(isInside(normalize(vscodeMcpRoot), normalize(managedRoot)), false);
  assert.equal(isInside(normalize(astMcpRoot), normalize(managedRoot)), false);
}

const servers = [
  {
    key: 'vscodeMcp',
    command: process.execPath,
    args: [path.join(
      vscodeMcpRoot,
      'server',
      'node_modules',
      '@vscode-mcp',
      'vscode-mcp-server',
      'dist',
      'index.js',
    )],
    cwd: vscodeMcpRoot,
    requiredTools: ['list_workspaces', 'health_check'],
  },
  {
    key: 'simplechatAst',
    command: path.join(astMcpRoot, 'runtime', 'node.exe'),
    args: [path.join(astMcpRoot, 'src', 'server.js')],
    cwd: astMcpRoot,
    environment: { AST_MCP_ROOT: astMcpWorkspaceRoot },
    requiredTools: ['ast_search', 'ast_rewrite_preview', 'ast_validate_change'],
  },
  {
    key: 'vscodeLspMcp',
    command: process.execPath,
    args: [path.join(componentRoot, 'packages', 'server', 'dist', 'cli.js')],
    cwd: componentRoot,
    requiredTools: [...TOOL_NAMES],
  },
];

await Promise.all(servers.flatMap(({ command, args }) => [command, ...args].map((filePath) => access(filePath))));

const sessions = servers.map((definition) => {
  const transport = new StdioClientTransport({
    command: definition.command,
    args: definition.args,
    cwd: definition.cwd,
    env: { ...inheritedEnvironment, ...definition.environment },
    stderr: 'pipe',
  });
  let stderrBytes = 0;
  transport.stderr?.on('data', (chunk) => {
    stderrBytes += Buffer.byteLength(chunk);
    assert.ok(stderrBytes <= 200_000, `${definition.key} stderr exceeded its bound.`);
  });
  return {
    definition,
    transport,
    client: new Client({ name: `p7-005-${definition.key}`, version: '1.0.0' }),
    stderrBytes: () => stderrBytes,
  };
});

let report;
try {
  await Promise.all(sessions.map(({ client, transport }) => client.connect(transport)));
  const listings = await Promise.all(sessions.map(({ client }) => client.listTools()));
  const processEvidence = {};
  for (const [index, session] of sessions.entries()) {
    const listedNames = listings[index].tools.map(({ name }) => name);
    for (const requiredTool of session.definition.requiredTools) {
      assert.ok(listedNames.includes(requiredTool), `${session.definition.key} is missing ${requiredTool}.`);
    }
    processEvidence[session.definition.key] = {
      initialized: true,
      toolCount: listedNames.length,
      requiredToolsPresent: true,
      stderrBytes: session.stderrBytes(),
    };
  }
  assert.equal(processEvidence.vscodeLspMcp.toolCount, 18);

  report = {
    schemaVersion: 1,
    task: 'P7-005',
    status: 'passed',
    simultaneousServers: sessions.length,
    identities,
    isolation: {
      registrationNamesDistinct: true,
      extensionIdsDistinct: true,
      configurationPrefixesDistinct: true,
      endpointPrefixesDistinct: true,
      managedInstallRootsOutsideExistingComponents: true,
    },
    processes: processEvidence,
  };
} finally {
  await Promise.allSettled(sessions.map(({ client }) => client.close()));
}

if (reportPath !== undefined) {
  const resolvedReportPath = path.resolve(reportPath);
  await mkdir(path.dirname(resolvedReportPath), { recursive: true });
  await writeFile(resolvedReportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
}
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
