import { Buffer } from 'node:buffer';
import { timingSafeEqual } from 'node:crypto';
import type { JsonObject, JsonValue } from './dto.js';
import type { RuntimePrimitives } from './runtime.js';
import { isInstanceId, isWorkspaceId, type InstanceId, type WorkspaceId } from './workspace-identity.js';

export const IPC_PROTOCOL_VERSION = '2.0' as const;
export const IPC_MAX_PAYLOAD_BYTES = 16_777_216;
// A busy Extension Host can be temporarily delayed by workspace indexing. Keep
// discovery bounded while allowing enough time for the local handshake and the
// lightweight health handler to reach the event loop.
export const IPC_HELLO_TIMEOUT_MS = 5_000;
export const IPC_HEALTH_TIMEOUT_MS = 10_000;
export const IPC_DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
export const IPC_MAX_REQUEST_TIMEOUT_MS = 610_000;
export const IPC_RECONNECT_DELAYS_MS = Object.freeze([100, 250, 500, 1_000] as const);

export type IpcProtocolVersion = typeof IPC_PROTOCOL_VERSION;

export interface IpcHello {
  readonly protocolVersion: IpcProtocolVersion;
  readonly kind: 'hello';
  readonly instanceId: InstanceId;
  readonly workspaceId: WorkspaceId;
  readonly workspaceGeneration: number;
  readonly token: string;
  readonly nonce: string;
}

export interface IpcHelloAck {
  readonly protocolVersion: IpcProtocolVersion;
  readonly kind: 'helloAck';
  readonly instanceId: InstanceId;
  readonly workspaceId: WorkspaceId;
  readonly workspaceGeneration: number;
  readonly nonce: string;
}

export interface IpcRequest {
  readonly protocolVersion: IpcProtocolVersion;
  readonly kind: 'request';
  readonly id: string;
  readonly method: string;
  readonly deadlineAt: number;
  readonly params: JsonObject;
}

export interface IpcResponseSuccess {
  readonly protocolVersion: IpcProtocolVersion;
  readonly kind: 'response';
  readonly id: string;
  readonly ok: true;
  readonly result: JsonValue;
}

export interface IpcResponseFailure {
  readonly protocolVersion: IpcProtocolVersion;
  readonly kind: 'response';
  readonly id: string;
  readonly ok: false;
  readonly error: {
    readonly code: string;
    readonly message: string;
  };
}

export type IpcResponse = IpcResponseSuccess | IpcResponseFailure;

export interface IpcCancel {
  readonly protocolVersion: IpcProtocolVersion;
  readonly kind: 'cancel';
  readonly id: string;
}

export type IpcMessage = IpcHello | IpcHelloAck | IpcRequest | IpcResponse | IpcCancel;

export class IpcProtocolError extends Error {
  readonly reason:
    | 'duplicateKey'
    | 'frameLength'
    | 'invalidJson'
    | 'invalidMessage'
    | 'invalidUtf8'
    | 'truncatedFrame';

  constructor(reason: IpcProtocolError['reason'], message: string) {
    super(message);
    this.name = 'IpcProtocolError';
    this.reason = reason;
  }
}

class StrictJsonParser {
  readonly #text: string;
  #index = 0;
  #entries = 0;

  constructor(text: string) {
    this.#text = text;
  }

  parse(): JsonValue {
    this.#skipWhitespace();
    const value = this.#parseValue(0);
    this.#skipWhitespace();
    if (this.#index !== this.#text.length) {
      this.#invalid('JSON contains trailing data.');
    }
    return value;
  }

  #invalid(message: string): never {
    throw new IpcProtocolError('invalidJson', message);
  }

  #skipWhitespace(): void {
    while (this.#index < this.#text.length) {
      const character = this.#text[this.#index];
      if (character !== ' ' && character !== '\n' && character !== '\r' && character !== '\t') {
        break;
      }
      this.#index += 1;
    }
  }

  #parseValue(depth: number): JsonValue {
    if (depth > 64) {
      this.#invalid('JSON nesting exceeds the protocol limit.');
    }
    const character = this.#text[this.#index];
    if (character === '{') {
      return this.#parseObject(depth + 1);
    }
    if (character === '[') {
      return this.#parseArray(depth + 1);
    }
    if (character === '"') {
      return this.#parseString();
    }
    if (character === 't' && this.#consumeLiteral('true')) {
      return true;
    }
    if (character === 'f' && this.#consumeLiteral('false')) {
      return false;
    }
    if (character === 'n' && this.#consumeLiteral('null')) {
      return null;
    }
    return this.#parseNumber();
  }

  #consumeLiteral(literal: string): boolean {
    if (!this.#text.startsWith(literal, this.#index)) {
      return false;
    }
    this.#index += literal.length;
    return true;
  }

  #countEntry(): void {
    this.#entries += 1;
    if (this.#entries > 100_000) {
      this.#invalid('JSON collection entries exceed the protocol limit.');
    }
  }

  #parseObject(depth: number): JsonObject {
    this.#index += 1;
    this.#skipWhitespace();
    const result: Record<string, JsonValue> = {};
    const keys = new Set<string>();
    if (this.#text[this.#index] === '}') {
      this.#index += 1;
      return result;
    }
    while (this.#index < this.#text.length) {
      if (this.#text[this.#index] !== '"') {
        this.#invalid('JSON object keys must be strings.');
      }
      const key = this.#parseString();
      if (keys.has(key)) {
        throw new IpcProtocolError('duplicateKey', 'JSON contains a duplicate object key.');
      }
      keys.add(key);
      this.#skipWhitespace();
      if (this.#text[this.#index] !== ':') {
        this.#invalid('JSON object key is missing a colon.');
      }
      this.#index += 1;
      this.#skipWhitespace();
      result[key] = this.#parseValue(depth);
      this.#countEntry();
      this.#skipWhitespace();
      const separator = this.#text[this.#index];
      this.#index += 1;
      if (separator === '}') {
        return result;
      }
      if (separator !== ',') {
        this.#invalid('JSON object is missing a comma or closing brace.');
      }
      this.#skipWhitespace();
    }
    return this.#invalid('JSON object is truncated.');
  }

  #parseArray(depth: number): readonly JsonValue[] {
    this.#index += 1;
    this.#skipWhitespace();
    const result: JsonValue[] = [];
    if (this.#text[this.#index] === ']') {
      this.#index += 1;
      return result;
    }
    while (this.#index < this.#text.length) {
      result.push(this.#parseValue(depth));
      this.#countEntry();
      this.#skipWhitespace();
      const separator = this.#text[this.#index];
      this.#index += 1;
      if (separator === ']') {
        return result;
      }
      if (separator !== ',') {
        this.#invalid('JSON array is missing a comma or closing bracket.');
      }
      this.#skipWhitespace();
    }
    return this.#invalid('JSON array is truncated.');
  }

  #parseString(): string {
    const start = this.#index;
    this.#index += 1;
    while (this.#index < this.#text.length) {
      const code = this.#text.charCodeAt(this.#index);
      if (code === 0x22) {
        this.#index += 1;
        let value: string;
        try {
          value = JSON.parse(this.#text.slice(start, this.#index)) as string;
        } catch {
          return this.#invalid('JSON string escape is invalid.');
        }
        if (hasUnpairedSurrogate(value)) {
          this.#invalid('JSON strings must not contain unpaired surrogates.');
        }
        return value;
      }
      if (code < 0x20) {
        this.#invalid('JSON strings must not contain control characters.');
      }
      if (code === 0x5c) {
        this.#index += 1;
        const escape = this.#text[this.#index];
        if (escape === 'u') {
          const hex = this.#text.slice(this.#index + 1, this.#index + 5);
          if (!/^[0-9A-Fa-f]{4}$/u.test(hex)) {
            this.#invalid('JSON unicode escape is invalid.');
          }
          this.#index += 5;
          continue;
        }
        if (escape === undefined || !'"\\/bfnrt'.includes(escape)) {
          this.#invalid('JSON string escape is invalid.');
        }
      }
      this.#index += 1;
    }
    return this.#invalid('JSON string is truncated.');
  }

  #parseNumber(): number {
    const remaining = this.#text.slice(this.#index);
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/u.exec(remaining);
    if (match === null) {
      return this.#invalid('JSON value is invalid.');
    }
    this.#index += match[0].length;
    const value = Number(match[0]);
    if (!Number.isFinite(value)) {
      this.#invalid('JSON number must be finite.');
    }
    return value;
  }
}

const hasUnpairedSurrogate = (value: string): boolean => {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        return true;
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return true;
    }
  }
  return false;
};

export const parseStrictJson = (text: string): JsonValue => new StrictJsonParser(text).parse();

const asObject = (value: JsonValue): JsonObject => {
  if (value === null || Array.isArray(value) || typeof value !== 'object') {
    throw new IpcProtocolError('invalidMessage', 'IPC payload must be a JSON object.');
  }
  return value as JsonObject;
};

const exactKeys = (
  object: JsonObject,
  required: readonly string[],
  optional: readonly string[] = [],
): void => {
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(object);
  if (required.some((key) => !(key in object)) || keys.some((key) => !allowed.has(key))) {
    throw new IpcProtocolError('invalidMessage', 'IPC message fields do not match its discriminant.');
  }
};

const stringField = (object: JsonObject, key: string, maximum = 256): string => {
  const value = object[key];
  if (typeof value !== 'string' || value.length === 0 || value.length > maximum) {
    throw new IpcProtocolError('invalidMessage', `IPC ${key} must be a bounded non-empty string.`);
  }
  return value;
};

const idField = (object: JsonObject, key: string): string => {
  const value = stringField(object, key, 128);
  if (!/^[A-Za-z0-9_-]+$/u.test(value)) {
    throw new IpcProtocolError('invalidMessage', `IPC ${key} must be base64url text.`);
  }
  return value;
};

const positiveSafeIntegerField = (object: JsonObject, key: string): number => {
  const value = object[key];
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) {
    throw new IpcProtocolError('invalidMessage', `IPC ${key} must be a positive safe integer.`);
  }
  return value;
};

const protocolVersionField = (object: JsonObject): IpcProtocolVersion => {
  if (object.protocolVersion !== IPC_PROTOCOL_VERSION) {
    throw new IpcProtocolError('invalidMessage', 'IPC protocol version is not supported.');
  }
  return IPC_PROTOCOL_VERSION;
};

const identityFields = (object: JsonObject): {
  readonly instanceId: InstanceId;
  readonly workspaceGeneration: number;
  readonly workspaceId: WorkspaceId;
} => {
  const instanceId = stringField(object, 'instanceId', 36);
  const workspaceId = stringField(object, 'workspaceId', 25);
  if (!isInstanceId(instanceId) || !isWorkspaceId(workspaceId)) {
    throw new IpcProtocolError('invalidMessage', 'IPC identity is malformed.');
  }
  return {
    instanceId,
    workspaceId,
    workspaceGeneration: positiveSafeIntegerField(object, 'workspaceGeneration'),
  };
};

export const assertAuthToken = (token: string): void => {
  if (!/^[A-Za-z0-9_-]{43}$/u.test(token)) {
    throw new IpcProtocolError('invalidMessage', 'IPC token is malformed.');
  }
  let decoded: Buffer;
  try {
    decoded = Buffer.from(token, 'base64url');
  } catch {
    throw new IpcProtocolError('invalidMessage', 'IPC token is malformed.');
  }
  if (decoded.byteLength !== 32 || decoded.toString('base64url') !== token) {
    throw new IpcProtocolError('invalidMessage', 'IPC token is malformed.');
  }
};

export const validateIpcMessage = (value: JsonValue): IpcMessage => {
  const object = asObject(value);
  protocolVersionField(object);
  const kind = stringField(object, 'kind', 16);
  if (kind === 'hello') {
    exactKeys(object, ['protocolVersion', 'kind', 'instanceId', 'workspaceId', 'workspaceGeneration', 'token', 'nonce']);
    const identity = identityFields(object);
    const token = stringField(object, 'token', 43);
    assertAuthToken(token);
    return Object.freeze({
      protocolVersion: IPC_PROTOCOL_VERSION,
      kind,
      ...identity,
      token,
      nonce: idField(object, 'nonce'),
    });
  }
  if (kind === 'helloAck') {
    exactKeys(object, ['protocolVersion', 'kind', 'instanceId', 'workspaceId', 'workspaceGeneration', 'nonce']);
    return Object.freeze({
      protocolVersion: IPC_PROTOCOL_VERSION,
      kind,
      ...identityFields(object),
      nonce: idField(object, 'nonce'),
    });
  }
  if (kind === 'request') {
    exactKeys(object, ['protocolVersion', 'kind', 'id', 'method', 'deadlineAt', 'params']);
    const method = stringField(object, 'method', 128);
    if (!/^[A-Za-z][A-Za-z0-9_.-]*$/u.test(method)) {
      throw new IpcProtocolError('invalidMessage', 'IPC method is malformed.');
    }
    return Object.freeze({
      protocolVersion: IPC_PROTOCOL_VERSION,
      kind,
      id: idField(object, 'id'),
      method,
      deadlineAt: positiveSafeIntegerField(object, 'deadlineAt'),
      params: asObject(object.params ?? null),
    });
  }
  if (kind === 'response') {
    const id = idField(object, 'id');
    if (object.ok === true) {
      exactKeys(object, ['protocolVersion', 'kind', 'id', 'ok', 'result']);
      return Object.freeze({
        protocolVersion: IPC_PROTOCOL_VERSION,
        kind,
        id,
        ok: true,
        result: object.result ?? null,
      });
    }
    if (object.ok === false) {
      exactKeys(object, ['protocolVersion', 'kind', 'id', 'ok', 'error']);
      const error = asObject(object.error ?? null);
      exactKeys(error, ['code', 'message']);
      return Object.freeze({
        protocolVersion: IPC_PROTOCOL_VERSION,
        kind,
        id,
        ok: false,
        error: Object.freeze({
          code: stringField(error, 'code', 64),
          message: stringField(error, 'message', 1_024),
        }),
      });
    }
    throw new IpcProtocolError('invalidMessage', 'IPC response ok must be boolean.');
  }
  if (kind === 'cancel') {
    exactKeys(object, ['protocolVersion', 'kind', 'id']);
    return Object.freeze({
      protocolVersion: IPC_PROTOCOL_VERSION,
      kind,
      id: idField(object, 'id'),
    });
  }
  throw new IpcProtocolError('invalidMessage', 'IPC message discriminant is unknown.');
};

export const decodeIpcPayload = (payload: Uint8Array): IpcMessage => {
  if (payload.byteLength < 1 || payload.byteLength > IPC_MAX_PAYLOAD_BYTES) {
    throw new IpcProtocolError('frameLength', 'IPC frame payload length is invalid.');
  }
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(payload);
  } catch {
    throw new IpcProtocolError('invalidUtf8', 'IPC payload is not strict UTF-8.');
  }
  return validateIpcMessage(parseStrictJson(text));
};

export const encodeFramePayload = (payload: Uint8Array): Uint8Array => {
  if (payload.byteLength < 1 || payload.byteLength > IPC_MAX_PAYLOAD_BYTES) {
    throw new IpcProtocolError('frameLength', 'IPC frame payload length is invalid.');
  }
  const frame = Buffer.allocUnsafe(4 + payload.byteLength);
  frame.writeUInt32BE(payload.byteLength, 0);
  Buffer.from(payload).copy(frame, 4);
  return frame;
};

export const encodeIpcMessage = (message: IpcMessage): Uint8Array => {
  const validated = validateIpcMessage(message as unknown as JsonValue);
  const payload = Buffer.from(JSON.stringify(validated), 'utf8');
  return encodeFramePayload(payload);
};

export class IpcFrameDecoder {
  #buffer = Buffer.alloc(0);

  push(chunk: Uint8Array): readonly IpcMessage[] {
    if (chunk.byteLength === 0) {
      return [];
    }
    this.#buffer = this.#buffer.byteLength === 0
      ? Buffer.from(chunk)
      : Buffer.concat([this.#buffer, Buffer.from(chunk)]);
    const messages: IpcMessage[] = [];
    while (this.#buffer.byteLength >= 4) {
      const length = this.#buffer.readUInt32BE(0);
      if (length < 1 || length > IPC_MAX_PAYLOAD_BYTES) {
        this.#buffer = Buffer.alloc(0);
        throw new IpcProtocolError('frameLength', 'IPC frame length prefix is invalid.');
      }
      if (this.#buffer.byteLength < 4 + length) {
        if (this.#buffer.byteLength > 4 + IPC_MAX_PAYLOAD_BYTES) {
          this.#buffer = Buffer.alloc(0);
          throw new IpcProtocolError('frameLength', 'IPC buffered frame exceeds its limit.');
        }
        break;
      }
      const payload = this.#buffer.subarray(4, 4 + length);
      this.#buffer = this.#buffer.subarray(4 + length);
      messages.push(decodeIpcPayload(payload));
    }
    return messages;
  }

  finish(): void {
    if (this.#buffer.byteLength !== 0) {
      this.#buffer = Buffer.alloc(0);
      throw new IpcProtocolError('truncatedFrame', 'IPC stream ended with a truncated frame.');
    }
  }
}

const randomBase64url = (length: number, primitives: RuntimePrimitives): string =>
  Buffer.from(primitives.secureRandomBytes(length)).toString('base64url');

export const createAuthToken = (primitives: RuntimePrimitives): string => {
  const token = randomBase64url(32, primitives);
  assertAuthToken(token);
  return token;
};

export const createIpcNonce = (primitives: RuntimePrimitives): string =>
  randomBase64url(16, primitives);

export const constantTimeAuthTokenEquals = (expected: string, candidate: string): boolean => {
  let expectedBytes: Buffer;
  let candidateBytes: Buffer;
  try {
    expectedBytes = Buffer.from(expected, 'base64url');
    candidateBytes = Buffer.from(candidate, 'base64url');
  } catch {
    return false;
  }
  return expectedBytes.byteLength === 32 &&
    candidateBytes.byteLength === 32 &&
    timingSafeEqual(expectedBytes, candidateBytes) &&
    expectedBytes.toString('base64url') === expected &&
    candidateBytes.toString('base64url') === candidate;
};
