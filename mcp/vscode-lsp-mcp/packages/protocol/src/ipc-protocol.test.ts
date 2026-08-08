import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  IPC_MAX_PAYLOAD_BYTES,
  IPC_PROTOCOL_VERSION,
  IpcFrameDecoder,
  IpcProtocolError,
  constantTimeAuthTokenEquals,
  createAuthToken,
  createInstanceId,
  createWorkspaceId,
  decodeIpcPayload,
  encodeFramePayload,
  encodeIpcMessage,
  type IpcMessage,
  type IpcRequest,
  type RuntimePrimitives,
} from './index.js';

const primitives = (): RuntimePrimitives => {
  let value = 0;
  return {
    monotonicNowMs: () => 0,
    secureRandomBytes: (length) => new Uint8Array(length).fill(++value),
    sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
  };
};

const request = (): IpcRequest => ({
  protocolVersion: IPC_PROTOCOL_VERSION,
  kind: 'request',
  id: 'request_1',
  method: 'symbol.search',
  deadlineAt: Date.now() + 10_000,
  params: { text: '中文\nmultiline 🚀' },
});

const rawFrame = (text: string): Uint8Array => encodeFramePayload(Buffer.from(text, 'utf8'));

test('length-prefixed frames preserve Unicode, multiline text, fragmentation, and coalescing', () => {
  const firstMessage = request();
  const first = encodeIpcMessage(firstMessage);
  const second = encodeIpcMessage({ ...request(), id: 'request_2' });
  const decoder = new IpcFrameDecoder();
  const messages: IpcMessage[] = [];
  for (const byte of Buffer.concat([first, second])) {
    messages.push(...decoder.push(Uint8Array.of(byte)));
  }
  decoder.finish();
  assert.equal(messages.length, 2);
  assert.deepEqual(messages[0], firstMessage);
  assert.equal(messages[1]?.kind, 'request');
  assert.equal(messages[1]?.kind === 'request' ? messages[1].params.text : undefined, '中文\nmultiline 🚀');
});

test('strict decoder rejects duplicate keys, trailing data, invalid UTF-8, and unknown fields', () => {
  const valid = JSON.stringify(request());
  const duplicate = valid.replace('"kind":"request"', '"kind":"request","kind":"cancel"');
  assert.throws(() => new IpcFrameDecoder().push(rawFrame(duplicate)), (error: unknown) =>
    error instanceof IpcProtocolError && error.reason === 'duplicateKey');
  assert.throws(() => decodeIpcPayload(Buffer.from(`${valid} true`)), (error: unknown) =>
    error instanceof IpcProtocolError && error.reason === 'invalidJson');
  assert.throws(() => decodeIpcPayload(Uint8Array.of(0xc3, 0x28)), (error: unknown) =>
    error instanceof IpcProtocolError && error.reason === 'invalidUtf8');
  assert.throws(() => decodeIpcPayload(Buffer.from(JSON.stringify({ ...request(), extra: true }))),
    (error: unknown) => error instanceof IpcProtocolError && error.reason === 'invalidMessage');
});

test('frame bounds and truncation fail closed independently of newline content', () => {
  assert.equal(encodeFramePayload(new Uint8Array(IPC_MAX_PAYLOAD_BYTES)).byteLength, IPC_MAX_PAYLOAD_BYTES + 4);
  assert.throws(() => encodeFramePayload(new Uint8Array(IPC_MAX_PAYLOAD_BYTES + 1)), (error: unknown) =>
    error instanceof IpcProtocolError && error.reason === 'frameLength');
  assert.throws(() => encodeFramePayload(new Uint8Array()), (error: unknown) =>
    error instanceof IpcProtocolError && error.reason === 'frameLength');
  const decoder = new IpcFrameDecoder();
  decoder.push(encodeIpcMessage(request()).subarray(0, 7));
  assert.throws(() => decoder.finish(), (error: unknown) =>
    error instanceof IpcProtocolError && error.reason === 'truncatedFrame');
});

test('authentication tokens are canonical 32-byte base64url and compared exactly', () => {
  const source = primitives();
  const token = createAuthToken(source);
  assert.equal(token.length, 43);
  assert.equal(constantTimeAuthTokenEquals(token, token), true);
  assert.equal(constantTimeAuthTokenEquals(token, `${token.slice(0, -1)}A`), false);
  assert.equal(constantTimeAuthTokenEquals(token, 'not-a-token'), false);
});

test('hello identity includes instance, workspace, generation, token, and nonce', () => {
  const source = primitives();
  const hello: IpcMessage = {
    protocolVersion: IPC_PROTOCOL_VERSION,
    kind: 'hello',
    instanceId: createInstanceId(source),
    workspaceId: createWorkspaceId(source),
    workspaceGeneration: 3,
    token: createAuthToken(source),
    nonce: 'AQEBAQEBAQEBAQEBAQEBAQ',
  };
  const decoder = new IpcFrameDecoder();
  assert.deepEqual(decoder.push(encodeIpcMessage(hello)), [hello]);
});
