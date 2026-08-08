import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import {
  TOOL_NAMES,
  assertToolOutput,
  decodeYamlText,
} from '@simplechat/vscode-lsp-mcp-protocol';
import { getServerVersion } from './cli.js';

test('server version is read from the package manifest used by the executable', () => {
  assert.equal(getServerVersion(), '0.1.21');
});

test('real stdio CLI reserves stdout for MCP initialize, listTools, and callTool', {
  timeout: 10_000,
}, async () => {
  const directory = path.dirname(fileURLToPath(import.meta.url));
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(directory, 'cli.js')],
    cwd: process.cwd(),
    stderr: 'pipe',
  });
  const client = new Client({ name: 'stdio-smoke', version: '1.0.0' });
  try {
    await client.connect(transport);
    const tools = await client.listTools();
    assert.deepEqual(tools.tools.map((tool) => tool.name), [...TOOL_NAMES]);
    const health = await client.callTool({ name: 'health_check', arguments: {} });
    assert.equal(health.isError, undefined);
    const publicHealth = health as unknown as {
      readonly content?: unknown;
      readonly structuredContent?: unknown;
    };
    assert.equal(publicHealth.structuredContent, undefined);
    assert.ok(Array.isArray(publicHealth.content));
    const content = publicHealth.content[0] as {
      readonly type?: unknown;
      readonly text?: unknown;
    } | undefined;
    assert.equal(content?.type, 'text');
    assert.equal(typeof content?.text, 'string');
    if (typeof content?.text !== 'string') {
      throw new Error('health_check did not return YAML TextContent.');
    }
    assertToolOutput('health_check', decodeYamlText(content.text));
  } finally {
    await client.close();
  }
});

test('real stdio CLI exits cleanly when its parent closes stdin without MCP shutdown', {
  timeout: 5_000,
}, async () => {
  const directory = path.dirname(fileURLToPath(import.meta.url));
  const child = spawn(process.execPath, [path.join(directory, 'cli.js')], {
    cwd: process.cwd(),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  let stderr = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (chunk: string) => {
    stderr = `${stderr}${chunk}`.slice(-4_096);
  });
  try {
    await new Promise((resolve) => setTimeout(resolve, 200));
    child.stdin.end();
    const exit = await new Promise<{ readonly code: number | null; readonly signal: NodeJS.Signals | null }>(
      (resolve, reject) => {
        child.once('error', reject);
        child.once('exit', (code, signal) => resolve({ code, signal }));
      },
    );
    assert.deepEqual(exit, { code: 0, signal: null }, stderr);
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill();
    }
  }
});
