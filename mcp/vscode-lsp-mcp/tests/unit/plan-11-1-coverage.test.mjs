import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import protocol from '../../packages/protocol/dist/index.js';

const componentRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

const evidence = (file, title) => Object.freeze({ file, title });

const coverage = Object.freeze([
  {
    id: 'PATH-IDENTITY',
    evidence: [
      evidence('packages/protocol/src/workspace-path.test.ts', 'alias normalization and collision suffixes are deterministic and index-stable'),
      evidence('packages/protocol/src/workspace-path.test.ts', 'root symlinks and nested roots reverse-map through the most specific canonical root'),
      evidence('packages/protocol/src/workspace-identity.test.ts', 'root changes increment generation and rotate workspace identity'),
    ],
  },
  {
    id: 'PATH-BOUNDARY',
    evidence: [
      evidence('packages/protocol/src/workspace-path.test.ts', 'canonical containment accepts internal links and rejects cross-root escapes'),
      evidence('packages/protocol/src/workspace-path.test.ts', 'missing create targets validate their nearest existing parent canonically'),
      evidence('packages/protocol/src/workspace-path.test.ts', 'Windows junction targets use native realpath and cannot escape the workspace'),
      evidence('packages/extension/src/symbol-info-provider.test.ts', 'symbol info bridge exposes an out-of-range provider state instead of an empty result'),
    ],
  },
  {
    id: 'DTO-STRICT-JSON',
    evidence: [
      evidence('packages/protocol/src/codec.test.ts', 'one validated DTO produces deterministic semantic-equivalent JSON and YAML'),
      evidence('packages/protocol/src/codec.test.ts', 'encoder validates output before serializing and cannot leak private fields'),
      evidence('packages/protocol/src/mutation.test.ts', 'public projection rebuilds only reviewable text fields and excludes snapshots'),
    ],
  },
  {
    id: 'YAML-EQUIVALENCE',
    evidence: [
      evidence('packages/protocol/src/codec.test.ts', 'one validated DTO produces deterministic semantic-equivalent JSON and YAML'),
    ],
  },
  {
    id: 'YAML-SAFETY',
    evidence: [
      evidence('packages/protocol/src/codec.test.ts', 'YAML decoder rejects aliases, anchors, tags, merge keys, and duplicate keys'),
      evidence('packages/protocol/src/codec.test.ts', 'YAML serialization quotes ambiguous scalars without changing their JSON meaning'),
    ],
  },
  {
    id: 'IPC-FRAMING',
    evidence: [
      evidence('packages/protocol/src/ipc-protocol.test.ts', 'length-prefixed frames preserve Unicode, multiline text, fragmentation, and coalescing'),
      evidence('packages/protocol/src/ipc-protocol.test.ts', 'frame bounds and truncation fail closed independently of newline content'),
    ],
  },
  {
    id: 'RESULT-WINDOW',
    evidence: [
      evidence('packages/protocol/src/collection.test.ts', 'result windows use one-based inclusive bounds and preserve available'),
      evidence('packages/protocol/src/collection.test.ts', 'result windows reject reversed, oversized, and unsafe bounds'),
    ],
  },
  {
    id: 'COLLECTION-STABILITY',
    evidence: [
      evidence('packages/protocol/src/collection.test.ts', 'candidate pipeline filters globs, deduplicates, stably sorts, then slices'),
      evidence('packages/protocol/src/collection.test.ts', 'candidate sort is deterministic and stable for equal comparator values'),
    ],
  },
  {
    id: 'ATOMIC-WORKSPACE-EDIT',
    evidence: [
      evidence('packages/protocol/src/collection.test.ts', 'candidate windows never slice edits nested in an atomic operation result'),
      evidence('packages/extension/src/workspace-edit-normalizer.test.ts', 'rebuild creates a new text-only object from normalized logical changes'),
    ],
  },
  {
    id: 'MUTATION-NORMALIZATION',
    evidence: [
      evidence('packages/extension/src/workspace-edit-normalizer.test.ts', 'normalizer copies public text edits, preserves UTF-16 insertion order, and captures snapshots'),
      evidence('packages/extension/src/workspace-edit-normalizer.test.ts', 'normalizer rejects resources, snippets, clamped ranges, overlaps, and duplicate logical targets'),
    ],
  },
  {
    id: 'MUTATION-CACHE',
    evidence: [
      evidence('packages/server/src/mutation-cache.test.ts', 'preview binding, claim, applying, and completion semantics prevent replay'),
      evidence('packages/server/src/mutation-cache.test.ts', 'preview TTL and tombstone TTL use exact monotonic boundaries without refresh'),
      evidence('packages/server/src/mutation-apply-service.test.ts', 'two concurrent apply calls dispatch at most once after atomic claim'),
      evidence('packages/server/src/mutation-apply-service.test.ts', 'post-claim transport or parser failure is outcome unknown and never retryable'),
    ],
  },
  {
    id: 'COMMAND-POLICY',
    evidence: [
      evidence('packages/protocol/src/command-policy.test.ts', 'workspace trust and hard-risk categories win over custom authorization'),
      evidence('packages/protocol/src/command-policy.test.ts', 'standard save, debug, and reload commands are enabled by default without policy entries'),
      evidence('packages/protocol/src/command-policy.test.ts', 'closed Draft 2020-12 argument schemas preserve structured values without command concatenation'),
      evidence('packages/protocol/src/command-policy.test.ts', 'input and command variables are rejected recursively before invocation'),
    ],
  },
  {
    id: 'TASK-STATE',
    evidence: [
      evidence('packages/extension/src/task-discovery.test.ts', 'task discovery builds a bounded dependency DAG from JSONC and exact allowlist entries'),
      evidence('packages/extension/src/task-discovery.test.ts', 'background, CustomExecution, and missing execution are rejected before task start'),
      evidence('packages/extension/src/command-execution.test.ts', 'task non-zero and missing exit statuses are completion failures'),
      evidence('packages/extension/src/command-execution.test.ts', 'task timeout terminates tracked executions and retains the gate until task-end'),
      evidence('packages/extension/src/command-execution.test.ts', 'timed-out command retains the workspace gate until its promise settles'),
    ],
  },
  {
    id: 'IPC-REGISTRY',
    evidence: [
      evidence('packages/protocol/src/ipc-protocol.test.ts', 'authentication tokens are canonical 32-byte base64url and compared exactly'),
      evidence('packages/protocol/src/ipc-protocol.test.ts', 'hello identity includes instance, workspace, generation, token, and nonce'),
      evidence('packages/protocol/src/registry.test.ts', 'lease cleanup is conservative and never treats a stale PID alone as identity'),
      evidence('packages/protocol/src/registry.test.ts', 'registry publish is atomic, comparison-delete is nonce guarded, and invalid records quarantine'),
    ],
  },
  {
    id: 'WINDOWS-RUNTIME',
    evidence: [
      evidence('packages/protocol/src/runtime-directory.test.ts', 'runtime directory derivation requires the secure Windows adapter'),
      evidence('packages/protocol/src/runtime-directory.test.ts', 'IPC endpoint is a collision-resistant Windows named pipe'),
    ],
  },
  {
    id: 'WINDOWS-SECURITY',
    evidence: [
      evidence('packages/win32-security/src/index.test.ts', 'runtime directory and repaired registry file have protected current-user/SYSTEM access'),
      evidence('packages/win32-security/src/index.test.ts', 'secure named pipe enforces DACL, local byte mode, first instance, cap, and raw I/O'),
    ],
  },
  {
    id: 'WINDOWS-FAIL-CLOSED',
    evidence: [
      evidence('packages/extension/src/extension.test.ts', 'Windows has no Node pipe fallback when the secure adapter is unavailable'),
    ],
  },
]);

test('PLAN 11.1 has a non-empty executable evidence mapping for all 17 unit boundaries', async () => {
  assert.equal(coverage.length, 17);
  assert.equal(new Set(coverage.map(({ id }) => id)).size, coverage.length);
  for (const requirement of coverage) {
    assert.ok(requirement.evidence.length > 0, requirement.id);
    for (const item of requirement.evidence) {
      const source = await readFile(resolve(componentRoot, item.file), 'utf8');
      assert.ok(source.includes(`test('${item.title}'`), `${requirement.id}: ${item.file} -> ${item.title}`);
    }
  }
});

test('the frozen registry compiles exactly 19 input and 19 output schemas', () => {
  const { TOOL_DEFINITIONS, TOOL_NAMES, compileAllToolSchemasIndependently } = protocol;
  assert.equal(TOOL_NAMES.length, 19);
  assert.equal(TOOL_DEFINITIONS.length, 19);
  assert.deepEqual(TOOL_DEFINITIONS.map(({ name }) => name), [...TOOL_NAMES]);
  const compiled = compileAllToolSchemasIndependently();
  assert.equal(compiled.length, 38);
  assert.equal(compiled.filter(({ direction }) => direction === 'input').length, 19);
  assert.equal(compiled.filter(({ direction }) => direction === 'output').length, 19);
});
