import { appendFileSync } from 'node:fs';
import path from 'node:path';

const [, , mode, markerPath, workspacePath] = process.argv;
if (mode === undefined || markerPath === undefined) {
  process.exitCode = 64;
} else {
  appendFileSync(markerPath, `${mode}\n`, 'utf8');
  if (mode === 'build' &&
      (workspacePath === undefined || workspacePath.includes('${') || !path.isAbsolute(workspacePath))) {
    process.stderr.write('workspaceFolder was not resolved before captured task execution\n');
    process.exitCode = 65;
  } else if (mode === 'build') {
    process.stdout.write('P6 successful build output\n');
  } else if (mode === 'fail') {
    process.stdout.write('P6 task output first line\n');
    process.stderr.write('P6 task error detail\n');
    process.exitCode = 7;
  } else if (mode === 'timeout') {
    setInterval(() => undefined, 1_000);
  }
}
