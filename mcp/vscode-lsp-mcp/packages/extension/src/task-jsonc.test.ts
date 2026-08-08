import assert from 'node:assert/strict';
import test from 'node:test';
import {
  MAX_TASK_CONFIGURATION_CHARS,
  TaskJsoncError,
  parseTaskJsonc,
} from './task-jsonc.js';

test('task JSONC accepts comments and trailing commas without changing string content', () => {
  const parsed = parseTaskJsonc(`{
    // task list
    "tasks": [
      { "label": "build", "command": "literal // not a comment", },
    ],
    /* bounded inputs */
    "inputs": [],
  }`);
  assert.deepEqual(JSON.parse(JSON.stringify(parsed)), {
    tasks: [{ label: 'build', command: 'literal // not a comment' }],
    inputs: [],
  });
});

test('task JSONC rejects duplicate keys, malformed comments, and excessive input', () => {
  for (const value of [
    '{ "tasks": [], "tasks": [] }',
    '{ /* unterminated',
    '{ "tasks": [01] }',
    '[] trailing',
  ]) {
    assert.throws(() => parseTaskJsonc(value), TaskJsoncError);
  }
  assert.throws(
    () => parseTaskJsonc(' '.repeat(MAX_TASK_CONFIGURATION_CHARS + 1)),
    TaskJsoncError,
  );
});
