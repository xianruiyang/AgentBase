import {
  isAlias,
  isMap,
  isScalar,
  isSeq,
  parseDocument,
  stringify,
} from 'yaml';
import type { JsonValue, ToolName, ToolResponseMap } from './dto.js';
import { assertToolOutput, isJsonObject } from './validation.js';

export class ProtocolCodecError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProtocolCodecError';
  }
}

const canonicalize = (
  value: unknown,
  path: string,
  ancestors: Set<object>,
): JsonValue => {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      throw new ProtocolCodecError(`${path} contains a non-finite number.`);
    }
    return Object.is(value, -0) ? 0 : value;
  }
  if (typeof value !== 'object') {
    throw new ProtocolCodecError(`${path} is not a strict JSON value.`);
  }
  if (ancestors.has(value)) {
    throw new ProtocolCodecError(`${path} contains a cyclic reference.`);
  }
  if (Object.getOwnPropertySymbols(value).length > 0) {
    throw new ProtocolCodecError(`${path} contains symbol-keyed properties.`);
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((item, index) => canonicalize(item, `${path}[${index}]`, ancestors));
    }

    const prototype = Object.getPrototypeOf(value) as object | null;
    if (prototype !== Object.prototype && prototype !== null) {
      throw new ProtocolCodecError(`${path} must be a plain JSON object.`);
    }

    const result: Record<string, JsonValue> = {};
    for (const key of Object.keys(value).sort()) {
      const nested = canonicalize(
        (value as Record<string, unknown>)[key],
        `${path}.${key}`,
        ancestors,
      );
      Object.defineProperty(result, key, {
        configurable: true,
        enumerable: true,
        value: nested,
        writable: true,
      });
    }
    return result;
  } finally {
    ancestors.delete(value);
  }
};

export const canonicalizeJson = (value: unknown): JsonValue =>
  canonicalize(value, '$', new Set<object>());

const deepFreezeJson = <T extends JsonValue>(value: T): T => {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const nested of Array.isArray(value) ? value : Object.values(value)) {
      deepFreezeJson(nested);
    }
    Object.freeze(value);
  }
  return value;
};

const hasYamlMetadata = (value: unknown): value is { anchor?: string; tag?: string } =>
  value !== null && typeof value === 'object';

const assertSafeYamlNode = (node: unknown): void => {
  if (node === null) {
    return;
  }
  if (isAlias(node)) {
    throw new ProtocolCodecError('YAML aliases are forbidden.');
  }
  if (hasYamlMetadata(node) && node.anchor) {
    throw new ProtocolCodecError('YAML anchors are forbidden.');
  }
  if (hasYamlMetadata(node) && node.tag) {
    throw new ProtocolCodecError('Explicit YAML tags are forbidden.');
  }
  if (isScalar(node)) {
    return;
  }
  if (isMap(node)) {
    for (const pair of node.items) {
      if (!isScalar(pair.key) || typeof pair.key.value !== 'string') {
        throw new ProtocolCodecError('YAML mapping keys must be strings.');
      }
      if (pair.key.value === '<<') {
        throw new ProtocolCodecError('YAML merge keys are forbidden.');
      }
      assertSafeYamlNode(pair.key);
      assertSafeYamlNode(pair.value);
    }
    return;
  }
  if (isSeq(node)) {
    for (const item of node.items) {
      assertSafeYamlNode(item);
    }
    return;
  }
  throw new ProtocolCodecError('Unsupported YAML node type.');
};

export const decodeYamlText = (text: string): JsonValue => {
  const document = parseDocument(text, {
    merge: false,
    prettyErrors: false,
    schema: 'core',
    strict: true,
    stringKeys: true,
    uniqueKeys: true,
  });
  if (document.errors.length > 0) {
    throw new ProtocolCodecError(
      `Invalid YAML: ${document.errors.map((error) => error.message).join('; ')}`,
    );
  }
  if (document.contents === null) {
    throw new ProtocolCodecError('YAML document must not be empty.');
  }

  assertSafeYamlNode(document.contents);
  return canonicalizeJson(
    document.toJS({
      mapAsMap: false,
      maxAliasCount: 0,
    }),
  );
};

export const toStrictJson = (value: unknown): string => JSON.stringify(canonicalizeJson(value));

export interface TruncatedText {
  readonly value: string;
  readonly truncated: boolean;
}

export const truncateUnicodeCodePoints = (value: string, maximumCodePoints: number): TruncatedText => {
  if (!Number.isSafeInteger(maximumCodePoints) || maximumCodePoints < 0) {
    throw new RangeError('maximumCodePoints must be a non-negative safe integer.');
  }
  const codePoints = [...value];
  if (codePoints.length <= maximumCodePoints) {
    return Object.freeze({ value, truncated: false });
  }
  return Object.freeze({
    value: codePoints.slice(0, maximumCodePoints).join(''),
    truncated: true,
  });
};

export const toDeterministicYaml = (value: unknown): string => {
  const canonical = canonicalizeJson(value);
  return stringify(canonical, {
    aliasDuplicateObjects: false,
    lineWidth: 0,
    simpleKeys: true,
  });
};

export interface EncodedToolResponse<K extends ToolName> {
  readonly structuredContent: ToolResponseMap[K];
  readonly content: readonly [
    {
      readonly type: 'text';
      readonly text: string;
    },
  ];
}

export const encodeToolResponse = <K extends ToolName>(
  toolName: K,
  response: ToolResponseMap[K],
): EncodedToolResponse<K> => {
  assertToolOutput(toolName, response);
  const canonical = deepFreezeJson(canonicalizeJson(response));
  if (!isJsonObject(canonical)) {
    throw new ProtocolCodecError('Tool response envelope must be a JSON object.');
  }

  const yamlText = toDeterministicYaml(canonical);
  const decoded = decodeYamlText(yamlText);
  if (toStrictJson(decoded) !== toStrictJson(canonical)) {
    throw new ProtocolCodecError('YAML and structured JSON content are not semantically equal.');
  }

  return Object.freeze({
    structuredContent: canonical as unknown as ToolResponseMap[K],
    content: Object.freeze([
      Object.freeze({
        type: 'text' as const,
        text: yamlText,
      }),
    ]) as EncodedToolResponse<K>['content'],
  });
};
