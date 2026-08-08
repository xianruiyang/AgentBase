import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const tscCliPath = require.resolve('typescript/bin/tsc');
const nativeBuildScript = join(packageRoot, 'scripts', 'build-native.mjs');

function run(scriptPath, argumentsList) {
  const result = spawnSync(process.execPath, [scriptPath, ...argumentsList], {
    cwd: packageRoot,
    env: process.env,
    stdio: 'inherit',
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${scriptPath} failed with exit code ${result.status}`);
  }
}

run(tscCliPath, ['-p', 'tsconfig.json', '--pretty', 'false']);
run(nativeBuildScript, [process.arch]);
