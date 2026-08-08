import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build as esbuild } from 'esbuild';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const packagesRoot = path.join(componentRoot, 'packages');
const noticesPath = path.join(componentRoot, 'THIRD_PARTY_NOTICES.md');
const reportPath = process.env.VSCODE_LSP_MCP_DEPENDENCY_REPORT;
const shouldWrite = process.argv.includes('--write');
const shouldCheck = process.argv.includes('--check');
const internalPackagePrefix = '@simplechat/';
const win32SecurityName = '@simplechat/vscode-lsp-mcp-win32-security';
const acceptedLicenses = new Set([
  '0BSD',
  'Apache-2.0',
  'BSD-2-Clause',
  'BSD-3-Clause',
  'CC0-1.0',
  'ISC',
  'MIT',
]);

const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const fileExists = async (filePath) => {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
};

const readJson = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));

const bundleInputs = async () => {
  const common = {
    bundle: true,
    platform: 'node',
    target: 'node22',
    legalComments: 'none',
    sourcemap: false,
    logLevel: 'silent',
    metafile: true,
    write: false,
  };
  const definitions = [
    {
      artifact: 'extension-vsix',
      options: {
        ...common,
        entryPoints: [path.join(packagesRoot, 'extension', 'dist', 'extension.js')],
        format: 'cjs',
        external: ['vscode', win32SecurityName],
      },
    },
    {
      artifact: 'server-zip',
      options: {
        ...common,
        entryPoints: [path.join(packagesRoot, 'server', 'dist', 'cli.js')],
        format: 'esm',
        external: [win32SecurityName],
      },
    },
    {
      artifact: 'installer',
      options: {
        ...common,
        entryPoints: [path.join(componentRoot, 'scripts', 'install.mjs')],
        format: 'esm',
      },
    },
  ];
  const inputs = [];
  for (const definition of definitions) {
    const result = await esbuild(definition.options);
    for (const input of Object.keys(result.metafile.inputs)) {
      inputs.push({ artifact: definition.artifact, input });
    }
  }
  return inputs;
};

const findPackage = async (input) => {
  let current = path.dirname(path.isAbsolute(input) ? input : path.resolve(componentRoot, input));
  const root = path.parse(current).root;
  while (current !== root) {
    const manifestPath = path.join(current, 'package.json');
    if (await fileExists(manifestPath)) {
      const manifest = await readJson(manifestPath);
      if (typeof manifest.name === 'string' && manifest.name.length > 0) {
        return { manifest, packageRoot: current };
      }
    }
    current = path.dirname(current);
  }
  return undefined;
};

const normalizeLicense = (license) => {
  if (typeof license === 'string') return license;
  if (license && typeof license.type === 'string') return license.type;
  return 'UNKNOWN';
};

const findLicenseFile = async (packageRoot) => {
  const entries = await readdir(packageRoot, { withFileTypes: true });
  const candidates = entries
    .filter((entry) => entry.isFile())
    .map((entry) => entry.name)
    .filter((name) => /^(?:licen[cs]e|copying|notice)(?:\..+)?$/iu.test(name))
    .sort((left, right) => left.localeCompare(right));
  for (const candidate of candidates) {
    const content = (await readFile(path.join(packageRoot, candidate), 'utf8')).trim();
    if (content.length > 0) return { name: candidate, content };
  }
  return undefined;
};

const collectPackages = async () => {
  const records = new Map();
  for (const entry of await bundleInputs()) {
    const located = await findPackage(entry.input);
    if (!located) continue;
    const { manifest, packageRoot } = located;
    const workspaceRelative = path.relative(packagesRoot, packageRoot);
    const isWorkspacePackage = workspaceRelative === '' ||
      (workspaceRelative.length > 0 && !workspaceRelative.startsWith('..') && !path.isAbsolute(workspaceRelative));
    if (isWorkspacePackage || manifest.name.startsWith(internalPackagePrefix)) continue;
    if (manifest.name === '@simplechat/vscode-lsp-mcp-workspace') continue;
    const key = `${manifest.name}@${manifest.version}`;
    let record = records.get(key);
    if (!record) {
      const licenseFile = await findLicenseFile(packageRoot);
      record = {
        name: manifest.name,
        version: String(manifest.version ?? 'UNKNOWN'),
        license: normalizeLicense(manifest.license),
        licenseFile: licenseFile?.name ?? null,
        licenseText: licenseFile?.content ?? null,
        artifacts: new Set(),
      };
      records.set(key, record);
    }
    record.artifacts.add(entry.artifact);
  }
  return [...records.values()]
    .map((record) => ({ ...record, artifacts: [...record.artifacts].sort() }))
    .sort((left, right) => left.name.localeCompare(right.name) || left.version.localeCompare(right.version));
};

const renderNotices = (packages) => {
  const sections = [
    '# Third-Party Notices',
    '',
    'This product bundles the third-party packages listed below. The package name, version, SPDX license expression, release artifact, and upstream license text were derived from the exact esbuild input graph used by the release pipeline.',
    '',
  ];
  for (const dependency of packages) {
    sections.push(
      `## ${dependency.name} ${dependency.version}`,
      '',
      `License: ${dependency.license}`,
      '',
      `Bundled in: ${dependency.artifacts.join(', ')}`,
      '',
      dependency.licenseText,
      '',
    );
  }
  return `${sections.join('\n').trimEnd()}\n`;
};

const packages = await collectPackages();
const missingLicenseText = packages.filter((dependency) => !dependency.licenseText);
const unapprovedLicenses = packages.filter((dependency) => !acceptedLicenses.has(dependency.license));
assert.equal(missingLicenseText.length, 0, `Missing license text: ${missingLicenseText.map(({ name }) => name).join(', ')}`);
assert.equal(unapprovedLicenses.length, 0, `Unreviewed licenses: ${unapprovedLicenses.map(({ name, license }) => `${name} (${license})`).join(', ')}`);

const notices = renderNotices(packages);
const report = {
  schemaVersion: 1,
  method: 'exact-esbuild-release-input-graph',
  acceptedLicenseIds: [...acceptedLicenses].sort(),
  packageCount: packages.length,
  licenses: Object.fromEntries([...new Set(packages.map(({ license }) => license))].sort().map(
    (license) => [license, packages.filter((dependency) => dependency.license === license).length],
  )),
  packages: packages.map(({ licenseText, ...dependency }) => ({
    ...dependency,
    licenseTextSha256: sha256(licenseText),
  })),
  noticesSha256: sha256(notices),
  conclusions: {
    missingLicenseTexts: 0,
    unreviewedLicenseExpressions: 0,
  },
};

if (shouldWrite) await writeFile(noticesPath, notices, 'utf8');
if (shouldCheck) {
  assert.equal(await fileExists(noticesPath), true, 'THIRD_PARTY_NOTICES.md is missing; run dependency:audit:write.');
  assert.equal(await readFile(noticesPath, 'utf8'), notices, 'THIRD_PARTY_NOTICES.md is stale; run dependency:audit:write.');
}
if (reportPath) await writeFile(path.resolve(reportPath), `${JSON.stringify(report, null, 2)}\n`, 'utf8');

process.stdout.write(`${JSON.stringify({
  packageCount: report.packageCount,
  licenses: report.licenses,
  missingLicenseTexts: report.conclusions.missingLicenseTexts,
  unreviewedLicenseExpressions: report.conclusions.unreviewedLicenseExpressions,
  noticesSha256: report.noticesSha256,
})}\n`);
