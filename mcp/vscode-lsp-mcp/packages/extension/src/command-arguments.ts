import {
  COMMAND_POLICY_LOGICAL_PATH_KEYWORD,
  resolveLogicalPath,
  type JsonSchema,
  type JsonValue,
  type WorkspacePathAccess,
  type WorkspacePathContext,
} from '@simplechat/vscode-lsp-mcp-protocol';

export interface CommandArgumentUriFactory<TUri = unknown> {
  file(absolutePath: string): TUri;
}

const resolvedUriMarker: unique symbol = Symbol('resolvedCommandArgumentUri');

interface ResolvedUri<TUri> {
  readonly [resolvedUriMarker]: true;
  readonly value: TUri;
}

const isResolvedUri = <TUri>(value: unknown): value is ResolvedUri<TUri> =>
  value !== null && typeof value === 'object' &&
  (value as Partial<ResolvedUri<TUri>>)[resolvedUriMarker] === true;

const asSchema = (value: unknown): JsonSchema | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonSchema
    : undefined;

const containsLogicalAnnotation = (
  value: unknown,
  seen = new Set<object>(),
): boolean => {
  if (value === null || typeof value !== 'object' || seen.has(value)) return false;
  seen.add(value);
  if (!Array.isArray(value) &&
      (value as Record<string, unknown>)[COMMAND_POLICY_LOGICAL_PATH_KEYWORD] === true) {
    return true;
  }
  return Object.values(value).some((nested) => containsLogicalAnnotation(nested, seen));
};

const localReference = (root: JsonSchema, reference: string): JsonSchema => {
  if (!reference.startsWith('#/')) {
    throw new TypeError('Command argument schemas may only use local logical-path references.');
  }
  let current: unknown = root;
  for (const encoded of reference.slice(2).split('/')) {
    const segment = encoded.replace(/~1/gu, '/').replace(/~0/gu, '~');
    if (current === null || typeof current !== 'object' || Array.isArray(current) ||
        !Object.hasOwn(current, segment)) {
      throw new TypeError('Command argument schema contains an unresolved local reference.');
    }
    current = (current as Record<string, unknown>)[segment];
  }
  const schema = asSchema(current);
  if (schema === undefined) {
    throw new TypeError('Command argument schema reference does not identify an object schema.');
  }
  return schema;
};

const ambiguousKeywords = [
  'anyOf',
  'oneOf',
  'if',
  'then',
  'else',
  'not',
  'contains',
  'dependentSchemas',
  'propertyNames',
  'unevaluatedItems',
  'unevaluatedProperties',
] as const;

const transform = async <TUri>(
  value: unknown,
  schema: JsonSchema,
  root: JsonSchema,
  context: WorkspacePathContext,
  access: WorkspacePathAccess,
  uriFactory: CommandArgumentUriFactory<TUri>,
  references: Set<string>,
): Promise<unknown> => {
  if (isResolvedUri<TUri>(value)) return value;
  if (schema[COMMAND_POLICY_LOGICAL_PATH_KEYWORD] === true) {
    if (typeof value !== 'string') {
      throw new TypeError('A logical-path command argument must be a string.');
    }
    const resolved = await resolveLogicalPath(context, value, access, { allowMissing: true });
    return Object.freeze({
      [resolvedUriMarker]: true as const,
      value: uriFactory.file(resolved.lexicalAbsolutePath),
    });
  }

  const reference = schema.$ref;
  if (reference !== undefined) {
    if (typeof reference !== 'string' || references.has(reference)) {
      throw new TypeError('Command argument schema contains an invalid reference cycle.');
    }
    references.add(reference);
    try {
      return await transform(
        value,
        localReference(root, reference),
        root,
        context,
        access,
        uriFactory,
        references,
      );
    } finally {
      references.delete(reference);
    }
  }

  for (const keyword of ambiguousKeywords) {
    if (schema[keyword] !== undefined && containsLogicalAnnotation(schema[keyword])) {
      throw new TypeError(
        `Logical-path annotations under conditional schema keyword ${keyword} are unsupported.`,
      );
    }
  }

  let transformed = value;
  const allOf = schema.allOf;
  if (Array.isArray(allOf)) {
    for (const nested of allOf) {
      const nestedSchema = asSchema(nested);
      if (nestedSchema !== undefined) {
        transformed = await transform(
          transformed,
          nestedSchema,
          root,
          context,
          access,
          uriFactory,
          references,
        );
      }
    }
  }

  if (Array.isArray(transformed)) {
    const prefixItems = Array.isArray(schema.prefixItems) ? schema.prefixItems : [];
    const items = asSchema(schema.items);
    return await Promise.all(transformed.map(async (item, index) => {
      const itemSchema = asSchema(prefixItems[index]) ?? items;
      return itemSchema === undefined
        ? item
        : await transform(item, itemSchema, root, context, access, uriFactory, references);
    }));
  }

  if (transformed !== null && typeof transformed === 'object') {
    const record = transformed as Record<string, unknown>;
    const properties = asSchema(schema.properties) ?? {};
    const patterns = asSchema(schema.patternProperties) ?? {};
    const additional = asSchema(schema.additionalProperties);
    const result: Record<string, unknown> = {};
    for (const [name, nestedValue] of Object.entries(record)) {
      const direct = asSchema(properties[name]);
      const matchingPatterns = Object.entries(patterns)
        .filter(([pattern]) => new RegExp(pattern, 'u').test(name))
        .map(([, nested]) => asSchema(nested))
        .filter((nested): nested is JsonSchema => nested !== undefined);
      let nestedResult: unknown = nestedValue;
      if (direct !== undefined) {
        nestedResult = await transform(
          nestedResult,
          direct,
          root,
          context,
          access,
          uriFactory,
          references,
        );
      }
      for (const pattern of matchingPatterns) {
        nestedResult = await transform(
          nestedResult,
          pattern,
          root,
          context,
          access,
          uriFactory,
          references,
        );
      }
      if (direct === undefined && matchingPatterns.length === 0 && additional !== undefined) {
        nestedResult = await transform(
          nestedResult,
          additional,
          root,
          context,
          access,
          uriFactory,
          references,
        );
      }
      result[name] = nestedResult;
    }
    return result;
  }
  return transformed;
};

const unwrapResolvedUris = <TUri>(value: unknown): unknown => {
  if (isResolvedUri<TUri>(value)) return value.value;
  if (Array.isArray(value)) return value.map((nested) => unwrapResolvedUris<TUri>(nested));
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([name, nested]) =>
      [name, unwrapResolvedUris<TUri>(nested)]));
  }
  return value;
};

export const resolveCommandArguments = async <TUri>(
  values: readonly JsonValue[],
  schema: JsonSchema | undefined,
  context: WorkspacePathContext,
  access: WorkspacePathAccess,
  uriFactory: CommandArgumentUriFactory<TUri>,
): Promise<readonly unknown[]> => {
  if (schema === undefined) return Object.freeze([]);
  const transformed = await transform(
    structuredClone(values),
    schema,
    schema,
    context,
    access,
    uriFactory,
    new Set<string>(),
  );
  const unwrapped = unwrapResolvedUris<TUri>(transformed);
  if (!Array.isArray(unwrapped)) {
    throw new TypeError('Command argument schema did not produce an arguments array.');
  }
  return Object.freeze(unwrapped);
};
