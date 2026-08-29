import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import {
  assertToolOutput,
  decodeYamlText,
  type ToolName,
  type ToolResponseMap,
} from '@simplechat/vscode-lsp-mcp-protocol';

const requiredEnvironment = (name: string): string => {
  const value = process.env[name];
  if (value === undefined || value.length === 0) throw new Error(`Missing ${name}.`);
  return value;
};

const forbiddenKeys = new Set([
  'authToken',
  'endpoint',
  'instanceId',
  'provider',
  'uri',
  'workspaceGeneration',
]);

const assertNoInternalLeak = (value: unknown, fixtureRoot: string): void => {
  const visit = (candidate: unknown): void => {
    if (Array.isArray(candidate)) {
      candidate.forEach(visit);
      return;
    }
    if (candidate === null || typeof candidate !== 'object') return;
    for (const [key, nested] of Object.entries(candidate)) {
      assert.equal(forbiddenKeys.has(key), false, `Internal key leaked: ${key}.`);
      visit(nested);
    }
  };
  visit(value);
  const serialized = JSON.stringify(value).replaceAll('\\', '/').toLowerCase();
  const normalizedRoot = fixtureRoot.replaceAll('\\', '/').toLowerCase();
  assert.equal(serialized.includes(normalizedRoot), false, 'Absolute fixture path leaked.');
  assert.equal(serialized.includes('file://'), false, 'File URI leaked.');
  assert.equal(serialized.includes('vscode.execute'), false, 'Provider command leaked.');
  assert.equal(serialized.includes('\\\\.\\pipe'), false, 'Named Pipe endpoint leaked.');
};

const responseBytes = (value: unknown): number => Buffer.byteLength(JSON.stringify(value), 'utf8');

const main = async (): Promise<void> => {
  const fixtureName = requiredEnvironment('STAGE_B_FIXTURE_NAME');
  const fixtureRoot = requiredEnvironment('STAGE_B_EXPECTED_ROOT');
  const directory = path.dirname(fileURLToPath(import.meta.url));
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(directory, 'cli.js')],
    cwd: process.cwd(),
    stderr: 'pipe',
  });
  const client = new Client({ name: 'stage-b-integration', version: '1.0.0' });

  const call = async <K extends ToolName>(
    name: K,
    argumentsValue: Record<string, unknown>,
  ): Promise<{ readonly raw: unknown; readonly response: ToolResponseMap[K] }> => {
    const raw = await client.callTool({ name, arguments: argumentsValue });
    const publicRaw = raw as unknown as {
      readonly content?: unknown;
      readonly isError?: boolean;
      readonly structuredContent?: unknown;
    };
    assert.equal(publicRaw.structuredContent, undefined);
    assert.ok(Array.isArray(publicRaw.content));
    const content = publicRaw.content[0] as {
      readonly type?: unknown;
      readonly text?: unknown;
    } | undefined;
    assert.equal(content?.type, 'text');
    assert.equal(typeof content?.text, 'string');
    if (typeof content?.text !== 'string') throw new Error(`${name} did not return YAML TextContent.`);
    const response = decodeYamlText(content.text);
    assert.equal(
      publicRaw.isError,
      undefined,
      `${name} returned an MCP error: ${JSON.stringify(response)}.`,
    );
    assertToolOutput(name, response);
    return {
      raw,
      response: response as unknown as ToolResponseMap[K],
    };
  };

  try {
    await client.connect(transport);
    const listed = await call('list_workspaces', {});
    assert.equal(listed.response.ok, true);
    if (!listed.response.ok) throw new Error('Workspace discovery failed.');
    const workspaces = listed.response.data.results.filter((workspace) => workspace.name === fixtureName);
    assert.equal(workspaces.length, 1, 'The isolated Extension Host workspace was not uniquely routed.');
    const workspaceId = workspaces[0]?.workspaceId;
    assert.ok(workspaceId);

    const capabilities = await call('get_capabilities', {
      workspaceId,
      file: 'src/dirty.ts',
      capabilities: ['commands', 'diagnostics', 'definition', 'documentSymbols'],
      resultStart: 2,
      resultEnd: 4,
    });
    assert.equal(capabilities.response.ok, true);
    if (!capabilities.response.ok) throw new Error('Capability probing failed.');
    assert.equal(capabilities.response.data.available, 4);
    assert.deepEqual(capabilities.response.data.results.map((candidate) => candidate.name), [
      'definition',
      'diagnostics',
      'commands',
    ]);
    assert.equal(capabilities.response.data.results[0]?.status, 'unknown');
    assert.equal(capabilities.response.data.results[1]?.status, 'available');
    assert.equal(capabilities.response.data.results[2]?.status, 'available');

    const unsupportedCapabilities = await call('get_capabilities', {
      workspaceId,
      file: 'src/unsupported.txt',
      capabilities: ['callHierarchy', 'typeHierarchy'],
    });
    assert.equal(unsupportedCapabilities.response.ok, true);
    if (!unsupportedCapabilities.response.ok) throw new Error('Unsupported capability probing failed.');
    assert.deepEqual(unsupportedCapabilities.response.data.results.map((candidate) => ({
      name: candidate.name,
      status: candidate.status,
      reason: candidate.status === 'available' ? undefined : candidate.reason,
    })), [
      { name: 'callHierarchy', status: 'unknown', reason: 'probe_returned_no_evidence' },
      { name: 'typeHierarchy', status: 'unknown', reason: 'probe_returned_no_evidence' },
    ]);

    const callHierarchy = await call('get_call_hierarchy', {
      workspaceId,
      file: 'src/hierarchy.ts',
      line: 4,
      column: 17,
      direction: 'both',
      maxDepth: 2,
    });
    assert.equal(callHierarchy.response.ok, true);
    if (!callHierarchy.response.ok) throw new Error('Call hierarchy failed.');
    const callRoot = callHierarchy.response.data.results.find((entry) => entry.relation === 'root');
    const incoming = callHierarchy.response.data.results.find((entry) =>
      entry.relation === 'incoming' && entry.symbol.name === 'rootCall');
    const outgoing = callHierarchy.response.data.results.find((entry) =>
      entry.relation === 'outgoing' && entry.symbol.name === 'leafCall');
    assert.equal(callRoot?.symbol.name, 'middleCall');
    assert.equal(incoming?.depth, 1);
    assert.equal(incoming?.parent?.name, 'middleCall');
    assert.ok(incoming?.callSites !== undefined && incoming.callSites.length > 0);
    assert.equal(outgoing?.depth, 1);
    assert.equal(outgoing?.parent?.name, 'middleCall');
    assert.ok(outgoing?.callSites !== undefined && outgoing.callSites.length > 0);

    const typeHierarchy = await call('get_type_hierarchy', {
      workspaceId,
      file: 'src/hierarchy.ts',
      line: 11,
      column: 14,
      direction: 'both',
      maxDepth: 2,
    });
    assert.equal(typeHierarchy.response.ok, true);
    if (!typeHierarchy.response.ok) throw new Error('Type hierarchy failed.');
    const typeRoot = typeHierarchy.response.data.results.find((entry) => entry.relation === 'root');
    const supertype = typeHierarchy.response.data.results.find((entry) =>
      entry.relation === 'supertype' && entry.symbol.name === 'BaseType');
    const subtype = typeHierarchy.response.data.results.find((entry) =>
      entry.relation === 'subtype' && entry.symbol.name === 'LeafType');
    assert.equal(typeRoot?.symbol.name, 'MiddleType');
    assert.equal(supertype?.depth, 1);
    assert.equal(supertype?.parent?.name, 'MiddleType');
    assert.equal(subtype?.depth, 1);
    assert.equal(subtype?.parent?.name, 'MiddleType');

    const dirtyCallHierarchy = await call('get_call_hierarchy', {
      workspaceId,
      file: 'src/dirty.ts',
      line: 5,
      column: 17,
      direction: 'both',
      maxDepth: 2,
    });
    assert.equal(dirtyCallHierarchy.response.ok, true);
    if (!dirtyCallHierarchy.response.ok) throw new Error('Dirty call hierarchy failed.');
    assert.equal(dirtyCallHierarchy.response.data.results.some((entry) =>
      entry.relation === 'root' && entry.symbol.name === 'dirtyRoot'), true);
    assert.equal(dirtyCallHierarchy.response.data.results.some((entry) =>
      entry.relation === 'outgoing' && entry.symbol.name === 'dirtyLeaf'), true);

    const dirtyTypeHierarchy = await call('get_type_hierarchy', {
      workspaceId,
      file: 'src/dirty.ts',
      line: 7,
      column: 14,
      direction: 'both',
      maxDepth: 2,
    });
    assert.equal(dirtyTypeHierarchy.response.ok, true);
    if (!dirtyTypeHierarchy.response.ok) throw new Error('Dirty type hierarchy failed.');
    assert.deepEqual(
      new Set(dirtyTypeHierarchy.response.data.results.map((entry) => entry.symbol.name)),
      new Set(['DirtyBase', 'DirtyMiddle', 'DirtyLeaf']),
    );

    const unsupportedCallHierarchy = await call('get_call_hierarchy', {
      workspaceId,
      file: 'src/unsupported.txt',
      line: 1,
      column: 1,
      direction: 'both',
      maxDepth: 1,
    });
    assert.equal(unsupportedCallHierarchy.response.ok, true);
    if (!unsupportedCallHierarchy.response.ok) throw new Error('Unsupported call hierarchy failed.');
    assert.equal(unsupportedCallHierarchy.response.data.available, 0);

    const unsupportedTypeHierarchy = await call('get_type_hierarchy', {
      workspaceId,
      file: 'src/unsupported.txt',
      line: 1,
      column: 1,
      direction: 'both',
      maxDepth: 1,
    });
    assert.equal(unsupportedTypeHierarchy.response.ok, true);
    if (!unsupportedTypeHierarchy.response.ok) throw new Error('Unsupported type hierarchy failed.');
    assert.equal(unsupportedTypeHierarchy.response.data.available, 0);

    const hidden = await call('document_symbols', {
      workspaceId,
      file: 'src/hidden.ts',
    });
    assert.equal(hidden.response.ok, true);
    if (!hidden.response.ok) throw new Error('Hidden document symbols failed.');
    assert.equal(hidden.response.data.results.some((candidate) =>
      candidate.path.join('.') === 'HiddenWidget' && candidate.kind === 'class'), true);

    const dirtySymbols = await call('document_symbols', {
      workspaceId,
      file: 'src/dirty.ts',
    });
    assert.equal(dirtySymbols.response.ok, true);
    if (!dirtySymbols.response.ok) throw new Error('Dirty document symbols failed.');
    assert.equal(dirtySymbols.response.data.results.some((candidate) =>
      candidate.path.join('.') === 'dirtyWidget'), true);

    const definition = await call('symbol_info', {
      workspaceId,
      file: 'src/consumer.ts',
      line: 2,
      column: 29,
    });
    assert.equal(definition.response.ok, true);
    if (!definition.response.ok) throw new Error('Known-position definition failed.');
    const knownPositionDefinition = definition.response.data.results.some((candidate) =>
      candidate.type === 'definition' && candidate.file === 'src/widget.ts');
    assert.equal(knownPositionDefinition, true);

    const dirtyDefinition = await call('symbol_info', {
      workspaceId,
      file: 'src/dirty.ts',
      line: 3,
      column: 32,
    });
    assert.equal(dirtyDefinition.response.ok, true);
    if (!dirtyDefinition.response.ok) throw new Error('Dirty definition failed.');
    const dirtyDefinitionFound = dirtyDefinition.response.data.results.some((candidate) =>
      candidate.type === 'definition' && candidate.file === 'src/widget.ts');
    assert.equal(dirtyDefinitionFound, true);

    const references = await call('get_references', {
      workspaceId,
      file: 'src/widget.ts',
      line: 1,
      column: 14,
      resultStart: 101,
      resultEnd: 120,
    });
    assert.equal(references.response.ok, true);
    if (!references.response.ok) throw new Error('Known-position references failed.');
    assert.ok(references.response.data.available >= 140);
    assert.equal(references.response.data.results.length, 20);

    const dirtyReferences = await call('get_references', {
      workspaceId,
      file: 'src/dirty.ts',
      line: 3,
      column: 32,
      resultStart: 1,
      resultEnd: 100,
    });
    assert.equal(dirtyReferences.response.ok, true);
    if (!dirtyReferences.response.ok) throw new Error('Dirty references failed.');
    const dirtyReferenceFound = dirtyReferences.response.data.results.some((candidate) =>
      candidate.file === 'src/dirty.ts' && candidate.line === 3);
    assert.equal(dirtyReferenceFound, true);

    const verifiedCandidates = await call('verify_symbol_candidates', {
      workspaceId,
      file: 'src/widget.ts',
      line: 1,
      column: 14,
      candidates: [
        { file: 'src/consumer.ts', line: 2, column: 29 },
        { file: 'src/dirty.ts', line: 3, column: 32 },
      ],
      timeoutMs: 30_000,
    });
    assert.equal(verifiedCandidates.response.ok, true);
    if (!verifiedCandidates.response.ok) throw new Error('Candidate verification failed.');
    assert.equal(verifiedCandidates.response.data.results.every((candidate) =>
      candidate.status === 'verified'), true);

    const workspaceSymbols = await call('workspace_symbols', {
      workspaceId,
      query: 'WindowSymbol',
      resultStart: 101,
      resultEnd: 120,
    });
    assert.equal(workspaceSymbols.response.ok, true);
    if (!workspaceSymbols.response.ok) throw new Error('Large workspace symbol query failed.');
    assert.ok(workspaceSymbols.response.data.available >= 140);
    assert.equal(workspaceSymbols.response.data.results.length, 20);

    const diagnostics = await call('get_diagnostics', {
      workspaceId,
      scope: 'modifiedFiles',
      includeRelatedInformation: true,
    });
    assert.equal(diagnostics.response.ok, true);
    if (!diagnostics.response.ok) throw new Error('Dirty diagnostics failed.');
    assert.equal(diagnostics.response.data.results.some((candidate) =>
      candidate.file === 'src/dirty.ts' && candidate.severity === 'error'), true);

    const semanticResponses = [
      capabilities.raw,
      unsupportedCapabilities.raw,
      callHierarchy.raw,
      typeHierarchy.raw,
      dirtyCallHierarchy.raw,
      dirtyTypeHierarchy.raw,
      unsupportedCallHierarchy.raw,
      unsupportedTypeHierarchy.raw,
      hidden.raw,
      dirtySymbols.raw,
      definition.raw,
      dirtyDefinition.raw,
      references.raw,
      dirtyReferences.raw,
      verifiedCandidates.raw,
      workspaceSymbols.raw,
      diagnostics.raw,
    ];
    semanticResponses.forEach((response) => assertNoInternalLeak(response, fixtureRoot));
    const referenceResponseBytes = responseBytes(references.raw);
    const workspaceSymbolResponseBytes = responseBytes(workspaceSymbols.raw);
    assert.ok(referenceResponseBytes < 25_000);
    assert.ok(workspaceSymbolResponseBytes < 25_000);

    process.stdout.write(JSON.stringify({
      capabilityAvailable: capabilities.response.data.available,
      capabilityWindowReturned: capabilities.response.data.results.length,
      callHierarchyAvailable: callHierarchy.response.data.available,
      callHierarchyReturned: callHierarchy.response.data.results.length,
      hiddenSymbolsReturned: hidden.response.data.results.length,
      knownPositionDefinition,
      referenceAvailable: references.response.data.available,
      referenceWindowReturned: references.response.data.results.length,
      referenceResponseBytes,
      typeHierarchyAvailable: typeHierarchy.response.data.available,
      typeHierarchyReturned: typeHierarchy.response.data.results.length,
      workspaceSymbolAvailable: workspaceSymbols.response.data.available,
      workspaceSymbolWindowReturned: workspaceSymbols.response.data.results.length,
      workspaceSymbolResponseBytes,
      diagnosticsReturned: diagnostics.response.data.results.length,
      dirtyCallHierarchyReturned: dirtyCallHierarchy.response.data.results.length,
      dirtyDefinitionFound,
      dirtyReferenceFound,
      dirtySymbolsReturned: dirtySymbols.response.data.results.length,
      dirtyTypeHierarchyReturned: dirtyTypeHierarchy.response.data.results.length,
      unsupportedCallHierarchyReturned: unsupportedCallHierarchy.response.data.available,
      unsupportedCapabilityStatus: unsupportedCapabilities.response.data.results[0]?.status,
      unsupportedCapabilityReason: unsupportedCapabilities.response.data.results[0]?.status === 'available'
        ? 'available'
        : unsupportedCapabilities.response.data.results[0]?.reason,
      unsupportedTypeHierarchyReturned: unsupportedTypeHierarchy.response.data.available,
      leakageChecksPassed: true,
    }));
  } finally {
    await client.close().catch(() => undefined);
  }
};

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.stack ?? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});
