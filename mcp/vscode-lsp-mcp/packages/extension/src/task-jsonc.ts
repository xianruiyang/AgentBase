export const MAX_TASK_CONFIGURATION_CHARS = 1_048_576;

export class TaskJsoncError extends Error {
  readonly offset: number;

  constructor(message: string, offset: number) {
    super(`${message} at offset ${offset}.`);
    this.name = 'TaskJsoncError';
    this.offset = offset;
  }
}

class TaskJsoncParser {
  readonly #text: string;
  #offset = 0;
  #nodes = 0;

  constructor(text: string) {
    this.#text = text;
  }

  parse(): unknown {
    this.#skipTrivia();
    const value = this.#parseValue(0);
    this.#skipTrivia();
    if (this.#offset !== this.#text.length) this.#fail('Unexpected trailing content');
    return value;
  }

  #fail(message: string): never {
    throw new TaskJsoncError(message, this.#offset);
  }

  #skipTrivia(): void {
    while (this.#offset < this.#text.length) {
      const character = this.#text[this.#offset]!;
      if (/\s/u.test(character)) {
        this.#offset += 1;
        continue;
      }
      if (character !== '/' || this.#offset + 1 >= this.#text.length) return;
      const next = this.#text[this.#offset + 1];
      if (next === '/') {
        this.#offset += 2;
        while (this.#offset < this.#text.length &&
            this.#text[this.#offset] !== '\n' && this.#text[this.#offset] !== '\r') {
          this.#offset += 1;
        }
        continue;
      }
      if (next === '*') {
        const end = this.#text.indexOf('*/', this.#offset + 2);
        if (end < 0) this.#fail('Unterminated block comment');
        this.#offset = end + 2;
        continue;
      }
      return;
    }
  }

  #parseValue(depth: number): unknown {
    if (depth > 64 || ++this.#nodes > 100_000) this.#fail('JSONC is too complex');
    this.#skipTrivia();
    const character = this.#text[this.#offset];
    if (character === '{') return this.#parseObject(depth + 1);
    if (character === '[') return this.#parseArray(depth + 1);
    if (character === '"') return this.#parseString();
    if (character === '-' || (character !== undefined && /[0-9]/u.test(character))) {
      return this.#parseNumber();
    }
    for (const [literal, value] of [
      ['true', true],
      ['false', false],
      ['null', null],
    ] as const) {
      if (this.#text.startsWith(literal, this.#offset)) {
        this.#offset += literal.length;
        return value;
      }
    }
    this.#fail('Expected a JSON value');
  }

  #parseString(): string {
    const start = this.#offset;
    this.#offset += 1;
    let escaped = false;
    while (this.#offset < this.#text.length) {
      const character = this.#text[this.#offset]!;
      this.#offset += 1;
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === '\\') {
        escaped = true;
        continue;
      }
      if (character === '"') {
        try {
          return JSON.parse(this.#text.slice(start, this.#offset)) as string;
        } catch {
          this.#fail('Invalid JSON string');
        }
      }
      if (character === '\n' || character === '\r') this.#fail('Unescaped newline in string');
    }
    this.#fail('Unterminated string');
  }

  #parseNumber(): number {
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/u.exec(
      this.#text.slice(this.#offset),
    );
    if (match === null) this.#fail('Invalid JSON number');
    this.#offset += match[0].length;
    const value = Number(match[0]);
    if (!Number.isFinite(value)) this.#fail('JSON number must be finite');
    return value;
  }

  #parseArray(depth: number): unknown[] {
    this.#offset += 1;
    const values: unknown[] = [];
    this.#skipTrivia();
    if (this.#text[this.#offset] === ']') {
      this.#offset += 1;
      return values;
    }
    while (true) {
      values.push(this.#parseValue(depth));
      this.#skipTrivia();
      const character = this.#text[this.#offset];
      if (character === ']') {
        this.#offset += 1;
        return values;
      }
      if (character !== ',') this.#fail('Expected a comma or closing bracket');
      this.#offset += 1;
      this.#skipTrivia();
      if (this.#text[this.#offset] === ']') {
        this.#offset += 1;
        return values;
      }
    }
  }

  #parseObject(depth: number): Record<string, unknown> {
    this.#offset += 1;
    const value: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    const keys = new Set<string>();
    this.#skipTrivia();
    if (this.#text[this.#offset] === '}') {
      this.#offset += 1;
      return value;
    }
    while (true) {
      this.#skipTrivia();
      if (this.#text[this.#offset] !== '"') this.#fail('Expected a quoted object key');
      const key = this.#parseString();
      if (keys.has(key)) this.#fail(`Duplicate object key ${JSON.stringify(key)}`);
      keys.add(key);
      this.#skipTrivia();
      if (this.#text[this.#offset] !== ':') this.#fail('Expected a colon after object key');
      this.#offset += 1;
      value[key] = this.#parseValue(depth);
      this.#skipTrivia();
      const character = this.#text[this.#offset];
      if (character === '}') {
        this.#offset += 1;
        return value;
      }
      if (character !== ',') this.#fail('Expected a comma or closing brace');
      this.#offset += 1;
      this.#skipTrivia();
      if (this.#text[this.#offset] === '}') {
        this.#offset += 1;
        return value;
      }
    }
  }
}

export const parseTaskJsonc = (text: string): unknown => {
  if (text.length > MAX_TASK_CONFIGURATION_CHARS) {
    throw new TaskJsoncError('Task configuration exceeds the size limit', 0);
  }
  return new TaskJsoncParser(text).parse();
};
