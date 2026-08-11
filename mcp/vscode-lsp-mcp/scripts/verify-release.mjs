import { runNpmScripts } from './verification-runner.mjs';

if (process.platform !== 'win32') {
  throw new Error('The signed release verification target is currently Windows x64 only.');
}

runNpmScripts([
  'verify',
  'release:verify',
  'test:stage-b',
  'test:stage-c',
  'test:integration:install',
  'test:integration:doctor',
  'test:integration:doctor:packaged',
  'test:integration:read-hierarchy',
  'test:integration:mutation-command',
  'test:integration:all-tools',
], 'npm run verify:release');
