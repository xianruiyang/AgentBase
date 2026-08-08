import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const componentRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const scripts = ['workspace:check', 'typecheck', 'lint', 'test', 'docs:check', 'dependency:audit'];

const npmCliPath = process.env.npm_execpath;
if (!npmCliPath) {
  throw new Error('npm_execpath is required; invoke this verifier through npm run verify.');
}

for (const script of scripts) {
  const result = spawnSync(process.execPath, [npmCliPath, 'run', script], {
    cwd: componentRoot,
    env: process.env,
    stdio: 'inherit',
  });

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${script} failed with exit code ${result.status}`);
  }
}
