#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createFoundationMcpServer } from './mcp-server.js';
import { CommandService } from './command-service.js';
import { createMutationCache } from './mutation-cache.js';
import { MutationService, createMutationClientSessionId } from './rename-service.js';
import { createSystemWorkspaceRouter } from './workspace-router.js';

export const getServerVersion = (): string => {
  const manifestPath = fileURLToPath(new URL('../package.json', import.meta.url));
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as { version?: unknown };
  if (typeof manifest.version !== 'string' || manifest.version.length === 0) {
    throw new Error('The packaged server manifest has no valid version.');
  }
  return manifest.version;
};

export const runStdioServer = async (): Promise<void> => {
  const router = await createSystemWorkspaceRouter();
  const mutationCache = createMutationCache();
  const mutationService = new MutationService({
    cache: mutationCache,
    clientSessionId: createMutationClientSessionId(),
    connector: router,
  });
  const commandService = new CommandService({ connector: router });
  const server = createFoundationMcpServer(router, mutationService, commandService);
  let routerCloseTask: Promise<void> | undefined;
  const closeRouter = (): Promise<void> => {
    routerCloseTask ??= router.close();
    return routerCloseTask;
  };
  let shutdownTask: Promise<void> | undefined;
  const removeInputListeners = (): void => {
    process.stdin.off('end', onInputClosed);
    process.stdin.off('close', onInputClosed);
  };
  const shutdown = (): Promise<void> => {
    shutdownTask ??= (async () => {
      await server.close().catch(() => undefined);
      await closeRouter().catch(() => undefined);
    })();
    return shutdownTask;
  };
  const onInputClosed = (): void => {
    void shutdown();
  };
  server.onclose = () => {
    removeInputListeners();
    void closeRouter();
  };
  const transport = new StdioServerTransport();
  process.stdin.once('end', onInputClosed);
  process.stdin.once('close', onInputClosed);
  try {
    await server.connect(transport);
  } catch (error) {
    removeInputListeners();
    await closeRouter().catch(() => undefined);
    throw error;
  }
};

const isMainModule = process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMainModule) {
  if (process.argv.length === 3 && process.argv[2] === '--version') {
    process.stdout.write(`${getServerVersion()}\n`);
  } else {
    void runStdioServer().catch((error: unknown) => {
      const message = error instanceof Error ? error.message : 'Unknown startup failure.';
      process.stderr.write(`vscode-lsp-mcp startup failed: ${message}\n`);
      process.exitCode = 1;
    });
  }
}
