import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runTests } from '@vscode/test-electron';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const npmCliPath = process.env.npm_execpath;
if (!npmCliPath) {
  throw new Error('npm_execpath is required; run this gate through npm run test:integration:mutation-command.');
}

if (process.env.P6_003_SKIP_BUILD !== '1') {
  const build = spawnSync(process.execPath, [npmCliPath, 'run', 'build'], {
    cwd: componentRoot,
    env: process.env,
    stdio: 'inherit',
  });
  if (build.error) throw build.error;
  if (build.status !== 0) {
    throw new Error(`P6-003 prerequisite build failed with exit code ${build.status}.`);
  }
}

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-stage-d-'));
const fixtureName = path.basename(temporaryRoot);
const fixtureTemplate = path.join(
  componentRoot,
  'tests',
  'fixtures',
  'extension-host-mutation-command',
);
const taskMarkerPath = path.join(temporaryRoot, '.p6-task-markers.txt');
const reportPath = process.env.P6_003_REPORT_PATH ?? path.join(temporaryRoot, 'p6-003-report.json');
const controlRoot = path.join(temporaryRoot, '.p6-control');

const substitute = (value, replacements) => {
  if (typeof value === 'string') {
    return Object.entries(replacements).reduce(
      (current, [token, replacement]) => current.replaceAll(token, replacement),
      value,
    );
  }
  if (Array.isArray(value)) return value.map((item) => substitute(item, replacements));
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, nested]) => [
      key,
      substitute(nested, replacements),
    ]));
  }
  return value;
};

try {
  await cp(fixtureTemplate, temporaryRoot, { recursive: true });
  await mkdir(path.dirname(reportPath), { recursive: true });
  const tasksTemplatePath = path.join(temporaryRoot, '.vscode', 'tasks.template.json');
  const tasksTemplate = JSON.parse(await readFile(tasksTemplatePath, 'utf8'));
  const taskConfiguration = substitute(tasksTemplate, {
    __NODE_PATH__: process.execPath,
    __TASK_SCRIPT__: path.join(temporaryRoot, 'task-fixture.mjs'),
    __TASK_MARKER__: taskMarkerPath,
  });
  await Promise.all([
    writeFile(
      path.join(temporaryRoot, '.vscode', 'tasks.json'),
      `${JSON.stringify(taskConfiguration, null, 2)}\n`,
      'utf8',
    ),
    writeFile(path.join(temporaryRoot, 'src', 'range.p6'), 'A😀éZ\r\n', 'utf8'),
  ]);
  await rm(tasksTemplatePath, { force: true });

  await runTests({
    version: process.env.VSCODE_TEST_VERSION ?? '1.128.0',
    extensionDevelopmentPath: path.join(componentRoot, 'packages', 'extension'),
    extensionTestsPath: path.join(
      componentRoot,
      'packages',
      'extension',
      'dist',
      'stage-d-extension-host.js',
    ),
    launchArgs: [
      temporaryRoot,
      '--disable-extensions',
      '--disable-updates',
      '--disable-workspace-trust',
      '--skip-welcome',
      '--skip-release-notes',
      '--user-data-dir',
      path.join(controlRoot, 'user-data'),
      '--extensions-dir',
      path.join(controlRoot, 'extensions'),
    ],
    extensionTestsEnv: {
      STAGE_D_CLIENT_PATH: path.join(
        componentRoot,
        'packages',
        'server',
        'dist',
        'stage-d-integration-client.js',
      ),
      STAGE_D_FIXTURE_NAME: fixtureName,
      STAGE_D_NODE_PATH: process.execPath,
      STAGE_D_REPORT_PATH: reportPath,
      STAGE_D_TASK_MARKER_PATH: taskMarkerPath,
    },
  });

  const report = await readFile(reportPath, 'utf8');
  process.stdout.write(`P6-003 integration report:\n${report}`);
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}
