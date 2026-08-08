import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CommandPolicy,
  classifyCommandRisk,
  createFailClosedCommandPolicyDecision,
} from './command-policy.js';

const entry = (commandId: string, argumentSchema?: Record<string, unknown>) => ({
  commandId,
  nonInteractive: true,
  completion: 'promise',
  maxTimeoutMs: 10_000,
  ...(argumentSchema === undefined ? {} : { argumentSchema }),
});

const input = (commandId: string, arguments_: readonly unknown[] = [], timeoutMs = 120_000) => ({
  target: { kind: 'command' as const, commandId, arguments: arguments_ as never },
  timeoutMs,
});

test('command policy defaults reject unknown custom commands', () => {
  const decision = new CommandPolicy().preflightCommand(input('fixture.complete'), true);
  assert.equal(decision.ok, false);
  if (!decision.ok) assert.equal(decision.error.code, 'COMMAND_NOT_ALLOWED');
});

test('workspace trust and hard-risk categories win over custom authorization', () => {
  const cases = [
    ['workbench.action.closeWindow', 'windowLifecycle'],
    ['workbench.action.quit', 'vscodeLifecycle'],
    ['workbench.extensions.action.uninstallExtension', 'extensionManagement'],
    ['vscodeLspMcp.disconnectBridge', 'bridgeLifecycle'],
    ['editor.action.rename', 'inputBox'],
    ['workbench.action.showCommands', 'quickPick'],
    ['workbench.action.files.openFile', 'filePicker'],
    ['workbench.action.accounts.signIn', 'authentication'],
    ['workbench.action.files.revert', 'confirmation'],
  ] as const;
  const policy = new CommandPolicy({
    allowStandardCommands: false,
    commands: cases.map(([commandId]) => entry(commandId)),
    tasks: [],
  });
  const untrusted = policy.preflightCommand(input('workbench.action.reloadWindow'), false);
  assert.equal(untrusted.ok, false);
  if (!untrusted.ok) {
    assert.equal(untrusted.error.code, 'INTERACTIVE_COMMAND');
    assert.deepEqual(untrusted.error.details, {
      targetKind: 'command',
      reason: 'workspaceTrust',
    });
  }
  for (const [commandId, expectedRisk] of cases) {
    assert.equal(classifyCommandRisk(commandId), expectedRisk);
    const decision = policy.preflightCommand(input(commandId), true);
    assert.equal(decision.ok, false, commandId);
    if (!decision.ok) {
      assert.equal(decision.error.code, 'INTERACTIVE_COMMAND');
      assert.equal(decision.risk, expectedRisk);
      assert.deepEqual(decision.error.details, {
        targetKind: 'command',
        reason: 'uiInteraction',
      });
    }
  }
});

test('standard save, debug, and reload commands are enabled by default without policy entries', () => {
  for (const commandId of [
    'workbench.action.files.saveAll',
    'workbench.action.debug.start',
    'workbench.action.debug.continue',
    'workbench.action.debug.stop',
    'workbench.action.reloadWindow',
    'workbench.action.restartExtensionHost',
  ]) {
    const decision = new CommandPolicy().preflightCommand(input(commandId), true);
    assert.equal(decision.ok, true, commandId);
    if (decision.ok) assert.deepEqual(decision.arguments, []);
  }
  const withArguments = new CommandPolicy().preflightCommand(
    input('workbench.action.debug.start', ['unexpected']),
    true,
  );
  assert.equal(withArguments.ok, false);
  if (!withArguments.ok) assert.equal(withArguments.error.code, 'INVALID_ARGUMENT');
  const disabled = new CommandPolicy({
    allowStandardCommands: false,
    allowWorkspaceTasks: true,
    commands: [],
    tasks: [],
  }).preflightCommand(input('workbench.action.reloadWindow'), true);
  assert.equal(disabled.ok, false);
  if (!disabled.ok) assert.equal(disabled.error.code, 'INTERACTIVE_COMMAND');
});

test('no argument schema permits only an empty structured argument array', () => {
  const policy = new CommandPolicy({ commands: [entry('fixture.complete')], tasks: [] });
  const allowed = policy.preflightCommand(input('fixture.complete', [], 20_000), true);
  assert.deepEqual(allowed, {
    ok: true,
    entry: entry('fixture.complete'),
    arguments: [],
    effectiveTimeoutMs: 10_000,
  });
  const denied = policy.preflightCommand(input('fixture.complete', ['value']), true);
  assert.equal(denied.ok, false);
  if (!denied.ok) assert.equal(denied.error.code, 'INVALID_ARGUMENT');
});

test('closed Draft 2020-12 argument schemas preserve structured values without command concatenation', () => {
  const argumentSchema = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    type: 'array',
    prefixItems: [{
      type: 'object',
      properties: {
        file: {
          type: 'string',
          'x-vscode-lsp-mcp-logicalPath': true,
        },
        literal: { type: 'string' },
      },
      required: ['file', 'literal'],
      additionalProperties: false,
    }],
    minItems: 1,
    maxItems: 1,
    items: false,
  };
  const policy = new CommandPolicy({
    commands: [entry('fixture.complete', argumentSchema)],
    tasks: [],
  });
  const args = [{ file: 'app/src/index.ts', literal: 'first; second && third' }];
  const allowed = policy.preflightCommand(input('fixture.complete', args), true);
  assert.equal(allowed.ok, true);
  if (allowed.ok) {
    assert.deepEqual(allowed.arguments, args);
    assert.notEqual(allowed.arguments, args);
    assert.equal(Object.isFrozen(allowed.arguments), true);
  }
  const extraProperty = policy.preflightCommand(input('fixture.complete', [{
    file: 'app/src/index.ts', literal: 'value', extra: true,
  }]), true);
  assert.equal(extraProperty.ok, false);
  if (!extraProperty.ok) assert.equal(extraProperty.error.code, 'INVALID_ARGUMENT');
});

test('input and command variables are rejected recursively before invocation', () => {
  const schema = {
    type: 'array',
    items: {
      type: 'object',
      additionalProperties: false,
      properties: { nested: { type: 'array', items: { type: 'string' } } },
      required: ['nested'],
    },
  };
  const policy = new CommandPolicy({
    commands: [entry('fixture.complete', schema)],
    tasks: [],
  });
  for (const [value, reason] of [
    ['${input:pickTarget}', 'inputVariable'],
    ['prefix-${command:resolveTarget}', 'commandVariable'],
  ] as const) {
    const decision = policy.preflightCommand(input('fixture.complete', [{ nested: [value] }]), true);
    assert.equal(decision.ok, false);
    if (!decision.ok) {
      assert.equal(decision.error.code, 'INTERACTIVE_COMMAND');
      assert.equal(decision.error.details?.reason, reason);
    }
  }
});

test('malformed or open schemas and duplicate entries disable the policy fail-closed', () => {
  const cases = [
    { commands: [entry('fixture.complete', {
      type: 'array', items: { type: 'object', properties: { value: { type: 'string' } } },
    })], tasks: [] },
    { commands: [entry('fixture.complete'), entry('fixture.complete')], tasks: [] },
    { commands: [{ ...entry('fixture.complete'), nonInteractive: false }], tasks: [] },
  ];
  for (const configuration of cases) {
    const decision = createFailClosedCommandPolicyDecision(
      configuration,
      input('fixture.complete'),
      true,
    );
    assert.equal(decision.ok, false);
    if (!decision.ok) {
      assert.equal(decision.error.code, 'COMMAND_NOT_ALLOWED');
      assert.equal(typeof decision.configurationIssue, 'string');
    }
  }
});

test('task allowlist entries are exact, bounded configuration inputs for P5-002', () => {
  const policy = new CommandPolicy({
    commands: [],
    tasks: [{
      rootAlias: 'app',
      taskName: 'build',
      nonInteractive: true,
      allowDependencies: true,
      maxTimeoutMs: 60_000,
    }],
  });
  assert.deepEqual(policy.configuration.tasks, [{
    rootAlias: 'app',
    taskName: 'build',
    nonInteractive: true,
    allowDependencies: true,
    maxTimeoutMs: 60_000,
  }]);
  assert.equal(policy.configuration.allowStandardCommands, true);
  assert.equal(policy.configuration.allowWorkspaceTasks, true);
  assert.equal(Object.isFrozen(policy.configuration.tasks), true);
});

test('trusted-workspace tasks resolve by default while explicit entries can narrow limits', () => {
  const defaults = new CommandPolicy();
  assert.deepEqual(defaults.taskEntry('app', 'build'), {
    rootAlias: 'app',
    taskName: 'build',
    nonInteractive: true,
    allowDependencies: true,
    maxTimeoutMs: 600_000,
  });
  const restricted = new CommandPolicy({
    allowStandardCommands: true,
    allowWorkspaceTasks: false,
    commands: [],
    tasks: [{
      rootAlias: 'app',
      taskName: 'test',
      nonInteractive: true,
      allowDependencies: false,
      maxTimeoutMs: 30_000,
    }],
  });
  assert.equal(restricted.taskEntry('app', 'build'), undefined);
  assert.equal(restricted.taskEntry('app', 'test')?.maxTimeoutMs, 30_000);
});
