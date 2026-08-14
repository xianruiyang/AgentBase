import { randomBytes } from 'node:crypto';
import {
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  rmdir,
  stat,
  writeFile,
} from 'node:fs/promises';
import path from 'node:path';
import type { TaskOutputLog, WorkspacePathAccess, WorkspacePathContext } from '@simplechat/vscode-lsp-mcp-protocol';
import {
  resolveLogicalPath,
  toPathComparisonKey,
} from '@simplechat/vscode-lsp-mcp-protocol';
import type { Task } from 'vscode';

export interface CommandTaskOutputCapture<TTask> {
  readonly task: TTask;
  finish(retain: boolean): PromiseLike<TaskOutputLog | undefined>;
}

const TASK_LOG_DIRECTORY = '.vscode-lsp-mcp/task-logs';
const MAX_TASK_LOG_BYTES = 64 * 1024 * 1024;
const MAX_RETAINED_TASK_LOGS = 10;
const STALE_PENDING_MILLISECONDS = 24 * 60 * 60 * 1_000;
const ANSI_CSI = new RegExp(`${String.fromCharCode(27)}\\[[0-?]*[ -/]*[@-~]`, 'gu');
const POWERSHELL_RUNNER = String.raw`param(
  [Parameter(Mandatory = $true)][string]$LogPath,
  [Parameter(Mandatory = $true)][string]$MetadataPath,
  [Parameter(Mandatory = $true)][long]$MaximumBytes,
  [Parameter(Mandatory = $true)][string]$CapturePrefix
)
$ErrorActionPreference = 'Continue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$stream = New-Object System.IO.FileStream(
  $LogPath,
  [System.IO.FileMode]::CreateNew,
  [System.IO.FileAccess]::Write,
  [System.IO.FileShare]::Read
)
$observedBytes = [long]0
$capturedBytes = [long]0
try {
  $executableName = "$($CapturePrefix)_EXECUTABLE"
  $argumentCountName = "$($CapturePrefix)_ARG_COUNT"
  $childExecutable = [Environment]::GetEnvironmentVariable($executableName, 'Process')
  $argumentCount = [int][Environment]::GetEnvironmentVariable($argumentCountName, 'Process')
  if ([string]::IsNullOrWhiteSpace($childExecutable) -or $argumentCount -lt 0) {
    throw 'Captured task process metadata is invalid.'
  }
  $childArguments = @()
  for ($index = 0; $index -lt $argumentCount; $index += 1) {
    $name = "$($CapturePrefix)_ARG_$index"
    $childArguments += [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
  }
  [Environment]::SetEnvironmentVariable($executableName, $null, 'Process')
  [Environment]::SetEnvironmentVariable($argumentCountName, $null, 'Process')
  $global:LASTEXITCODE = 1
  & $childExecutable @childArguments 2>&1 | ForEach-Object {
    $line = "$_"
    [Console]::Out.WriteLine($line)
    $bytes = $utf8.GetBytes($line + [Environment]::NewLine)
    $observedBytes += $bytes.Length
    $remaining = $MaximumBytes - $capturedBytes
    if ($remaining -gt 0) {
      $retained = [Math]::Min($remaining, $bytes.Length)
      $stream.Write($bytes, 0, [int]$retained)
      $capturedBytes += $retained
    }
  }
  $exitCode = $global:LASTEXITCODE
  if ($null -eq $exitCode) { $exitCode = 1 }
} catch {
  $line = "Task process could not be completed: $($_.Exception.Message)"
  [Console]::Error.WriteLine($line)
  $bytes = $utf8.GetBytes($line + [Environment]::NewLine)
  $observedBytes += $bytes.Length
  $remaining = $MaximumBytes - $capturedBytes
  if ($remaining -gt 0) {
    $retained = [Math]::Min($remaining, $bytes.Length)
    $stream.Write($bytes, 0, [int]$retained)
    $capturedBytes += $retained
  }
  $exitCode = 1
} finally {
  $stream.Flush()
  $stream.Dispose()
  $metadata = @{
    observedBytes = $observedBytes
    capturedBytes = $capturedBytes
    truncated = ($observedBytes -gt $capturedBytes)
  } | ConvertTo-Json -Compress
  [System.IO.File]::WriteAllText($MetadataPath, $metadata + [Environment]::NewLine, $utf8)
}
exit $exitCode
`;

export const normalizeCapturedTaskOutput = (raw: Uint8Array): string =>
  new TextDecoder('utf-8', { fatal: false })
    .decode(raw)
    .replace(ANSI_CSI, '')
    .replaceAll('\r\n', '\n')
    .replaceAll('\r', '\n');

export const taskOutputLineCount = (text: string): number => {
  if (text.length === 0) return 0;
  let lines = text.endsWith('\n') ? 0 : 1;
  for (const character of text) {
    if (character === '\n') lines += 1;
  }
  return lines;
};

const taskSlug = (taskName: string): string => {
  const normalized = taskName.normalize('NFKC').toLowerCase()
    .replace(/[^a-z0-9._-]+/gu, '-')
    .replace(/-+/gu, '-')
    .replace(/^[._-]+|[._-]+$/gu, '')
    .slice(0, 48)
    .replace(/[._-]+$/gu, '');
  return normalized.length === 0 ? 'task' : normalized;
};

const compactTimestamp = (date: Date): string =>
  date.toISOString().replaceAll('-', '').replaceAll(':', '').replace(/\.\d{3}Z$/u, 'Z');

const rootForTask = (
  context: WorkspacePathContext,
  task: Task,
) => {
  if (typeof task.scope !== 'object' || task.scope.uri.scheme !== 'file') return undefined;
  let key: string;
  try {
    key = toPathComparisonKey(task.scope.uri.fsPath);
  } catch {
    return undefined;
  }
  return context.roots.find((candidate) => candidate.lexicalComparisonKey === key);
};

const removeIfEmpty = async (directory: string): Promise<void> => {
  try { await rmdir(directory); } catch { /* existing logs or an external writer keep the directory */ }
};

const cleanupManagedLogs = async (directory: string, now: number): Promise<void> => {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return;
  }
  const pending = entries.filter((entry) => entry.isFile() && /^\.pending-[a-f0-9]+\.(?:log|json|ps1)$/u.test(entry.name));
  for (const entry of pending) {
    const absolutePath = path.join(directory, entry.name);
    try {
      if (now - (await stat(absolutePath)).mtimeMs > STALE_PENDING_MILLISECONDS) {
        await rm(absolutePath, { force: true });
      }
    } catch { /* cleanup is best effort */ }
  }
  const logs = await Promise.all(entries
    .filter((entry) => entry.isFile() && /^\d{8}T\d{6}Z-.+-[a-f0-9]+\.log$/u.test(entry.name))
    .map(async (entry) => ({
      name: entry.name,
      modified: await stat(path.join(directory, entry.name)).then((value) => value.mtimeMs, () => 0),
    })));
  logs.sort((left, right) => right.modified - left.modified || right.name.localeCompare(left.name));
  await Promise.all(logs.slice(MAX_RETAINED_TASK_LOGS).map((entry) =>
    rm(path.join(directory, entry.name), { force: true })));
};

interface RunnerMetadata {
  readonly truncated: boolean;
}

const readRunnerMetadata = async (metadataPath: string): Promise<RunnerMetadata | undefined> => {
  try {
    const value = JSON.parse(await readFile(metadataPath, 'utf8')) as Record<string, unknown>;
    return typeof value.truncated === 'boolean' ? { truncated: value.truncated } : undefined;
  } catch {
    return undefined;
  }
};

export const prepareVscodeTaskOutputCapture = async (
  vscode: typeof import('vscode'),
  context: WorkspacePathContext,
  task: Task,
  taskName: string,
  access: WorkspacePathAccess,
): Promise<CommandTaskOutputCapture<Task> | undefined> => {
  if (context.platform !== 'win32') return undefined;
  if (!(task.execution instanceof vscode.ProcessExecution)) return undefined;
  if (typeof task.scope !== 'object') return undefined;
  const systemRoot = process.env.SystemRoot ?? process.env.WINDIR;
  if (systemRoot === undefined) return undefined;
  const root = rootForTask(context, task);
  if (root === undefined) return undefined;
  const originalOptions = task.execution.options;

  const identifier = randomBytes(6).toString('hex');
  const timestamp = compactTimestamp(new Date());
  const logicalDirectory = context.roots.length === 1
    ? TASK_LOG_DIRECTORY
    : `${root.alias}/${TASK_LOG_DIRECTORY}`;
  const pendingLogicalPath = `${logicalDirectory}/.pending-${identifier}.log`;
  const finalLogicalPath = `${logicalDirectory}/${timestamp}-${taskSlug(taskName)}-${identifier}.log`;
  const pending = await resolveLogicalPath(context, pendingLogicalPath, access, { allowMissing: true });
  const pendingPath = pending.lexicalAbsolutePath;
  const metadataPath = path.join(path.dirname(pendingPath), `.pending-${identifier}.json`);
  const runnerPath = path.join(path.dirname(pendingPath), `.pending-${identifier}.ps1`);
  const finalPath = path.join(path.dirname(pendingPath), path.basename(finalLogicalPath));
  await mkdir(path.dirname(pendingPath), { recursive: true });
  await resolveLogicalPath(context, pendingLogicalPath, access, { allowMissing: true });
  await cleanupManagedLogs(path.dirname(pendingPath), Date.now());
  await writeFile(runnerPath, POWERSHELL_RUNNER, { encoding: 'utf8', flag: 'wx' });

  const environmentPrefix = `VSCODE_LSP_MCP_CAPTURE_${identifier.toUpperCase()}`;
  const wrapperEnvironment = {
    ...(originalOptions?.env ?? {}),
    [`${environmentPrefix}_EXECUTABLE`]: task.execution.process,
    [`${environmentPrefix}_ARG_COUNT`]: String(task.execution.args.length),
    ...Object.fromEntries(task.execution.args.map((argument, index) =>
      [`${environmentPrefix}_ARG_${index}`, argument] as const)),
  };
  const wrapperOptions = {
    ...(originalOptions?.cwd === undefined ? {} : { cwd: originalOptions.cwd }),
    env: wrapperEnvironment,
  };
  const powershellPath = path.win32.join(
    systemRoot,
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe',
  );
  const execution = new vscode.ProcessExecution(powershellPath, [
    '-NoLogo',
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    runnerPath,
    '-LogPath',
    pendingPath,
    '-MetadataPath',
    metadataPath,
    '-MaximumBytes',
    String(MAX_TASK_LOG_BYTES),
    '-CapturePrefix',
    environmentPrefix,
  ], wrapperOptions);
  const wrapped = new vscode.Task(
    task.definition,
    task.scope,
    task.name,
    task.source,
    execution,
    task.problemMatchers,
  );
  if (task.detail !== undefined) wrapped.detail = task.detail;
  if (task.group !== undefined) wrapped.group = task.group;
  wrapped.isBackground = task.isBackground;
  wrapped.presentationOptions = { ...task.presentationOptions };
  wrapped.runOptions = { ...task.runOptions };

  let finishPromise: Promise<TaskOutputLog | undefined> | undefined;
  return Object.freeze({
    task: wrapped,
    finish: (retain: boolean) => {
      finishPromise ??= (async () => {
        if (!retain) {
          await Promise.all([
            rm(pendingPath, { force: true }),
            rm(metadataPath, { force: true }),
            rm(runnerPath, { force: true }),
          ]);
          await removeIfEmpty(path.dirname(pendingPath));
          await removeIfEmpty(path.dirname(path.dirname(pendingPath)));
          return undefined;
        }
        const [raw, metadata] = await Promise.all([
          readFile(pendingPath),
          readRunnerMetadata(metadataPath),
        ]);
        const normalized = normalizeCapturedTaskOutput(raw);
        await writeFile(pendingPath, normalized, 'utf8');
        await rename(pendingPath, finalPath);
        await rm(metadataPath, { force: true });
        await rm(runnerPath, { force: true });
        await cleanupManagedLogs(path.dirname(finalPath), Date.now());
        return Object.freeze({
          path: finalLogicalPath,
          lineCount: taskOutputLineCount(normalized),
          byteCount: Buffer.byteLength(normalized, 'utf8'),
          encoding: 'utf-8' as const,
          truncated: metadata?.truncated ?? true,
        });
      })().catch(async () => {
        await Promise.all([
          rm(pendingPath, { force: true }).catch(() => undefined),
          rm(metadataPath, { force: true }).catch(() => undefined),
          rm(runnerPath, { force: true }).catch(() => undefined),
        ]);
        return undefined;
      });
      return finishPromise;
    },
  });
};
