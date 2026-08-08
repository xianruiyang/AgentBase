import { spawn } from 'node:child_process';
import { createWriteStream } from 'node:fs';

const [stdoutCapturePath, stdinCapturePath, cliPath] = process.argv.slice(2);
if (!stdoutCapturePath || !stdinCapturePath || !cliPath) {
  process.stderr.write('stdio-capture-proxy requires stdout capture, stdin capture, and CLI paths.\n');
  process.exitCode = 2;
} else {
  const stdoutCapture = createWriteStream(stdoutCapturePath, { flags: 'wx', mode: 0o600 });
  const stdinCapture = createWriteStream(stdinCapturePath, { flags: 'wx', mode: 0o600 });
  const child = spawn(process.execPath, [cliPath], {
    cwd: process.cwd(),
    env: process.env,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });

  process.stdin.on('data', (chunk) => {
    stdinCapture.write(chunk);
    child.stdin.write(chunk);
  });
  process.stdin.once('end', () => {
    stdinCapture.end();
    child.stdin.end();
  });
  process.stdin.once('error', (error) => child.stdin.destroy(error));

  child.stdout.on('data', (chunk) => {
    stdoutCapture.write(chunk);
    process.stdout.write(chunk);
  });
  child.stdout.once('end', () => stdoutCapture.end());
  child.stdout.once('error', (error) => process.stdout.destroy(error));
  child.stderr.pipe(process.stderr);

  const forwardSignal = (signal) => {
    if (!child.killed) child.kill(signal);
  };
  process.once('SIGINT', () => forwardSignal('SIGINT'));
  process.once('SIGTERM', () => forwardSignal('SIGTERM'));

  child.once('error', (error) => {
    process.stderr.write(`${error.stack ?? error.message}\n`);
    process.exitCode = 1;
  });
  child.once('exit', (code, signal) => {
    if (!stdinCapture.closed) stdinCapture.end();
    if (!stdoutCapture.closed) stdoutCapture.end();
    process.exitCode = code ?? (signal === null ? 1 : 1);
  });
}
