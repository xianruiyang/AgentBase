import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import type { Position, TextDocument } from 'vscode';
import {
  DIAGNOSTICS_BRIDGE_METHOD,
  IPC_PROTOCOL_VERSION,
  REFERENCES_BRIDGE_METHOD,
  VERIFY_SYMBOL_CANDIDATES_BRIDGE_METHOD,
  createWorkspacePathContext,
  hostPathPlatform,
  parseDiagnosticsBridgeResponse,
  parseReferencesBridgeResponse,
  parseVerifySymbolCandidatesBridgeResponse,
  systemRuntimePrimitives,
  type IpcRequest,
  type JsonObject,
  type WorkspacePathAccess,
} from '@simplechat/vscode-lsp-mcp-protocol';
import {
  ReferencesDiagnosticsProviderBridge,
  type ReferencesDiagnosticsProviderHost,
} from './references-diagnostics-provider.js';

const workspaceRoot = process.platform === 'win32' ? 'D:/workspace/app' : '/workspace/app';
const sourceFile = path.join(workspaceRoot, 'src', 'widget.ts');
const baseFile = path.join(workspaceRoot, 'src', 'base.ts');
const outsideFile = process.platform === 'win32' ? 'D:/private/secret.ts' : '/private/secret.ts';
const uri = (fsPath: string) => ({ scheme: 'file', fsPath });
const point = (line: number, character: number) => ({ line, character });
const range = (startLine: number, startCharacter: number, endLine: number, endCharacter: number) => ({
  start: point(startLine, startCharacter),
  end: point(endLine, endCharacter),
});

const pathAccess: WorkspacePathAccess = {
  entryType: (value) => Promise.resolve(path.extname(value).length > 0 ? 'file' : 'directory'),
  realpath: (value) => Promise.resolve(value),
};

const context = () => createWorkspacePathContext([{
  name: 'app',
  uriScheme: 'file',
  lexicalAbsolutePath: workspaceRoot,
}], hostPathPlatform, pathAccess, systemRuntimePrimitives);

const request = (method: string, params: JsonObject): IpcRequest => ({
  protocolVersion: IPC_PROTOCOL_VERSION,
  kind: 'request',
  id: 'req_AAAAAAAAAAAAAAAAAAAAAA',
  method,
  deadlineAt: Date.now() + 10_000,
  params,
});

const document = (fsPath: string, text: string, isDirty: boolean): TextDocument => ({
  uri: uri(fsPath),
  isDirty,
  getText: () => text,
}) as unknown as TextDocument;

const richDocument = (fsPath: string, text: string, languageId = 'cpp'): TextDocument => {
  const lineStarts = [0];
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === '\n') lineStarts.push(index + 1);
  }
  const validatePosition = (value: Position): Position => {
    const line = Math.max(0, Math.min(value.line, lineStarts.length - 1));
    const start = lineStarts[line] ?? 0;
    const next = lineStarts[line + 1] ?? text.length + 1;
    const length = Math.max(0, next - start - (next <= text.length ? 1 : 0));
    return point(line, Math.max(0, Math.min(value.character, length))) as Position;
  };
  return {
    uri: uri(fsPath),
    languageId,
    isDirty: false,
    getText: () => text,
    validatePosition,
    offsetAt: (value: Position) => {
      const valid = validatePosition(value);
      return (lineStarts[valid.line] ?? 0) + valid.character;
    },
    positionAt: (rawOffset: number) => {
      const offset = Math.max(0, Math.min(rawOffset, text.length));
      let line = lineStarts.length - 1;
      while (line > 0 && (lineStarts[line] ?? 0) > offset) line -= 1;
      return point(line, offset - (lineStarts[line] ?? 0)) as Position;
    },
  } as unknown as TextDocument;
};

class FakeReadHost implements ReferencesDiagnosticsProviderHost {
  readonly calls: Array<{ readonly command: string; readonly args: readonly unknown[] }> = [];
  readonly positions: Array<{ readonly line: number; readonly character: number }> = [];
  readonly results = new Map<string, unknown>();
  readonly diagnosticResults = new Map<string, readonly unknown[]>();
  readonly sourceDocument = document(sourceFile, 'header\nconst item = new Widget();\nfooter', true);
  readonly baseDocument = document(baseFile, 'export class Widget {}', false);
  readonly globalDiagnostics: Array<readonly [unknown, readonly unknown[]]> = [];
  readonly documents = new Map<string, TextDocument>();
  readonly findCalls: Array<{
    readonly rootAbsolutePath: string;
    readonly includePattern: string;
    readonly maximumResults: number;
  }> = [];
  findResults: readonly unknown[] = [];
  providerDocumentOpenCount = 0;

  constructor() {
    this.documents.set(sourceFile, this.sourceDocument);
    this.documents.set(baseFile, this.baseDocument);
  }

  createPosition(line: number, character: number): Position {
    const value = { line, character };
    this.positions.push(value);
    return value as Position;
  }

  executeCommand(command: string, ...args: readonly unknown[]): PromiseLike<unknown> {
    this.calls.push({ command, args });
    const result = this.results.get(command);
    return Promise.resolve(typeof result === 'function'
      ? (result as (...values: readonly unknown[]) => unknown)(...args)
      : result);
  }

  findFiles(
    rootAbsolutePath: string,
    includePattern: string,
    maximumResults: number,
  ): PromiseLike<readonly unknown[]> {
    this.findCalls.push({ rootAbsolutePath, includePattern, maximumResults });
    return Promise.resolve(this.findResults);
  }

  getDiagnostics(resource?: unknown): unknown {
    if (resource === undefined) return this.globalDiagnostics;
    const fsPath = (resource as { readonly fsPath?: unknown }).fsPath;
    return typeof fsPath === 'string' ? this.diagnosticResults.get(fsPath) ?? [] : [];
  }

  getOpenDocuments(): readonly TextDocument[] {
    return [this.sourceDocument, this.baseDocument];
  }

  openTextDocument(value: string): PromiseLike<TextDocument> {
    return Promise.resolve(this.documents.get(value) ?? this.sourceDocument);
  }

  openProviderDocument(value: unknown): PromiseLike<TextDocument> {
    this.providerDocumentOpenCount += 1;
    const fsPath = (value as { readonly fsPath?: unknown }).fsPath;
    return Promise.resolve(typeof fsPath === 'string'
      ? this.documents.get(fsPath) ?? this.sourceDocument
      : this.sourceDocument);
  }

  readProviderText(value: unknown): PromiseLike<string> {
    const fsPath = (value as { readonly fsPath?: unknown }).fsPath;
    return Promise.resolve(typeof fsPath === 'string'
      ? (this.documents.get(fsPath) ?? this.sourceDocument).getText()
      : this.sourceDocument.getText());
  }
}

test('references bridge maps public provider locations without inventing declaration metadata', async () => {
  const host = new FakeReadHost();
  host.results.set('vscode.executeReferenceProvider', [
    { uri: uri(sourceFile), range: range(1, 17, 1, 23) },
    { uri: uri(sourceFile), range: range(1, 17, 1, 23) },
    { uri: uri(baseFile), range: range(0, 7, 0, 13) },
    { uri: uri(outsideFile), range: range(0, 0, 0, 1) },
  ]);
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(REFERENCES_BRIDGE_METHOD, {
    file: 'src/widget.ts',
    line: 2,
    column: 18,
    contextLines: 1,
    includeGlobs: ['src/**'],
    excludeGlobs: ['src/base.ts'],
    resultStart: 1,
    resultEnd: 1,
  }), new AbortController().signal);
  const result = parseReferencesBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates, [{
      file: 'src/widget.ts',
      line: 2,
      column: 18,
      snippet: 'header\nconst item = new Widget();\nfooter',
    }]);
    assert.deepEqual(result.warnings, ['reference_candidate_outside_workspace']);
    assert.equal(result.available, 1);
  }
  assert.deepEqual(host.calls[0]?.args, [host.sourceDocument.uri, { line: 1, character: 17 }]);
  assert.equal(host.calls.length, 1);
});

test('scoped C++ references use exact-token discovery and definition identity instead of global scan', async () => {
  const headerFile = path.join(workspaceRoot, 'Source', 'settings.h');
  const useFile = path.join(workspaceRoot, 'Source', 'settings.cpp');
  const otherSymbolFile = path.join(workspaceRoot, 'Source', 'other.cpp');
  const host = new FakeReadHost();
  host.documents.set(headerFile, richDocument(headerFile, 'GetMutable\n'));
  host.documents.set(useFile, richDocument(
    useFile,
    'GetMutable();\nGetMutable();\n// GetMutable\nconst char* text = "GetMutable";\nauto raw = R"(GetMutable)";\n',
  ));
  host.documents.set(otherSymbolFile, richDocument(otherSymbolFile, 'GetMutable();\n'));
  host.findResults = [uri(otherSymbolFile), uri(useFile), uri(headerFile)];
  host.results.set('vscode.executeDefinitionProvider', (rawUri: unknown, rawPosition: unknown) => {
    const fsPath = (rawUri as { readonly fsPath: string }).fsPath;
    const position = rawPosition as { readonly line: number };
    if (fsPath === useFile && position.line === 2) {
      return [{ uri: uri(otherSymbolFile), range: range(0, 0, 0, 10) }];
    }
    return fsPath === otherSymbolFile
      ? [{ uri: uri(otherSymbolFile), range: range(0, 0, 0, 10) }]
      : [{ uri: uri(headerFile), range: range(0, 0, 0, 10) }];
  });
  host.results.set('vscode.executeDeclarationProvider', []);
  host.results.set('vscode.executeReferenceProvider', new Error('Global references must not run.'));
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(REFERENCES_BRIDGE_METHOD, {
    file: 'Source/settings.h',
    line: 1,
    column: 1,
    contextLines: 0,
    includeGlobs: ['Source/**'],
    resultStart: 1,
    resultEnd: 100,
  }), new AbortController().signal);
  const result = parseReferencesBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.equal(result.available, 3);
    assert.deepEqual(result.candidates.map((candidate) => [
      candidate.file,
      candidate.line,
      candidate.column,
    ]), [
      ['Source/settings.cpp', 1, 1],
      ['Source/settings.cpp', 2, 1],
      ['Source/settings.h', 1, 1],
    ]);
    assert.deepEqual(result.warnings, ['references_scoped_identity_search']);
  }
  assert.equal(host.calls.some((call) => call.command === 'vscode.executeReferenceProvider'), false);
  assert.equal(host.providerDocumentOpenCount, 0);
});

test('incomplete scoped C++ proof fails fast without starting the global provider', async () => {
  const headerFile = path.join(workspaceRoot, 'Source', 'settings.h');
  const useFile = path.join(workspaceRoot, 'Source', 'settings.cpp');
  const host = new FakeReadHost();
  host.documents.set(headerFile, richDocument(headerFile, 'GetMutable\n'));
  host.documents.set(useFile, richDocument(useFile, 'GetMutable();\n'));
  host.findResults = [uri(useFile), uri(headerFile)];
  host.results.set('vscode.executeDefinitionProvider', (rawUri: unknown) =>
    (rawUri as { readonly fsPath: string }).fsPath === headerFile
      ? [{ uri: uri(headerFile), range: range(0, 0, 0, 10) }]
      : []);
  host.results.set('vscode.executeDeclarationProvider', []);
  host.results.set('vscode.executeReferenceProvider', new Error('Global references must not run.'));
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(REFERENCES_BRIDGE_METHOD, {
    file: 'Source/settings.h',
    line: 1,
    column: 1,
    contextLines: 0,
    includeGlobs: ['Source/**'],
    resultStart: 1,
    resultEnd: 100,
  }), new AbortController().signal);

  assert.deepEqual(parseReferencesBridgeResponse(raw), {
    status: 'scopedIncomplete',
    reason: 'candidateUnresolved',
  });
  assert.equal(host.calls.some((call) => call.command === 'vscode.executeReferenceProvider'), false);
});

test('candidate verification checks only supplied positions against one target identity', async () => {
  const headerFile = path.join(workspaceRoot, 'Source', 'settings.h');
  const useFile = path.join(workspaceRoot, 'Source', 'settings.cpp');
  const otherFile = path.join(workspaceRoot, 'Source', 'other.cpp');
  const host = new FakeReadHost();
  host.documents.set(headerFile, richDocument(headerFile, 'GetMutable\n'));
  host.documents.set(useFile, richDocument(useFile, 'GetMutable();\n'));
  host.documents.set(otherFile, richDocument(otherFile, 'GetMutable();\n'));
  host.results.set('vscode.executeDefinitionProvider', (rawUri: unknown) => {
    const fsPath = (rawUri as { readonly fsPath: string }).fsPath;
    return [{
      uri: uri(fsPath === otherFile ? otherFile : headerFile),
      range: range(0, 0, 0, 10),
    }];
  });
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(VERIFY_SYMBOL_CANDIDATES_BRIDGE_METHOD, {
    file: 'Source/settings.h',
    line: 1,
    column: 1,
    candidates: [
      { file: 'Source/settings.cpp', line: 1, column: 1 },
      { file: 'Source/other.cpp', line: 1, column: 1 },
    ],
    timeoutMs: 10_000,
  }), new AbortController().signal);

  assert.deepEqual(parseVerifySymbolCandidatesBridgeResponse(raw), {
    status: 'completed',
    candidates: [
      { file: 'Source/settings.cpp', line: 1, column: 1, status: 'verified' },
      { file: 'Source/other.cpp', line: 1, column: 1, status: 'mismatched' },
    ],
  });
  assert.equal(host.calls.some((call) => call.command === 'vscode.executeReferenceProvider'), false);
});

test('explicit provider mode reserves the requested budget for full semantic enumeration', async () => {
  const headerFile = path.join(workspaceRoot, 'Source', 'settings.h');
  const host = new FakeReadHost();
  host.documents.set(headerFile, richDocument(headerFile, 'GetMutable\n'));
  host.findResults = [uri(headerFile)];
  host.results.set('vscode.executeDefinitionProvider', new Error('Scoped fallback must not run.'));
  host.results.set('vscode.executeReferenceProvider', [
    { uri: uri(headerFile), range: range(0, 0, 0, 10) },
  ]);
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(REFERENCES_BRIDGE_METHOD, {
    file: 'Source/settings.h',
    line: 1,
    column: 1,
    contextLines: 0,
    includeGlobs: ['Source/**'],
    searchMode: 'provider',
    timeoutMs: 90_000,
    resultStart: 1,
    resultEnd: 100,
  }), new AbortController().signal);
  const result = parseReferencesBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  assert.equal(host.calls.some((call) => call.command === 'vscode.executeDefinitionProvider'), false);
  assert.equal(host.calls.filter((call) => call.command === 'vscode.executeReferenceProvider').length, 1);
});

test('default C++ references search the full workspace candidate set without a global provider scan', async () => {
  const headerFile = path.join(workspaceRoot, 'Source', 'settings.h');
  const useFile = path.join(workspaceRoot, 'Source', 'settings.cpp');
  const host = new FakeReadHost();
  host.documents.set(headerFile, richDocument(headerFile, 'GetMutable\n'));
  host.documents.set(useFile, richDocument(useFile, 'GetMutable();\n'));
  host.findResults = [uri(useFile), uri(headerFile)];
  host.results.set('vscode.executeDefinitionProvider', [{
    uri: uri(headerFile),
    range: range(0, 0, 0, 10),
  }]);
  host.results.set('vscode.executeReferenceProvider', new Error('Global references must not run.'));
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(REFERENCES_BRIDGE_METHOD, {
    file: 'Source/settings.h',
    line: 1,
    column: 1,
    contextLines: 0,
    resultStart: 1,
    resultEnd: 100,
  }), new AbortController().signal);
  const result = parseReferencesBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.equal(result.available, 2);
    assert.deepEqual(result.warnings, ['references_fast_workspace_identity_search']);
  }
  assert.deepEqual(host.findCalls.map((call) => call.includePattern), [
    '**/*.{c,cc,cpp,cxx,m,mm,h,hh,hpp,hxx,inl,inc,ipp,tpp,txx,ixx,cppm}',
  ]);
  assert.equal(host.calls.some((call) => call.command === 'vscode.executeReferenceProvider'), false);
});

test('scopePaths expand logical files or directories without requiring glob syntax', async () => {
  const headerFile = path.join(workspaceRoot, 'Source', 'Feature', 'settings.h');
  const host = new FakeReadHost();
  host.documents.set(headerFile, richDocument(headerFile, 'GetMutable\n'));
  host.findResults = [uri(headerFile)];
  host.results.set('vscode.executeDefinitionProvider', [{
    uri: uri(headerFile),
    range: range(0, 0, 0, 10),
  }]);
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(REFERENCES_BRIDGE_METHOD, {
    file: 'Source/Feature/settings.h',
    line: 1,
    column: 1,
    contextLines: 0,
    searchMode: 'scoped',
    scopePaths: ['Source/Feature'],
    resultStart: 1,
    resultEnd: 100,
  }), new AbortController().signal);
  const result = parseReferencesBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates.map((candidate) => candidate.file), [
      'Source/Feature/settings.h',
    ]);
    assert.deepEqual(result.warnings, ['references_scoped_identity_search']);
  }
  assert.deepEqual(host.findCalls.map((call) => call.includePattern), [
    'Source/Feature',
    'Source/Feature/**',
  ]);
});

test('diagnostics bridge maps files scope, tags, code, and safe related information', async () => {
  const host = new FakeReadHost();
  host.diagnosticResults.set(sourceFile, [{
    range: range(1, 6, 1, 10),
    severity: 1,
    message: ' Deprecated use.\r\n',
    code: { value: 6385, target: uri(outsideFile) },
    source: 'typescript',
    tags: [2, 2, 99],
    relatedInformation: [
      {
        location: { uri: uri(baseFile), range: range(0, 7, 0, 13) },
        message: ' Declared here. ',
      },
      {
        location: { uri: uri(outsideFile), range: range(0, 0, 0, 1) },
        message: 'Private source.',
      },
    ],
  }]);
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(DIAGNOSTICS_BRIDGE_METHOD, {
    scope: 'files',
    files: ['src/widget.ts'],
    includeRelatedInformation: true,
  }), new AbortController().signal);
  const result = parseDiagnosticsBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates, [{
      file: 'src/widget.ts',
      range: { startLine: 2, startColumn: 7, endLine: 2, endColumn: 11 },
      severity: 'warning',
      message: 'Deprecated use.',
      code: 6385,
      source: 'typescript',
      tags: ['deprecated'],
      relatedInformation: [{
        file: 'src/base.ts',
        range: { startLine: 1, startColumn: 8, endLine: 1, endColumn: 14 },
        message: 'Declared here.',
      }],
    }]);
    assert.deepEqual(result.warnings, ['diagnostic_related_information_outside_workspace']);
  }
});

test('diagnostics modifiedFiles consumes only dirty open documents without workspace traversal', async () => {
  const host = new FakeReadHost();
  host.diagnosticResults.set(sourceFile, [{
    range: range(0, 0, 0, 6),
    severity: 0,
    message: 'Broken header.',
  }]);
  host.diagnosticResults.set(baseFile, [{
    range: range(0, 0, 0, 6),
    severity: 2,
    message: 'Clean file diagnostic.',
  }]);
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(DIAGNOSTICS_BRIDGE_METHOD, {
    scope: 'modifiedFiles',
    includeRelatedInformation: false,
  }), new AbortController().signal);
  const result = parseDiagnosticsBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates.map(({ file, message }) => ({ file, message })), [{
      file: 'src/widget.ts',
      message: 'Broken header.',
    }]);
  }
});

test('diagnostics workspace scope consumes published tuples and excludes other workspaces', async () => {
  const host = new FakeReadHost();
  host.globalDiagnostics.push(
    [uri(outsideFile), [{ range: range(0, 0, 0, 1), severity: 0, message: 'Private.' }]],
    [uri(baseFile), [{ range: range(0, 7, 0, 13), severity: 2, message: 'Workspace info.' }]],
  );
  const bridge = new ReferencesDiagnosticsProviderBridge(host, pathAccess);
  const raw = await bridge.handle(await context(), request(DIAGNOSTICS_BRIDGE_METHOD, {
    scope: 'workspace',
    includeRelatedInformation: false,
  }), new AbortController().signal);
  const result = parseDiagnosticsBridgeResponse(raw);

  assert.equal(result.status, 'completed');
  if (result.status === 'completed') {
    assert.deepEqual(result.candidates, [{
      file: 'src/base.ts',
      range: { startLine: 1, startColumn: 8, endLine: 1, endColumn: 14 },
      severity: 'information',
      message: 'Workspace info.',
    }]);
  }
});
