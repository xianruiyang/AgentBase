#!/usr/bin/env node
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  InstallError,
  backupConfiguration,
  defaultRoots,
  getInstallStatus,
  installRelease,
  restoreConfiguration,
  uninstallRelease,
} from './install-core.mjs';
import { runDoctor } from './doctor-core.mjs';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));

const usage = `vscode-lsp-mcp installer

Usage:
  node install.mjs install [options]
  node install.mjs status [options]
  node install.mjs doctor [options]
  node install.mjs uninstall [options]
  node install.mjs backup-config --output <file> [options]
  node install.mjs restore-config --input <file> [options]

Options:
  --release-dir <dir>    Release manifest/artifact directory (default: installer directory)
  --install-root <dir>   Managed program root
  --config-root <dir>    Separate user configuration root
  --code-cli <path>      VS Code CLI or Code.exe
  --extensions-dir <dir> Isolated/custom VS Code extensions directory
  --user-data-dir <dir>  Isolated/custom VS Code user-data directory
  --runtime-root <dir>    Advanced override for the existing runtime registry root
  --workspace-id <id>    Diagnose only one registered workspace
  --file <logical-path>  Probe language providers for a logical workspace file
  --log-file <file>      Log path inside <config-root>/logs
  --skip-extension       Install or remove only the MCP server
  --remove-config        With uninstall, explicitly remove config.json
  --output <file>        backup-config destination
  --input <file>         restore-config source
  --json                 Emit a machine-readable result
  --help                 Show this help
`;

const valueOptions = new Set([
  'release-dir',
  'install-root',
  'config-root',
  'code-cli',
  'extensions-dir',
  'user-data-dir',
  'runtime-root',
  'workspace-id',
  'file',
  'log-file',
  'output',
  'input',
]);
const booleanOptions = new Set(['skip-extension', 'remove-config', 'json', 'help']);

export const parseArguments = (argumentsList) => {
  const [command, ...tokens] = argumentsList;
  const options = {};
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token.startsWith('--')) throw new InstallError('INVALID_ARGUMENT', `Unexpected argument: ${token}`);
    const name = token.slice(2);
    if (booleanOptions.has(name)) {
      options[name] = true;
      continue;
    }
    if (!valueOptions.has(name)) throw new InstallError('INVALID_ARGUMENT', `Unknown option: ${token}`);
    const value = tokens[index + 1];
    if (value === undefined || value.startsWith('--')) {
      throw new InstallError('MISSING_ARGUMENT', `${token} requires a value.`);
    }
    options[name] = value;
    index += 1;
  }
  return { command, options };
};

const normalizedOptions = (parsed) => {
  const roots = defaultRoots();
  return {
    releaseDir: parsed['release-dir'] ?? process.env.VSCODE_LSP_MCP_RELEASE_DIR ?? scriptDirectory,
    installRoot: parsed['install-root'] ?? process.env.VSCODE_LSP_MCP_INSTALL_ROOT ?? roots.installRoot,
    configRoot: parsed['config-root'] ?? process.env.VSCODE_LSP_MCP_CONFIG_ROOT ?? roots.configRoot,
    codeCli: parsed['code-cli'] ?? process.env.CODE_CLI,
    extensionsDir: parsed['extensions-dir'],
    userDataDir: parsed['user-data-dir'],
    runtimeRoot: parsed['runtime-root'],
    workspaceId: parsed['workspace-id'],
    file: parsed.file,
    logFile: parsed['log-file'],
    skipExtension: parsed['skip-extension'] === true,
    removeConfig: parsed['remove-config'] === true,
    output: parsed.output,
    input: parsed.input,
  };
};

export const runCli = async (argumentsList) => {
  const { command, options: parsed } = parseArguments(argumentsList);
  if (command === undefined || command === '--help' || parsed.help === true) {
    return { help: true, text: usage, json: parsed.json === true };
  }
  const options = normalizedOptions(parsed);
  let result;
  switch (command) {
    case 'install':
      result = await installRelease(options);
      break;
    case 'status':
      result = await getInstallStatus(options);
      break;
    case 'doctor':
      result = await runDoctor(options);
      break;
    case 'uninstall':
      result = await uninstallRelease(options);
      break;
    case 'backup-config':
      result = await backupConfiguration(options);
      break;
    case 'restore-config':
      result = await restoreConfiguration(options);
      break;
    default:
      throw new InstallError('INVALID_COMMAND', `Unknown installer command: ${command}`);
  }
  return { help: false, result, json: parsed.json === true };
};

const isMain = process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  try {
    const output = await runCli(process.argv.slice(2));
    if (output.help) process.stdout.write(output.text);
    else if (output.json) process.stdout.write(`${JSON.stringify(output.result)}\n`);
    else if (output.result.kind === 'doctor') {
      process.stdout.write(`doctor ${output.result.status}: ${output.result.summary.fail} failed, ${output.result.summary.warning} warning(s); log ${output.result.log.path}\n`);
    } else {
      process.stdout.write(`${output.result.outcome ?? (output.result.installed ? 'installed' : 'not installed')}\n`);
    }
  } catch (error) {
    const code = error instanceof InstallError ? error.code : 'INSTALL_FAILED';
    const message = error instanceof Error ? error.message : String(error);
    if (process.argv.includes('--json')) {
      process.stderr.write(`${JSON.stringify({ ok: false, error: { code, message } })}\n`);
    } else {
      process.stderr.write(`vscode-lsp-mcp installer failed [${code}]: ${message}\n`);
    }
    process.exitCode = 1;
  }
}
