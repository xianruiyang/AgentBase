import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  RuntimeSecurityError,
  assertSecurePosixDirectoryMetadata,
  assertSecurePosixSocketMetadata,
  cleanupStaleUnixSocket,
  createInstanceId,
  createIpcEndpoint,
  deriveRuntimeDirectoryRoot,
  type RuntimePrimitives,
} from './index.js';

const primitives: RuntimePrimitives = {
  monotonicNowMs: () => 0,
  secureRandomBytes: (length) => new Uint8Array(length).fill(7),
  sha256Hex: (input) => createHash('sha256').update(input).digest('hex'),
};

test('runtime directories are outside projects and use platform-owned per-user locations', () => {
  assert.equal(
    deriveRuntimeDirectoryRoot({ platform: 'linux', environment: { XDG_RUNTIME_DIR: '/run/user/42' }, uid: 42 }, primitives).root,
    '/run/user/42/vscode-lsp-mcp',
  );
  assert.match(
    deriveRuntimeDirectoryRoot({ platform: 'linux', environment: {}, uid: 42 }, primitives).root,
    /^\/tmp\/vlm-[0-9a-f]{12}$/u,
  );
  assert.match(
    deriveRuntimeDirectoryRoot({ platform: 'darwin', environment: { TMPDIR: '/private/tmp/user' }, uid: 42 }, primitives).root,
    /^\/private\/tmp\/user\/vscode-lsp-mcp-[0-9a-f]{12}$/u,
  );
  assert.throws(() => deriveRuntimeDirectoryRoot({ platform: 'win32', environment: {} }, primitives),
    (error: unknown) => error instanceof RuntimeSecurityError && error.reason === 'windowsAdapterUnavailable');
});

test('POSIX directory and socket metadata require exact owner, type, and modes', () => {
  assert.doesNotThrow(() => assertSecurePosixDirectoryMetadata({
    isDirectory: true, isSymbolicLink: false, mode: 0o40700, uid: 42,
  }, 42));
  assert.throws(() => assertSecurePosixDirectoryMetadata({
    isDirectory: true, isSymbolicLink: false, mode: 0o40755, uid: 42,
  }, 42), RuntimeSecurityError);
  assert.throws(() => assertSecurePosixDirectoryMetadata({
    isDirectory: true, isSymbolicLink: true, mode: 0o40700, uid: 42,
  }, 42), RuntimeSecurityError);
  assert.doesNotThrow(() => assertSecurePosixSocketMetadata({
    isSocket: true, isSymbolicLink: false, mode: 0o140600, uid: 42,
  }, 42));
  assert.throws(() => assertSecurePosixSocketMetadata({
    isSocket: true, isSymbolicLink: false, mode: 0o140660, uid: 42,
  }, 42), RuntimeSecurityError);
});

test('IPC endpoints are bounded, collision-resistant, and platform-specific', () => {
  const instanceId = createInstanceId(primitives);
  const windows = createIpcEndpoint({
    platform: 'win32', root: 'C:\\runtime', registrations: 'C:\\runtime\\registrations', quarantine: 'C:\\runtime\\quarantine',
  }, instanceId, primitives, 'S-1-5-21-1');
  assert.match(windows.address, /^\\\\\.\\pipe\\vscode-lsp-mcp-[0-9a-f]{12}-[0-9a-f]{32}$/u);
  const unix = createIpcEndpoint({
    platform: 'linux', root: '/tmp/vlm-short', registrations: '/tmp/vlm-short/registrations', quarantine: '/tmp/vlm-short/quarantine',
  }, instanceId, primitives);
  assert.equal(Buffer.byteLength(unix.address) <= 100, true);
  assert.match(unix.address, /^\/tmp\/vlm-short\/i-[0-9a-f]{24}\.sock$/u);
  assert.throws(() => createIpcEndpoint({
    platform: 'linux', root: `/tmp/${'x'.repeat(100)}`, registrations: '/tmp/r', quarantine: '/tmp/q',
  }, instanceId, primitives), (error: unknown) =>
    error instanceof RuntimeSecurityError && error.reason === 'endpointPathTooLong');
});

test('stale Unix socket cleanup removes only an owned unreachable exact endpoint', async () => {
  const calls = { lstat: 0, unlink: 0, connect: 0 };
  const filesystem = {
    lstat: () => {
      calls.lstat += 1;
      return Promise.resolve({
        uid: 42,
        isSocket: () => true,
        isSymbolicLink: () => false,
      });
    },
    unlink: () => { calls.unlink += 1; return Promise.resolve(); },
  };
  const base = {
    endpoint: '/run/user/42/vscode-lsp-mcp/i-owned.sock',
    expectedEndpoint: '/run/user/42/vscode-lsp-mcp/i-owned.sock',
    expectedUid: 42,
    hasValidRegistration: false,
    canConnect: () => { calls.connect += 1; return Promise.resolve(false); },
    filesystem,
  };

  assert.equal(await cleanupStaleUnixSocket(base), true);
  assert.deepEqual(calls, { lstat: 1, unlink: 1, connect: 1 });

  assert.equal(await cleanupStaleUnixSocket({
    ...base,
    expectedEndpoint: '/run/user/42/vscode-lsp-mcp/i-other.sock',
  }), false);
  assert.equal(await cleanupStaleUnixSocket({ ...base, hasValidRegistration: true }), false);
  assert.deepEqual(calls, { lstat: 1, unlink: 1, connect: 1 });

  assert.equal(await cleanupStaleUnixSocket({
    ...base,
    filesystem: {
      ...filesystem,
      lstat: () => Promise.resolve({
        uid: 7,
        isSocket: () => true,
        isSymbolicLink: () => false,
      }),
    },
  }), false);
  for (const metadata of [
    { uid: 42, isSocket: () => false, isSymbolicLink: () => false },
    { uid: 42, isSocket: () => true, isSymbolicLink: () => true },
  ]) {
    assert.equal(await cleanupStaleUnixSocket({
      ...base,
      filesystem: { ...filesystem, lstat: () => Promise.resolve(metadata) },
    }), false);
  }
  assert.equal(await cleanupStaleUnixSocket({
    ...base,
    canConnect: () => Promise.resolve(true),
  }), false);
  assert.equal(await cleanupStaleUnixSocket({
    ...base,
    filesystem: {
      ...filesystem,
      unlink: () => Promise.reject(new Error('simulated unlink failure')),
    },
  }), false);
  assert.equal(calls.unlink, 1);
});
