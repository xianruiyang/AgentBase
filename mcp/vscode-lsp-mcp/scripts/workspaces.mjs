import { readdir, readFile, rm } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const componentRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packagesRoot = join(componentRoot, 'packages');
const unitTestsRoot = join(componentRoot, 'tests', 'unit');
const removableOutputNames = new Set(['dist', 'build']);

function getNpmCliPath() {
  const npmCliPath = process.env.npm_execpath;
  if (!npmCliPath) {
    throw new Error('npm_execpath is required; invoke this runner through an npm script.');
  }
  return npmCliPath;
}

async function loadWorkspaces() {
  const entries = await readdir(packagesRoot, { withFileTypes: true });
  const workspaces = [];

  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue;
    }

    const directory = join(packagesRoot, entry.name);
    const manifestPath = join(directory, 'package.json');
    let manifest;

    try {
      manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    } catch (error) {
      throw new Error(`Unable to read workspace manifest ${relative(componentRoot, manifestPath)}`, {
        cause: error,
      });
    }

    if (typeof manifest.name !== 'string' || manifest.name.length === 0) {
      throw new Error(`Workspace ${entry.name} has no valid package name.`);
    }

    workspaces.push({
      directory,
      manifest,
      name: manifest.name,
      relativeDirectory: relative(componentRoot, directory).replaceAll('\\', '/'),
    });
  }

  workspaces.sort((left, right) => left.relativeDirectory.localeCompare(right.relativeDirectory));
  return workspaces;
}

function sortTopologically(workspaces) {
  const byName = new Map();

  for (const workspace of workspaces) {
    if (byName.has(workspace.name)) {
      throw new Error(`Duplicate workspace package name: ${workspace.name}`);
    }
    byName.set(workspace.name, workspace);
  }

  const dependencyFields = ['dependencies', 'optionalDependencies', 'peerDependencies', 'devDependencies'];
  const dependencies = new Map();
  const dependents = new Map(workspaces.map((workspace) => [workspace.name, new Set()]));

  for (const workspace of workspaces) {
    const internal = new Set();
    for (const field of dependencyFields) {
      for (const dependencyName of Object.keys(workspace.manifest[field] ?? {})) {
        if (byName.has(dependencyName)) {
          internal.add(dependencyName);
        }
      }
    }
    dependencies.set(workspace.name, internal);
    for (const dependencyName of internal) {
      dependents.get(dependencyName).add(workspace.name);
    }
  }

  const ready = workspaces
    .filter((workspace) => dependencies.get(workspace.name).size === 0)
    .map((workspace) => workspace.name)
    .sort();
  const order = [];

  while (ready.length > 0) {
    const name = ready.shift();
    order.push(byName.get(name));

    for (const dependentName of [...dependents.get(name)].sort()) {
      const remaining = dependencies.get(dependentName);
      remaining.delete(name);
      if (remaining.size === 0) {
        ready.push(dependentName);
        ready.sort();
      }
    }
  }

  if (order.length !== workspaces.length) {
    const cycleMembers = workspaces
      .map((workspace) => workspace.name)
      .filter((name) => !order.some((workspace) => workspace.name === name))
      .sort();
    throw new Error(`Workspace dependency cycle detected: ${cycleMembers.join(', ')}`);
  }

  return order;
}

function assertSafeOutputPath(workspaceDirectory, outputName) {
  if (!removableOutputNames.has(outputName)) {
    throw new Error(`Refusing to remove unapproved output directory: ${outputName}`);
  }

  const outputPath = resolve(workspaceDirectory, outputName);
  if (dirname(outputPath) !== resolve(workspaceDirectory)) {
    throw new Error(`Output path escaped workspace: ${outputPath}`);
  }
  return outputPath;
}

async function clean(workspaces) {
  for (const workspace of workspaces) {
    for (const outputName of removableOutputNames) {
      await rm(assertSafeOutputPath(workspace.directory, outputName), {
        force: true,
        recursive: true,
      });
    }
  }
}

function runScript(workspace, scriptName) {
  const result = spawnSync(
    process.execPath,
    [getNpmCliPath(), 'run', scriptName, '--workspace', workspace.name],
    {
      cwd: componentRoot,
      env: process.env,
      stdio: 'inherit',
    },
  );

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${scriptName} failed for ${workspace.name} with exit code ${result.status}`);
  }
}

async function runRootUnitTests() {
  const entries = await readdir(unitTestsRoot, { withFileTypes: true });
  const tests = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith('.test.mjs'))
    .map((entry) => join(unitTestsRoot, entry.name))
    .sort();
  if (tests.length === 0) {
    throw new Error('No root unit coverage tests were found.');
  }
  const result = spawnSync(process.execPath, ['--test', ...tests], {
    cwd: componentRoot,
    env: process.env,
    stdio: 'inherit',
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`root unit coverage tests failed with exit code ${result.status}`);
  }
}

async function main() {
  const action = process.argv[2];
  const workspaces = await loadWorkspaces();
  const order = sortTopologically(workspaces);

  if (action === 'check') {
    process.stdout.write(`Workspace graph OK: ${order.map((workspace) => workspace.name).join(' -> ')}\n`);
    return;
  }
  if (action === 'clean') {
    await clean(workspaces);
    return;
  }
  if (action === 'build') {
    await clean(workspaces);
    for (const workspace of order) {
      runScript(workspace, 'build');
    }
    return;
  }
  if (action === 'test') {
    await clean(workspaces);
    for (const workspace of order) {
      runScript(workspace, 'build');
    }
    for (const workspace of order) {
      runScript(workspace, 'test');
    }
    await runRootUnitTests();
    return;
  }

  throw new Error('Expected one action: clean, check, build, or test.');
}

await main();
