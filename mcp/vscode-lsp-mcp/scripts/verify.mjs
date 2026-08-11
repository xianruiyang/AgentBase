import { runNpmScripts } from './verification-runner.mjs';

const scripts = ['workspace:check', 'typecheck', 'lint', 'test', 'docs:check', 'dependency:audit'];
runNpmScripts(scripts, 'npm run verify');
