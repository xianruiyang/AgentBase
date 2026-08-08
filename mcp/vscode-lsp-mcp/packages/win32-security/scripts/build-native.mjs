import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const supportedArchitectures = new Set(['x64', 'arm64']);
const targetArchitecture = process.argv[2] ?? process.arch;

if (!supportedArchitectures.has(targetArchitecture)) {
  throw new Error(`Expected x64 or arm64 target architecture, received: ${targetArchitecture}`);
}

if (process.platform !== 'win32') {
  process.stdout.write(`Skipping Windows native build on ${process.platform}.\n`);
  process.exit(0);
}

const require = createRequire(import.meta.url);
const nodeGypCliPath = require.resolve('node-gyp/bin/node-gyp.js');
const result = spawnSync(
  process.execPath,
  [nodeGypCliPath, 'rebuild', '--release', `--arch=${targetArchitecture}`],
  {
    cwd: packageRoot,
    env: process.env,
    stdio: 'inherit',
  },
);

if (result.error) {
  throw result.error;
}
if (result.status !== 0) {
  throw new Error(`node-gyp failed for ${targetArchitecture} with exit code ${result.status}`);
}
