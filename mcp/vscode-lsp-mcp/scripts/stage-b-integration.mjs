import { spawnSync } from 'node:child_process';
import { cp, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runTests } from '@vscode/test-electron';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const npmCliPath = process.env.npm_execpath;

if (!npmCliPath) {
  throw new Error('npm_execpath is required; run this gate through npm run test:stage-b.');
}

const build = spawnSync(process.execPath, [npmCliPath, 'run', 'build'], {
  cwd: componentRoot,
  env: process.env,
  stdio: 'inherit',
});
if (build.error) throw build.error;
if (build.status !== 0) {
  throw new Error(`Stage B prerequisite build failed with exit code ${build.status}.`);
}

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-stage-b-'));
const fixtureName = path.basename(temporaryRoot);
const fixtureSource = path.join(temporaryRoot, 'src');
const fixtureTemplate = path.join(
  componentRoot,
  'tests',
  'fixtures',
  'extension-host-read-hierarchy',
);
const reportPath = process.env.STAGE_B_REPORT_PATH ?? path.join(temporaryRoot, 'stage-b-report.json');

const numbered = (prefix, count, render) => Array.from(
  { length: count },
  (_value, index) => render(prefix + String(index + 1).padStart(3, '0')),
).join('\n');

try {
  await cp(fixtureTemplate, temporaryRoot, { recursive: true });
  await Promise.all([
    writeFile(
      path.join(fixtureSource, 'large.ts'),
      "import { Widget } from './widget.js';\n" +
        numbered('ref', 140, (name) => `export const ${name} = new Widget();`) + '\n',
      'utf8',
    ),
    writeFile(
      path.join(fixtureSource, 'symbols.ts'),
      numbered('WindowSymbol', 140, (name) => `export class ${name} {}`) + '\n',
      'utf8',
    ),
  ]);

  await runTests({
    version: process.env.VSCODE_TEST_VERSION ?? '1.128.0',
    extensionDevelopmentPath: path.join(componentRoot, 'packages', 'extension'),
    extensionTestsPath: path.join(
      componentRoot,
      'packages',
      'extension',
      'dist',
      'stage-b-extension-host.js',
    ),
    launchArgs: [
      temporaryRoot,
      '--disable-extensions',
      '--disable-workspace-trust',
      '--skip-welcome',
      '--skip-release-notes',
    ],
    extensionTestsEnv: {
      STAGE_B_CLIENT_PATH: path.join(
        componentRoot,
        'packages',
        'server',
        'dist',
        'stage-b-integration-client.js',
      ),
      STAGE_B_FIXTURE_NAME: fixtureName,
      STAGE_B_NODE_PATH: process.execPath,
      STAGE_B_REPORT_PATH: reportPath,
    },
  });

  const report = await readFile(reportPath, 'utf8');
  process.stdout.write(`Stage B integration report:\n${report}`);
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}
