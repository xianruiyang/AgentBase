import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ProtocolCodecError,
  ProtocolValidationError,
  decodeYamlText,
  encodeToolResponse,
  toDeterministicYaml,
  toStrictJson,
  truncateUnicodeCodePoints,
  type ToolResponseMap,
} from './index.js';

const renameResponse: ToolResponseMap['rename_preview'] = {
  ok: true,
  data: {
    previewId: 'pv_example',
    changes: [
      {
        kind: 'text',
        file: 'src/emoji.ts',
        edits: [
          {
            range: {
              startLine: 1,
              startColumn: 1,
              endLine: 2,
              endColumn: 3,
            },
            oldText: 'first line\nsecond 😀 line',
            newText: 'replacement\nkeeps surrogate 😀 intact',
          },
        ],
      },
    ],
  },
};

test('one validated DTO produces deterministic semantic-equivalent JSON and YAML', () => {
  const first = encodeToolResponse('rename_preview', renameResponse);
  const second = encodeToolResponse('rename_preview', renameResponse);

  assert.equal(first.content[0].text, second.content[0].text);
  assert.deepEqual(decodeYamlText(first.content[0].text), first.structuredContent);
  assert.equal(toStrictJson(first.structuredContent), toStrictJson(decodeYamlText(first.content[0].text)));
  assert.ok(Object.isFrozen(first.structuredContent));
  assert.equal(first.structuredContent.ok, true);
  if (!first.structuredContent.ok) {
    throw new Error('Expected the rename preview success envelope.');
  }
  assert.ok(Object.isFrozen(first.structuredContent.data));
  assert.ok(Object.isFrozen(first.structuredContent.data.changes));
  assert.ok(Object.isFrozen(first.structuredContent.data.changes[0]));
  assert.match(first.content[0].text, /oldText: \|/u);
  assert.match(first.content[0].text, /newText: \|/u);
  assert.match(first.content[0].text, /😀/u);
  assert.doesNotMatch(first.content[0].text, /(?:^|\s)[&*][A-Za-z0-9]/mu);
  assert.doesNotMatch(first.content[0].text, /!!|^\s*<<:/mu);
});

test('YAML decoder rejects aliases, anchors, tags, merge keys, and duplicate keys', () => {
  const invalidDocuments = [
    'a: &anchor\n  value: 1\nb: *anchor\n',
    'a: !!str value\n',
    '<<: { value: 1 }\n',
    'a: 1\na: 2\n',
  ];

  for (const document of invalidDocuments) {
    assert.throws(() => decodeYamlText(document), ProtocolCodecError, document);
  }
});

test('YAML serialization quotes ambiguous scalars without changing their JSON meaning', () => {
  const source = {
    values: ['true', 'false', 'null', '~', '0123', '1e3', '2026-07-15'],
  };
  const text = toDeterministicYaml(source);
  assert.deepEqual(decodeYamlText(text), source);
  for (const value of ['true', 'false', 'null', '~', '0123']) {
    assert.match(text, new RegExp(`[- ]+["']${value}["']`, 'u'));
  }
});

test('strict JSON canonicalization rejects non-JSON values and cycles', () => {
  assert.throws(() => toStrictJson({ value: Number.NaN }), ProtocolCodecError);
  assert.throws(() => toStrictJson({ value: 1n }), ProtocolCodecError);
  const cyclic: Record<string, unknown> = {};
  cyclic.self = cyclic;
  assert.throws(() => toStrictJson(cyclic), ProtocolCodecError);
});

test('encoder validates output before serializing and cannot leak private fields', () => {
  assert.throws(
    () =>
      encodeToolResponse('rename_preview', {
        ok: true,
        data: {
          changes: [],
          warnings: [],
        },
      } as unknown as ToolResponseMap['rename_preview']),
    ProtocolValidationError,
  );
  assert.throws(
    () =>
      encodeToolResponse('rename_preview', {
        ...renameResponse,
        internalUri: 'file:///C:/secret.ts',
      } as unknown as ToolResponseMap['rename_preview']),
    ProtocolValidationError,
  );
});

test('command result JSON and multiline output round-trip without invented task output', () => {
  const jsonResult = encodeToolResponse('execute_command', {
    ok: true,
    data: {
      result: {
        count: 0,
        nested: [false, null, 'kept because these are command payload values'],
      },
    },
  });
  assert.deepEqual(decodeYamlText(jsonResult.content[0].text), jsonResult.structuredContent);

  const outputResult = encodeToolResponse('execute_command', {
    ok: true,
    data: {
      output: 'line one\nline two 😀',
      outputTruncated: true,
    },
  });
  assert.match(outputResult.content[0].text, /output: \|/u);
  assert.deepEqual(decodeYamlText(outputResult.content[0].text), outputResult.structuredContent);

  const taskResult = encodeToolResponse('execute_command', { ok: true, data: {} });
  assert.deepEqual(taskResult.structuredContent, { data: {}, ok: true });

  const failedTaskResult = encodeToolResponse('execute_command', {
    ok: false,
    error: {
      code: 'COMMAND_FAILED',
      message: 'The task process exited with a non-zero status.',
      retryable: false,
      details: {
        targetKind: 'task',
        reason: 'nonZeroExit',
        outcome: 'failed',
        exitCode: 7,
        outputLog: {
          path: '.vscode-lsp-mcp/task-logs/failed.log',
          lineCount: 2,
          byteCount: 39,
          encoding: 'utf-8',
          truncated: false,
        },
      },
    },
  });
  assert.deepEqual(decodeYamlText(failedTaskResult.content[0].text), failedTaskResult.structuredContent);
});

test('Unicode truncation counts code points rather than UTF-16 code units', () => {
  assert.deepEqual(truncateUnicodeCodePoints('A😀B', 2), {
    value: 'A😀',
    truncated: true,
  });
  assert.deepEqual(truncateUnicodeCodePoints('A😀B', 3), {
    value: 'A😀B',
    truncated: false,
  });
  assert.equal(toDeterministicYaml({ output: truncateUnicodeCodePoints('A😀B', 2).value }).includes('😀'), true);
  assert.throws(() => truncateUnicodeCodePoints('text', -1), RangeError);
});
