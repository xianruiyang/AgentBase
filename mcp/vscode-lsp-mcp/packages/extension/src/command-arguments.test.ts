import assert from 'node:assert/strict';
import test from 'node:test';
import type {
  InternalWorkspaceRoot,
  JsonSchema,
  RootAlias,
  WorkspacePathAccess,
  WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';
import { resolveCommandArguments } from './command-arguments.js';

const root: InternalWorkspaceRoot = {
  alias: 'root' as RootAlias,
  name: 'root',
  folderIndex: 0,
  lexicalAbsolutePath: 'C:\\workspace',
  canonicalAbsolutePath: 'C:\\workspace',
  lexicalComparisonKey: 'c:\\workspace',
  canonicalComparisonKey: 'c:\\workspace',
};
const context: WorkspacePathContext = { platform: 'win32', roots: [root] };
const access: WorkspacePathAccess = {
  entryType: () => Promise.resolve('file'),
  realpath: (value) => Promise.resolve(value),
};
const uri = { file: (value: string) => `uri:${value}` };

test('command argument resolution follows local refs and nested closed-object properties', async () => {
  const schema: JsonSchema = {
    type: 'array',
    items: { $ref: '#/$defs/item' },
    $defs: {
      item: {
        type: 'object',
        properties: {
          file: {
            type: 'string',
            'x-vscode-lsp-mcp-logicalPath': true,
          },
          label: { type: 'string' },
        },
        required: ['file', 'label'],
        additionalProperties: false,
      },
    },
  };
  assert.deepEqual(await resolveCommandArguments(
    [{ file: 'src/a.ts', label: 'keep' }],
    schema,
    context,
    access,
    uri,
  ), [{ file: 'uri:C:\\workspace\\src\\a.ts', label: 'keep' }]);
});

test('command argument resolution rejects ambiguous conditional logical-path annotations', async () => {
  const schema: JsonSchema = {
    type: 'array',
    items: {
      oneOf: [
        { type: 'string', 'x-vscode-lsp-mcp-logicalPath': true },
        { type: 'string' },
      ],
    },
  };
  await assert.rejects(
    resolveCommandArguments(['src/a.ts'], schema, context, access, uri),
    /conditional schema keyword oneOf/u,
  );
});

test('command argument resolution preserves Uri object identity through allOf traversal', async () => {
  const uriValue = Object.freeze({ uriBrand: true, fsPath: 'C:\\workspace\\src\\a.ts' });
  const schema: JsonSchema = {
    type: 'array',
    items: {
      type: 'object',
      allOf: [{
        properties: {
          file: {
            type: 'string',
            'x-vscode-lsp-mcp-logicalPath': true,
          },
        },
      }],
      properties: { file: {} },
      required: ['file'],
      additionalProperties: false,
    },
  };
  const result = await resolveCommandArguments(
    [{ file: 'src/a.ts' }],
    schema,
    context,
    access,
    { file: () => uriValue },
  );
  assert.equal((result[0] as { readonly file: unknown }).file, uriValue);
});
