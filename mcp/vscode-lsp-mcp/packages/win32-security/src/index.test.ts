import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import test from 'node:test';
import {
  createSecurePipeServer,
  ensureSecureRuntimeDirectory,
  getNativeBuildInfo,
  SUPPORTED_WINDOWS_ARCHITECTURES,
  verifySecureRegistryFile,
} from './index.js';

test('native adapter declares auditable Windows targets', () => {
  assert.deepEqual(SUPPORTED_WINDOWS_ARCHITECTURES, ['x64', 'arm64']);
});

test('native adapter implements the frozen Node-API security boundary', {
  skip: process.platform !== 'win32',
}, () => {
  const info = getNativeBuildInfo();
  assert.equal(info.abi, 'node-api');
  assert.ok(info.napiVersion >= 8);
  assert.equal(info.targetArch, process.arch);
  assert.equal(info.securityOperationsImplemented, true);
});

test('runtime directory and registry file have protected current-user/SYSTEM access', {
  skip: process.platform !== 'win32',
}, async () => {
  const info = ensureSecureRuntimeDirectory();
  assert.equal(info.protectedDacl, true);
  assert.equal(info.ownerCurrentUser, true);
  assert.equal(info.systemFullControl, true);
  assert.equal(info.otherUsersDenied, true);
  assert.equal(info.reparsePoint, false);
  const registrations = path.join(info.path, 'registrations');
  await mkdir(registrations, { recursive: true });
  const file = path.join(registrations, `test-${randomUUID()}.json`);
  try {
    await writeFile(file, '{}', { flag: 'wx' });
    assert.equal(verifySecureRegistryFile(file), true);
  } finally {
    await rm(file, { force: true });
  }
});

test('secure named pipe enforces DACL, local byte mode, first instance, cap, and raw I/O', {
  skip: process.platform !== 'win32', timeout: 5_000,
}, async () => {
  const name = `\\\\.\\pipe\\vscode-lsp-mcp-test-${randomUUID()}`;
  const server = createSecurePipeServer({ name, maxInstances: 4 });
  const inspection = server.inspectSecurity();
  assert.deepEqual(inspection, {
    protectedDacl: true,
    ownerCurrentUser: true,
    currentUserFullControl: true,
    systemFullControl: true,
    otherUsersDenied: true,
    remoteClientsRejected: true,
    byteMode: true,
    firstInstance: true,
    maxInstances: 4,
  });
  const accepting = server.accept();
  const client = net.createConnection(name);
  try {
    await new Promise<void>((resolve, reject) => {
      client.once('connect', resolve);
      client.once('error', reject);
    });
    const connection = await accepting;
    try {
      client.write(Buffer.from('client-to-native'));
      assert.equal(Buffer.from(await connection.read() ?? []).toString(), 'client-to-native');
      const received = new Promise<Buffer>((resolve) => client.once('data', resolve));
      await connection.write(Buffer.from('native-to-client'));
      assert.equal((await received).toString(), 'native-to-client');
    } finally {
      await connection.close();
    }
  } finally {
    client.destroy();
    await server.close();
  }
});

test('secure named pipe rejects foreign namespaces and over-capacity configuration', {
  skip: process.platform !== 'win32',
}, () => {
  assert.throws(() => createSecurePipeServer({ name: '\\\\.\\pipe\\other' }), /namespace/u);
  assert.throws(() => createSecurePipeServer({ name: '\\\\.\\pipe\\vscode-lsp-mcp-test', maxInstances: 5 }), RangeError);
});

test('native adapter fails closed on non-Windows platforms', {
  skip: process.platform === 'win32',
}, () => {
  assert.throws(() => getNativeBuildInfo(), /only loadable on Windows/);
});
