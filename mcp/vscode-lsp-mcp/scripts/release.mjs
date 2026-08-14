import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createWriteStream } from 'node:fs';
import {
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { decodeYamlText } from '@simplechat/vscode-lsp-mcp-protocol';
import vsce from '@vscode/vsce';
import { build as esbuild } from 'esbuild';
import yauzl from 'yauzl';
import yazl from 'yazl';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const packagesRoot = path.join(componentRoot, 'packages');
const defaultOutputRoot = path.join(componentRoot, 'dist');
const sourceDateEpoch = 315_532_800;
const fixedArchiveDate = new Date(sourceDateEpoch * 1_000);
const win32SecurityName = '@simplechat/vscode-lsp-mcp-win32-security';
const protocolName = '@simplechat/vscode-lsp-mcp-protocol';
const verifyReproducible = process.argv.includes('--verify-reproducible');
const deliveryDocumentNames = Object.freeze([
  'configuration.md',
  'dependencies.md',
  'development.md',
  'doctor.md',
  'installation.md',
  'security.md',
  'tools.md',
  'troubleshooting.md',
]);
const deliveryRootDocumentNames = Object.freeze([
  'LICENSE',
  'NOTICE',
  'README.md',
  'THIRD_PARTY_NOTICES.md',
]);
const extensionReadme = `# VS Code LSP MCP Companion

This companion extension exposes the language providers active in the current VS Code Extension Host to the independently installed VS Code LSP MCP server.

The packaged documentation is available under the \`docs\` directory:

- \`docs/installation.md\`
- \`docs/configuration.md\`
- \`docs/tools.md\`
- \`docs/security.md\`
- \`docs/troubleshooting.md\`

The extension does not accept free-form shell input. Mutating tools use preview/apply boundaries; trusted workspaces may use bounded standard commands and discovered foreground tasks, while custom commands require explicit \`vscodeLspMcp.commandPolicy\` authorization.
`;

const readJson = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));
const writeJson = (filePath, value) => writeFile(
  filePath,
  `${JSON.stringify(value, null, 2)}\n`,
  'utf8',
);
const normalizeArchivePath = (value) => value.replaceAll('\\', '/');
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

const copyDeliveryDocumentation = async (targetRoot) => {
  const docsRoot = path.join(targetRoot, 'docs');
  await mkdir(docsRoot, { recursive: true });
  await Promise.all([
    ...deliveryRootDocumentNames.map((name) =>
      copyFile(path.join(componentRoot, name), path.join(targetRoot, name))),
    ...deliveryDocumentNames.map((name) =>
      copyFile(path.join(componentRoot, 'docs', name), path.join(docsRoot, name))),
  ]);
};

const copyReleaseRootDocuments = async (targetRoot) => Promise.all(
  deliveryRootDocumentNames.map((name) =>
    copyFile(path.join(componentRoot, name), path.join(targetRoot, name))),
);

const assertSemver = (version) => {
  assert.match(
    version,
    /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/u,
    `Release version is not a supported semantic version: ${version}`,
  );
};

const runNpmScript = (scriptName) => {
  const npmCliPath = process.env.npm_execpath;
  assert.ok(npmCliPath, 'npm_execpath is required; invoke release packaging through npm.');
  const result = spawnSync(process.execPath, [npmCliPath, 'run', scriptName], {
    cwd: componentRoot,
    env: process.env,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `${scriptName} failed with exit code ${result.status}.`);
};

const assertSafeOutputRoot = (candidate) => {
  const resolved = path.resolve(candidate);
  const relative = path.relative(componentRoot, resolved);
  assert.ok(
    resolved === defaultOutputRoot ||
      (relative.length > 0 && !relative.startsWith('..') && !path.isAbsolute(relative)),
    `Release output must stay inside the component root: ${resolved}`,
  );
  return resolved;
};

const loadReleaseConfiguration = async () => {
  const manifestPaths = {
    workspace: path.join(componentRoot, 'package.json'),
    extension: path.join(packagesRoot, 'extension', 'package.json'),
    protocol: path.join(packagesRoot, 'protocol', 'package.json'),
    server: path.join(packagesRoot, 'server', 'package.json'),
    win32Security: path.join(packagesRoot, 'win32-security', 'package.json'),
  };
  const manifests = Object.fromEntries(await Promise.all(Object.entries(manifestPaths).map(
    async ([key, manifestPath]) => [key, await readJson(manifestPath)],
  )));
  const sourceVersion = manifests.workspace.version;
  assertSemver(sourceVersion);
  for (const [key, manifest] of Object.entries(manifests)) {
    assert.equal(
      manifest.version,
      sourceVersion,
      `Source package version mismatch: ${key}=${manifest.version}, workspace=${sourceVersion}.`,
    );
    assert.equal(
      manifest.license,
      manifests.workspace.license,
      `Source package license mismatch: ${key}=${manifest.license}, workspace=${manifests.workspace.license}.`,
    );
    assert.equal(
      manifest.author,
      manifests.workspace.author,
      `Source package author mismatch: ${key}=${manifest.author}, workspace=${manifests.workspace.author}.`,
    );
  }
  for (const [key, manifest] of Object.entries({
    extension: manifests.extension,
    server: manifests.server,
  })) {
    assert.equal(manifest.dependencies[protocolName], sourceVersion, `${key} protocol version mismatch.`);
    assert.equal(
      manifest.dependencies[win32SecurityName],
      sourceVersion,
      `${key} native security version mismatch.`,
    );
  }
  const version = process.env.VSCODE_LSP_MCP_VERSION ?? sourceVersion;
  assertSemver(version);
  assert.equal(process.platform, 'win32', 'P7-001 currently produces the Windows native release target.');
  assert.ok(['x64', 'arm64'].includes(process.arch), `Unsupported Windows architecture: ${process.arch}.`);
  return {
    manifests,
    sourceVersion,
    version,
    target: `win32-${process.arch}`,
  };
};

const listFiles = async (root) => {
  const files = [];
  const visit = async (directory, prefix = '') => {
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      assert.equal(entry.isSymbolicLink(), false, `Release staging cannot contain symlinks: ${entry.name}`);
      const relative = prefix.length === 0 ? entry.name : `${prefix}/${entry.name}`;
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(absolute, relative);
      } else if (entry.isFile()) {
        files.push({ absolute, relative });
      } else {
        throw new Error(`Unsupported release staging entry: ${absolute}`);
      }
    }
  };
  await visit(root);
  return files;
};

const writeDeterministicZip = async ({ sourceRoot, archivePath, archiveRoot }) => {
  const files = await listFiles(sourceRoot);
  await mkdir(path.dirname(archivePath), { recursive: true });
  await new Promise((resolve, reject) => {
    const zip = new yazl.ZipFile();
    for (const file of files) {
      const executable = file.relative.startsWith('bin/');
      zip.addFile(
        file.absolute,
        `${archiveRoot}/${normalizeArchivePath(file.relative)}`,
        {
          mtime: fixedArchiveDate,
          mode: executable ? 0o100755 : 0o100644,
        },
      );
    }
    zip.end();
    const output = createWriteStream(archivePath);
    zip.outputStream.once('error', reject);
    output.once('error', reject);
    output.once('finish', resolve);
    zip.outputStream.pipe(output);
  });
};

const stageNativePackage = async (targetRoot, sourceManifest, version) => {
  const target = path.join(
    targetRoot,
    'node_modules',
    '@simplechat',
    'vscode-lsp-mcp-win32-security',
  );
  const nativeSource = path.join(
    packagesRoot,
    'win32-security',
    'build',
    'Release',
    'win32_security.node',
  );
  const runtimeSource = path.join(packagesRoot, 'win32-security', 'dist', 'index.js');
  await Promise.all([
    mkdir(path.join(target, 'dist'), { recursive: true }),
    mkdir(path.join(target, 'build', 'Release'), { recursive: true }),
  ]);
  await Promise.all([
    copyFile(runtimeSource, path.join(target, 'dist', 'index.js')),
    copyFile(nativeSource, path.join(target, 'build', 'Release', 'win32_security.node')),
    writeJson(path.join(target, 'package.json'), {
      name: win32SecurityName,
      version,
      private: true,
      author: sourceManifest.author,
      license: sourceManifest.license,
      type: 'commonjs',
      main: './dist/index.js',
      exports: {
        '.': {
          import: './dist/index.js',
          require: './dist/index.js',
        },
      },
    }),
  ]);
};

const bundleRuntime = async ({ extensionStage, serverStage }) => {
  await Promise.all([
    mkdir(path.join(extensionStage, 'dist'), { recursive: true }),
    mkdir(path.join(serverStage, 'dist'), { recursive: true }),
  ]);
  await Promise.all([
    esbuild({
      entryPoints: [path.join(packagesRoot, 'extension', 'dist', 'extension.js')],
      outfile: path.join(extensionStage, 'dist', 'extension.js'),
      bundle: true,
      platform: 'node',
      target: 'node22',
      format: 'cjs',
      external: ['vscode', win32SecurityName],
      legalComments: 'none',
      sourcemap: false,
      logLevel: 'warning',
    }),
    esbuild({
      entryPoints: [path.join(packagesRoot, 'server', 'dist', 'cli.js')],
      outfile: path.join(serverStage, 'dist', 'cli.js'),
      bundle: true,
      platform: 'node',
      target: 'node22',
      format: 'esm',
      external: [win32SecurityName],
      banner: {
        js: "import { createRequire as __createReleaseRequire } from 'node:module'; const require = __createReleaseRequire(import.meta.url);",
      },
      legalComments: 'none',
      sourcemap: false,
      logLevel: 'warning',
    }),
  ]);
};

const stageExtension = async ({ stageRoot, configuration }) => {
  const extensionStage = path.join(stageRoot, 'extension');
  const serverStage = path.join(stageRoot, 'server');
  await bundleRuntime({ extensionStage, serverStage });
  await Promise.all([
    stageNativePackage(
      extensionStage,
      configuration.manifests.win32Security,
      configuration.version,
    ),
    stageNativePackage(
      serverStage,
      configuration.manifests.win32Security,
      configuration.version,
    ),
    copyDeliveryDocumentation(extensionStage),
    copyDeliveryDocumentation(serverStage),
  ]);
  await writeFile(path.join(extensionStage, 'README.md'), extensionReadme, 'utf8');

  const extensionManifest = structuredClone(configuration.manifests.extension);
  extensionManifest.version = configuration.version;
  delete extensionManifest.private;
  delete extensionManifest.scripts;
  extensionManifest.dependencies = {
    [win32SecurityName]: configuration.version,
  };
  extensionManifest.files = [
    'dist',
    'node_modules/@simplechat/vscode-lsp-mcp-win32-security',
    'README.md',
    'LICENSE',
    'NOTICE',
    'THIRD_PARTY_NOTICES.md',
    'docs',
  ];
  const versions = {
    extension: configuration.version,
    protocol: configuration.version,
    win32Security: configuration.version,
  };
  await Promise.all([
    writeJson(path.join(extensionStage, 'package.json'), extensionManifest),
    writeJson(path.join(extensionStage, 'dist', 'versions.json'), versions),
  ]);

  const serverManifest = structuredClone(configuration.manifests.server);
  serverManifest.version = configuration.version;
  serverManifest.private = true;
  serverManifest.engines = configuration.manifests.workspace.engines;
  serverManifest.bin = { 'vscode-lsp-mcp': './dist/cli.js' };
  serverManifest.dependencies = {
    [win32SecurityName]: configuration.version,
  };
  delete serverManifest.scripts;
  delete serverManifest.files;
  const binRoot = path.join(serverStage, 'bin');
  await mkdir(binRoot, { recursive: true });
  await Promise.all([
    writeJson(path.join(serverStage, 'package.json'), serverManifest),
    writeJson(path.join(serverStage, 'versions.json'), {
      server: configuration.version,
      protocol: configuration.version,
      win32Security: configuration.version,
    }),
    writeFile(
      path.join(binRoot, 'vscode-lsp-mcp.cmd'),
      '@echo off\r\nnode "%~dp0..\\dist\\cli.js" %*\r\n',
      'utf8',
    ),
  ]);
  return { extensionStage, serverStage };
};

const buildInstallerArtifacts = async (destination) => {
  const installerNodePath = path.join(destination, 'install.mjs');
  await esbuild({
    entryPoints: [path.join(componentRoot, 'scripts', 'install.mjs')],
    outfile: installerNodePath,
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    banner: {
      js: "import { createRequire as __createInstallerRequire } from 'node:module'; const require = __createInstallerRequire(import.meta.url);",
    },
    legalComments: 'none',
    sourcemap: false,
    logLevel: 'warning',
  });
  await Promise.all([
    writeFile(
      path.join(destination, 'install.ps1'),
      "param([Parameter(ValueFromRemainingArguments = $true)][string[]] $InstallerArguments)\r\n$node = (Get-Command node -ErrorAction Stop).Source\r\n& $node (Join-Path $PSScriptRoot 'install.mjs') @InstallerArguments\r\nexit $LASTEXITCODE\r\n",
      'utf8',
    ),
    writeFile(
      path.join(destination, 'install.cmd'),
      '@echo off\r\nnode "%~dp0install.mjs" %*\r\n',
      'utf8',
    ),
  ]);
};

const withSourceDateEpoch = async (action) => {
  const previous = process.env.SOURCE_DATE_EPOCH;
  process.env.SOURCE_DATE_EPOCH = String(sourceDateEpoch);
  try {
    return await action();
  } finally {
    if (previous === undefined) delete process.env.SOURCE_DATE_EPOCH;
    else process.env.SOURCE_DATE_EPOCH = previous;
  }
};

const buildReleasePass = async ({ destination, configuration, passRoot }) => {
  const stageRoot = path.join(passRoot, 'stage');
  await mkdir(destination, { recursive: true });
  const { extensionStage, serverStage } = await stageExtension({ stageRoot, configuration });
  const extensionFile = `vscode-lsp-mcp-companion-${configuration.version}-${configuration.target}.vsix`;
  const serverFile = `vscode-lsp-mcp-server-${configuration.version}-${configuration.target}.zip`;
  const extensionPath = path.join(destination, extensionFile);
  const serverPath = path.join(destination, serverFile);
  const documentationFile = `vscode-lsp-mcp-docs-${configuration.version}.zip`;
  const documentationPath = path.join(destination, documentationFile);
  const documentationStage = path.join(passRoot, 'documentation');
  await Promise.all([
    buildInstallerArtifacts(destination),
    copyReleaseRootDocuments(destination),
  ]);
  await copyDeliveryDocumentation(documentationStage);
  await withSourceDateEpoch(() => vsce.createVSIX({
    cwd: extensionStage,
    packagePath: extensionPath,
    target: configuration.target,
    useYarn: false,
    dependencies: true,
    allowMissingRepository: true,
    allowUnusedFilesPattern: true,
    skipLicense: false,
    updatePackageJson: false,
  }));
  await writeDeterministicZip({
    sourceRoot: serverStage,
    archivePath: serverPath,
    archiveRoot: 'vscode-lsp-mcp-server',
  });
  await writeDeterministicZip({
    sourceRoot: documentationStage,
    archivePath: documentationPath,
    archiveRoot: 'vscode-lsp-mcp-docs',
  });
  const artifactRecords = await Promise.all([
    ['extension-vsix', extensionFile, extensionPath],
    ['server-zip', serverFile, serverPath],
    ['delivery-docs', documentationFile, documentationPath],
    ['license', 'LICENSE', path.join(destination, 'LICENSE')],
    ['notice', 'NOTICE', path.join(destination, 'NOTICE')],
    ['delivery-readme', 'README.md', path.join(destination, 'README.md')],
    ['third-party-notices', 'THIRD_PARTY_NOTICES.md', path.join(destination, 'THIRD_PARTY_NOTICES.md')],
    ['installer-node', 'install.mjs', path.join(destination, 'install.mjs')],
    ['installer-powershell', 'install.ps1', path.join(destination, 'install.ps1')],
    ['installer-cmd', 'install.cmd', path.join(destination, 'install.cmd')],
  ].map(async ([type, name, filePath]) => {
    const bytes = await readFile(filePath);
    return { type, name, bytes: bytes.length, sha256: sha256(bytes) };
  }));
  artifactRecords.sort((left, right) => left.name.localeCompare(right.name));
  const manifest = {
    schemaVersion: 1,
    component: 'vscode-lsp-mcp',
    version: configuration.version,
    sourceVersion: configuration.sourceVersion,
    target: configuration.target,
    nodeEngine: configuration.manifests.workspace.engines.node,
    vscodeEngine: configuration.manifests.extension.engines.vscode,
    mcpSdkVersion: configuration.manifests.server.dependencies['@modelcontextprotocol/sdk'],
    author: configuration.manifests.workspace.author,
    license: configuration.manifests.workspace.license,
    sourceDateEpoch,
    packages: {
      extension: configuration.version,
      protocol: configuration.version,
      server: configuration.version,
      win32Security: configuration.version,
    },
    entryPoints: {
      extension: 'extension/dist/extension.js',
      serverWindows: 'vscode-lsp-mcp-server/bin/vscode-lsp-mcp.cmd',
      installerNode: 'install.mjs',
      installerWindows: 'install.ps1',
      installerWindowsCmd: 'install.cmd',
      documentation: `vscode-lsp-mcp-docs/README.md`,
      license: 'LICENSE',
      notice: 'NOTICE',
    },
    artifacts: artifactRecords,
  };
  const manifestPath = path.join(destination, 'release-manifest.json');
  await writeJson(manifestPath, manifest);
  await writeFile(
    path.join(destination, 'checksums.sha256'),
    `${artifactRecords.map((record) => `${record.sha256}  ${record.name}`).join('\n')}\n`,
    'utf8',
  );
  return manifest;
};

const readZip = async (archivePath, selectedNames = new Set()) => {
  const archiveBuffer = await readFile(archivePath);
  const zip = await new Promise((resolve, reject) => {
    yauzl.fromBuffer(archiveBuffer, { lazyEntries: true }, (error, opened) => {
      if (error) reject(error);
      else resolve(opened);
    });
  });
  const names = [];
  const selected = new Map();
  await new Promise((resolve, reject) => {
    zip.once('error', reject);
    zip.once('end', resolve);
    zip.on('entry', (entry) => {
      const name = normalizeArchivePath(entry.fileName);
      names.push(name);
      if (!selectedNames.has(name) || name.endsWith('/')) {
        zip.readEntry();
        return;
      }
      zip.openReadStream(entry, (error, stream) => {
        if (error) {
          reject(error);
          return;
        }
        const chunks = [];
        stream.on('data', (chunk) => chunks.push(chunk));
        stream.once('error', reject);
        stream.once('end', () => {
          selected.set(name, Buffer.concat(chunks));
          zip.readEntry();
        });
      });
    });
    zip.readEntry();
  });
  return { names, selected };
};

const extractZip = async (archivePath, destination) => {
  const archiveBuffer = await readFile(archivePath);
  const zip = await new Promise((resolve, reject) => {
    yauzl.fromBuffer(archiveBuffer, { lazyEntries: true }, (error, opened) => {
      if (error) reject(error);
      else resolve(opened);
    });
  });
  await mkdir(destination, { recursive: true });
  await new Promise((resolve, reject) => {
    zip.once('error', reject);
    zip.once('end', resolve);
    zip.on('entry', (entry) => {
      const name = normalizeArchivePath(entry.fileName);
      const segments = name.split('/').filter((segment) => segment.length > 0);
      if (segments.some((segment) => segment === '..') || path.isAbsolute(name)) {
        reject(new Error(`Unsafe archive entry: ${name}`));
        return;
      }
      const target = path.join(destination, ...segments);
      if (name.endsWith('/')) {
        mkdir(target, { recursive: true }).then(() => zip.readEntry(), reject);
        return;
      }
      zip.openReadStream(entry, (error, stream) => {
        if (error) {
          reject(error);
          return;
        }
        const chunks = [];
        stream.on('data', (chunk) => chunks.push(chunk));
        stream.once('error', reject);
        stream.once('end', () => {
          mkdir(path.dirname(target), { recursive: true })
            .then(() => writeFile(target, Buffer.concat(chunks)))
            .then(() => zip.readEntry(), reject);
        });
      });
    });
    zip.readEntry();
  });
};

const assertCleanArchiveEntries = (names) => {
  const forbidden = names.filter((name) =>
    /(?:^|\/)(?:src|test|tests)(?:\/|$)|\.test\.|\.map$|\.d\.ts$|tsconfig\.tsbuildinfo$/u.test(name));
  assert.deepEqual(forbidden, [], `Release archive contains development files: ${forbidden.join(', ')}`);
};

const validateRelease = async ({ destination, manifest, verificationRoot }) => {
  const extensionRecord = manifest.artifacts.find(({ type }) => type === 'extension-vsix');
  const serverRecord = manifest.artifacts.find(({ type }) => type === 'server-zip');
  const documentationRecord = manifest.artifacts.find(({ type }) => type === 'delivery-docs');
  assert.ok(extensionRecord);
  assert.ok(serverRecord);
  assert.ok(documentationRecord);
  for (const [type, name] of [
    ['license', 'LICENSE'],
    ['notice', 'NOTICE'],
    ['delivery-readme', 'README.md'],
    ['third-party-notices', 'THIRD_PARTY_NOTICES.md'],
  ]) {
    const record = manifest.artifacts.find((artifact) => artifact.type === type);
    assert.equal(record?.name, name, `Release is missing ${type}.`);
    assert.deepEqual(
      await readFile(path.join(destination, name)),
      await readFile(path.join(componentRoot, name)),
      `Release root ${name} differs from source.`,
    );
  }
  const nativeRelative = 'node_modules/@simplechat/vscode-lsp-mcp-win32-security/build/Release/win32_security.node';
  const extensionSelections = new Set([
    'extension/package.json',
    'extension/dist/extension.js',
    'extension/dist/versions.json',
    'extension/readme.md',
    'extension/LICENSE.txt',
    'extension/NOTICE',
    'extension/THIRD_PARTY_NOTICES.md',
    'extension/docs/security.md',
  ]);
  const extensionZip = await readZip(path.join(destination, extensionRecord.name), extensionSelections);
  assertCleanArchiveEntries(extensionZip.names);
  for (const required of [
    '[Content_Types].xml',
    'extension.vsixmanifest',
    'extension/package.json',
    'extension/dist/extension.js',
    'extension/readme.md',
    'extension/LICENSE.txt',
    'extension/NOTICE',
    'extension/THIRD_PARTY_NOTICES.md',
    'extension/docs/security.md',
    `extension/${nativeRelative}`,
  ]) {
    assert.ok(extensionZip.names.includes(required), `VSIX is missing ${required}.`);
  }
  const extensionManifest = JSON.parse(extensionZip.selected.get('extension/package.json').toString('utf8'));
  const extensionVersions = JSON.parse(extensionZip.selected.get('extension/dist/versions.json').toString('utf8'));
  assert.equal(extensionManifest.version, manifest.version);
  assert.equal(extensionManifest.author, manifest.author);
  assert.equal(extensionManifest.license, manifest.license);
  assert.deepEqual(new Set(Object.values(extensionVersions)), new Set([manifest.version]));

  const serverSelections = new Set([
    'vscode-lsp-mcp-server/package.json',
    'vscode-lsp-mcp-server/versions.json',
    'vscode-lsp-mcp-server/dist/cli.js',
    'vscode-lsp-mcp-server/README.md',
    'vscode-lsp-mcp-server/LICENSE',
    'vscode-lsp-mcp-server/NOTICE',
    'vscode-lsp-mcp-server/THIRD_PARTY_NOTICES.md',
    'vscode-lsp-mcp-server/docs/security.md',
  ]);
  const serverZip = await readZip(path.join(destination, serverRecord.name), serverSelections);
  assertCleanArchiveEntries(serverZip.names);
  for (const required of [
    'vscode-lsp-mcp-server/package.json',
    'vscode-lsp-mcp-server/versions.json',
    'vscode-lsp-mcp-server/dist/cli.js',
    'vscode-lsp-mcp-server/README.md',
    'vscode-lsp-mcp-server/LICENSE',
    'vscode-lsp-mcp-server/NOTICE',
    'vscode-lsp-mcp-server/THIRD_PARTY_NOTICES.md',
    'vscode-lsp-mcp-server/docs/security.md',
    'vscode-lsp-mcp-server/bin/vscode-lsp-mcp.cmd',
    `vscode-lsp-mcp-server/${nativeRelative}`,
  ]) {
    assert.ok(serverZip.names.includes(required), `Server archive is missing ${required}.`);
  }
  const serverManifest = JSON.parse(serverZip.selected.get('vscode-lsp-mcp-server/package.json').toString('utf8'));
  const serverVersions = JSON.parse(serverZip.selected.get('vscode-lsp-mcp-server/versions.json').toString('utf8'));
  assert.equal(serverManifest.version, manifest.version);
  assert.equal(serverManifest.author, manifest.author);
  assert.equal(serverManifest.license, manifest.license);
  assert.deepEqual(new Set(Object.values(serverVersions)), new Set([manifest.version]));

  const documentationSelections = new Set([
    'vscode-lsp-mcp-docs/README.md',
    'vscode-lsp-mcp-docs/LICENSE',
    'vscode-lsp-mcp-docs/NOTICE',
    'vscode-lsp-mcp-docs/THIRD_PARTY_NOTICES.md',
    'vscode-lsp-mcp-docs/docs/installation.md',
    'vscode-lsp-mcp-docs/docs/tools.md',
    'vscode-lsp-mcp-docs/docs/security.md',
  ]);
  const documentationZip = await readZip(
    path.join(destination, documentationRecord.name),
    documentationSelections,
  );
  assertCleanArchiveEntries(documentationZip.names);
  for (const required of documentationSelections) {
    assert.ok(documentationZip.names.includes(required), `Documentation archive is missing ${required}.`);
    assert.ok(documentationZip.selected.get(required).length > 0, `${required} is empty.`);
  }

  const rootNeedle = normalizeArchivePath(componentRoot).toLowerCase();
  for (const bytes of [
    extensionZip.selected.get('extension/dist/extension.js'),
    serverZip.selected.get('vscode-lsp-mcp-server/dist/cli.js'),
    await readFile(path.join(destination, 'install.mjs')),
    ...documentationZip.selected.values(),
  ]) {
    assert.equal(bytes.toString('utf8').toLowerCase().includes(rootNeedle), false, 'Bundle leaked build path.');
  }

  const extractRoot = path.join(verificationRoot, 'extracted');
  await extractZip(path.join(destination, serverRecord.name), extractRoot);
  const serverRoot = path.join(extractRoot, 'vscode-lsp-mcp-server');
  const versionProbe = spawnSync(process.execPath, [path.join(serverRoot, 'dist', 'cli.js'), '--version'], {
    cwd: serverRoot,
    encoding: 'utf8',
    windowsHide: true,
  });
  assert.equal(versionProbe.status, 0, versionProbe.stderr);
  assert.equal(versionProbe.stdout.trim(), manifest.version);
  const nativeProbe = spawnSync(process.execPath, [
    '-e',
    `const api=require(${JSON.stringify(path.join(serverRoot, 'node_modules', '@simplechat', 'vscode-lsp-mcp-win32-security', 'dist', 'index.js'))});process.stdout.write(JSON.stringify(api.getNativeBuildInfo()));`,
  ], {
    cwd: serverRoot,
    encoding: 'utf8',
    windowsHide: true,
  });
  assert.equal(nativeProbe.status, 0, nativeProbe.stderr);
  const nativeInfo = JSON.parse(nativeProbe.stdout);
  assert.equal(nativeInfo.abi, 'node-api');
  assert.equal(nativeInfo.targetArch, process.arch);
  assert.equal(nativeInfo.securityOperationsImplemented, true);
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(serverRoot, 'dist', 'cli.js')],
    cwd: serverRoot,
    stderr: 'pipe',
  });
  const client = new Client({ name: 'p7-001-release-smoke', version: manifest.version });
  let tools;
  let health;
  try {
    await client.connect(transport);
    tools = await client.listTools();
    health = await client.callTool({ name: 'health_check', arguments: {} });
  } finally {
    await client.close().catch(() => undefined);
  }
  assert.equal(tools.tools.length, 18);
  assert.equal(new Set(tools.tools.map(({ name }) => name)).size, 18);
  assert.equal(health.isError, undefined);
  assert.equal(health.structuredContent, undefined);
  assert.equal(health.content.length, 1);
  assert.equal(health.content[0]?.type, 'text');
  const healthResponse = decodeYamlText(health.content[0].text);
  assert.equal(healthResponse.ok, true);
  for (const type of ['installer-node', 'installer-powershell', 'installer-cmd']) {
    assert.ok(manifest.artifacts.some((artifact) => artifact.type === type), `Release is missing ${type}.`);
  }
  const installerProbe = spawnSync(process.execPath, [path.join(destination, 'install.mjs'), '--help'], {
    cwd: destination,
    encoding: 'utf8',
    windowsHide: true,
  });
  assert.equal(installerProbe.status, 0, installerProbe.stderr);
  assert.match(installerProbe.stdout, /vscode-lsp-mcp installer/u);
  const doctorRoot = path.join(verificationRoot, 'doctor');
  const doctorProbe = spawnSync(process.execPath, [
    path.join(destination, 'install.mjs'),
    'doctor',
    '--install-root',
    path.join(doctorRoot, 'install'),
    '--config-root',
    path.join(doctorRoot, 'config'),
    '--runtime-root',
    path.join(doctorRoot, 'runtime'),
    '--json',
  ], {
    cwd: destination,
    encoding: 'utf8',
    windowsHide: true,
  });
  assert.equal(doctorProbe.status, 0, doctorProbe.stderr);
  assert.equal(doctorProbe.stderr, '');
  assert.equal(doctorProbe.stdout.trim().split(/\r?\n/u).length, 1);
  const doctor = JSON.parse(doctorProbe.stdout);
  assert.equal(doctor.kind, 'doctor');
  assert.equal(doctor.installation.state, 'notInstalled');
  assert.equal(doctor.checks.some(({ code }) => code === 'INSTALL_NOT_FOUND'), true);
  assert.equal((await readFile(doctor.log.path, 'utf8')).includes(componentRoot), false);
  return {
    extensionEntries: extensionZip.names.length,
    serverEntries: serverZip.names.length,
    documentationEntries: documentationZip.names.length,
    serverVersion: versionProbe.stdout.trim(),
    native: nativeInfo,
    stdio: {
      tools: tools.tools.length,
      healthOk: healthResponse.ok,
    },
    installerHelp: true,
    doctorStatic: true,
  };
};

const compareDirectories = async (leftRoot, rightRoot) => {
  const [leftFiles, rightFiles] = await Promise.all([listFiles(leftRoot), listFiles(rightRoot)]);
  assert.deepEqual(
    leftFiles.map(({ relative }) => relative),
    rightFiles.map(({ relative }) => relative),
    'Release passes produced different file sets.',
  );
  const hashes = {};
  for (let index = 0; index < leftFiles.length; index += 1) {
    const [leftBytes, rightBytes] = await Promise.all([
      readFile(leftFiles[index].absolute),
      readFile(rightFiles[index].absolute),
    ]);
    assert.deepEqual(rightBytes, leftBytes, `Release output is not reproducible: ${leftFiles[index].relative}`);
    hashes[leftFiles[index].relative] = sha256(leftBytes);
  }
  return hashes;
};

const main = async () => {
  const configuration = await loadReleaseConfiguration();
  const outputRoot = assertSafeOutputRoot(process.env.VSCODE_LSP_MCP_OUTPUT_DIR ?? defaultOutputRoot);
  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-release-'));
  try {
    runNpmScript('build');
    const firstOutput = path.join(temporaryRoot, 'pass-1', 'output');
    const firstManifest = await buildReleasePass({
      destination: firstOutput,
      configuration,
      passRoot: path.join(temporaryRoot, 'pass-1'),
    });
    let reproducibleHashes;
    if (verifyReproducible) {
      runNpmScript('build');
      const secondOutput = path.join(temporaryRoot, 'pass-2', 'output');
      await buildReleasePass({
        destination: secondOutput,
        configuration,
        passRoot: path.join(temporaryRoot, 'pass-2'),
      });
      reproducibleHashes = await compareDirectories(firstOutput, secondOutput);
    }
    const validation = await validateRelease({
      destination: firstOutput,
      manifest: firstManifest,
      verificationRoot: path.join(temporaryRoot, 'verification'),
    });
    await rm(outputRoot, { recursive: true, force: true });
    await mkdir(outputRoot, { recursive: true });
    for (const file of await listFiles(firstOutput)) {
      const target = path.join(outputRoot, file.relative);
      await mkdir(path.dirname(target), { recursive: true });
      await copyFile(file.absolute, target);
    }
    const report = {
      schemaVersion: 1,
      version: configuration.version,
      sourceVersion: configuration.sourceVersion,
      target: configuration.target,
      outputRoot: normalizeArchivePath(path.relative(componentRoot, outputRoot)),
      reproducible: verifyReproducible,
      ...(reproducibleHashes === undefined ? {} : { reproducibleHashes }),
      validation,
      artifacts: firstManifest.artifacts,
    };
    if (process.env.VSCODE_LSP_MCP_REPORT_PATH !== undefined) {
      const reportPath = path.resolve(process.env.VSCODE_LSP_MCP_REPORT_PATH);
      await mkdir(path.dirname(reportPath), { recursive: true });
      await writeJson(reportPath, report);
    }
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
};

await main();
