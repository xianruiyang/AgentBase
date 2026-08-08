import assert from 'node:assert/strict';
import test from 'node:test';
import {
  normalizeCapturedTaskOutput,
  taskOutputLineCount,
} from './task-output-capture.js';

test('captured task output is readable UTF-8 with ANSI and carriage-return progress removed', () => {
  const raw = Buffer.from('\u001b[31mcompile error\u001b[0m\r\nprogress 1\rprogress 2\n', 'utf8');
  const normalized = normalizeCapturedTaskOutput(raw);
  assert.equal(normalized, 'compile error\nprogress 1\nprogress 2\n');
  assert.equal(taskOutputLineCount(normalized), 3);
  assert.equal(taskOutputLineCount('unterminated final line'), 1);
  assert.equal(taskOutputLineCount(''), 0);
});
