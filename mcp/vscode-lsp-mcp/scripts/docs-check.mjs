import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const expectedAuthor = 'SimpleChat contributors';
const expectedLicense = 'Apache-2.0';
const expectedNotice = `VS Code LSP MCP
Copyright 2026 SimpleChat contributors

Licensed under the Apache License, Version 2.0.

Third-party software and attribution notices are listed in
THIRD_PARTY_NOTICES.md.
`;
const apacheLicenseSha256 = 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4';
const requiredDocuments = Object.freeze([
  'README.md',
  'docs/configuration.md',
  'docs/dependencies.md',
  'docs/development.md',
  'docs/doctor.md',
  'docs/installation.md',
  'docs/security.md',
  'docs/tools.md',
  'docs/troubleshooting.md',
]);
const manifestPaths = Object.freeze([
  'package.json',
  'packages/extension/package.json',
  'packages/protocol/package.json',
  'packages/server/package.json',
  'packages/win32-security/package.json',
]);

const readText = (relativePath) => readFile(path.join(componentRoot, relativePath), 'utf8');
const readJson = async (relativePath) => JSON.parse(await readText(relativePath));
const exists = async (filePath) => {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
};

const documents = new Map();
for (const relativePath of requiredDocuments) {
  const content = await readText(relativePath);
  assert.ok(content.trim().length > 0, `${relativePath} is empty.`);
  documents.set(relativePath, content);
}

const machineAbsolutePath = /(?:^|[\s("'`])(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+\\[^\\\s]+)/mu;
for (const [relativePath, content] of documents) {
  assert.equal(
    machineAbsolutePath.test(content),
    false,
    `${relativePath} contains a machine-specific absolute path.`,
  );
  const linkPattern = /\[[^\]]*\]\(([^)]+)\)/gu;
  for (const match of content.matchAll(linkPattern)) {
    const rawTarget = match[1].trim().replace(/^<|>$/gu, '');
    if (/^(?:https?:|mailto:|#)/iu.test(rawTarget)) continue;
    const localTarget = decodeURIComponent(rawTarget.split('#', 1)[0]);
    const resolved = path.resolve(path.dirname(path.join(componentRoot, relativePath)), localTarget);
    const relative = path.relative(componentRoot, resolved);
    assert.ok(
      relative.length > 0 && !relative.startsWith('..') && !path.isAbsolute(relative),
      `${relativePath} link escapes the component: ${rawTarget}`,
    );
    assert.equal(await exists(resolved), true, `${relativePath} has a broken link: ${rawTarget}`);
  }
}

const dtoSource = await readText('packages/protocol/src/dto.ts');
const toolArray = /export const TOOL_NAMES = \[([\s\S]*?)\] as const;/u.exec(dtoSource);
assert.ok(toolArray, 'Unable to locate TOOL_NAMES in the protocol source.');
const protocolTools = [...toolArray[1].matchAll(/'([a-z_]+)'/gu)].map((match) => match[1]);
const documentedTools = [...documents.get('docs/tools.md').matchAll(
  /^\| `([a-z_]+)` \| (?:read|preview|mutation) \|/gmu,
)].map((match) => match[1]);
assert.equal(protocolTools.length, 18, 'The protocol must expose exactly 18 tools.');
assert.deepEqual(documentedTools, protocolTools, 'The tool table differs from protocol TOOL_NAMES.');
assert.match(documents.get('docs/security.md'), /^## Explicit limitations$/mu);

const license = await readText('LICENSE');
assert.equal(createHash('sha256').update(license).digest('hex'), apacheLicenseSha256);
assert.equal(await readText('NOTICE'), expectedNotice);

const manifests = [];
for (const relativePath of manifestPaths) {
  const manifest = await readJson(relativePath);
  assert.equal(manifest.author, expectedAuthor, `${relativePath} author mismatch.`);
  assert.equal(manifest.license, expectedLicense, `${relativePath} license mismatch.`);
  manifests.push({ relativePath, manifest });
}
const lock = await readJson('package-lock.json');
for (const { relativePath, manifest } of manifests) {
  const lockKey = relativePath === 'package.json' ? '' : path.posix.dirname(relativePath);
  const entry = lock.packages[lockKey];
  assert.ok(entry, `package-lock.json is missing ${lockKey || 'the root package'}.`);
  assert.equal(entry.name, manifest.name, `package-lock.json name mismatch for ${lockKey}.`);
  assert.equal(entry.license, expectedLicense, `package-lock.json license mismatch for ${lockKey}.`);
}
const rootManifest = manifests.find(({ relativePath }) => relativePath === 'package.json')?.manifest;
assert.ok(rootManifest, 'The root package manifest was not loaded.');
assert.equal(rootManifest.scripts.verify, 'node ./scripts/verify.mjs');
assert.equal(rootManifest.scripts['verify:release'], 'node ./scripts/verify-release.mjs');
const releaseVerifier = await readText('scripts/verify-release.mjs');
for (const requiredStage of ["'test:stage-b'", "'test:stage-c'"]) {
  assert.ok(releaseVerifier.includes(requiredStage), `Release verifier is missing ${requiredStage}.`);
}
assert.match(documents.get('docs/development.md'), /normal developer verifier[\s\S]*npm run verify/u);
assert.match(documents.get('docs/development.md'), /complete Windows x64 release gate[\s\S]*npm run verify:release/u);

process.stdout.write(`${JSON.stringify({
  documents: requiredDocuments.length,
  localLinks: [...documents.values()].reduce(
    (count, content) => count + [...content.matchAll(/\[[^\]]*\]\(([^)]+)\)/gu)]
      .filter((match) => !/^(?:https?:|mailto:|#)/iu.test(match[1].trim())).length,
    0,
  ),
  tools: documentedTools.length,
  manifests: manifests.length,
  license: expectedLicense,
  author: expectedAuthor,
})}\n`);
