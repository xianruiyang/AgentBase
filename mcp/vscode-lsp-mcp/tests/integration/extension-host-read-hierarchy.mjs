import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const componentRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const npmCliPath = process.env.npm_execpath;
if (!npmCliPath) {
  throw new Error('npm_execpath is required; run this suite through npm run test:integration:read-hierarchy.');
}

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'vscode-lsp-mcp-p6-002-'));
const stageBReportPath = path.join(temporaryRoot, 'stage-b.json');
const stageCReportPath = path.join(temporaryRoot, 'stage-c.json');

const runGate = (script, environment) => {
  const result = spawnSync(process.execPath, [npmCliPath, 'run', script], {
    cwd: componentRoot,
    env: { ...process.env, ...environment },
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `${script} failed with exit code ${result.status}.`);
};

const readJson = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));

try {
  runGate('test:stage-b', { STAGE_B_REPORT_PATH: stageBReportPath });
  runGate('test:stage-c', { STAGE_C_REPORT_PATH: stageCReportPath });

  const stageB = await readJson(stageBReportPath);
  const stageC = await readJson(stageCReportPath);

  assert.equal(stageB.companionActiveAfterExplicitActivation, true);
  assert.equal(stageB.semanticDocumentsInitiallyClosed, true);
  assert.equal(stageB.closedDocumentsActivatedWithoutEditor, 5);
  assert.equal(stageB.dirtyDocumentRemainedUnsaved, true);
  assert.equal(stageB.diskRemainedOriginal, true);
  assert.equal(stageB.knownPositionDefinition, true);
  assert.equal(stageB.dirtyDefinitionFound, true);
  assert.equal(stageB.dirtyReferenceFound, true);
  assert.ok(stageB.dirtySymbolsReturned > 0);
  assert.ok(stageB.dirtyCallHierarchyReturned > 0);
  assert.equal(stageB.dirtyTypeHierarchyReturned, 3);
  assert.equal(stageB.unsupportedCallHierarchyReturned, 0);
  assert.equal(stageB.unsupportedTypeHierarchyReturned, 0);
  assert.equal(stageB.unsupportedCapabilityStatus, 'unknown');
  assert.equal(stageB.unsupportedCapabilityReason, 'probe_returned_no_evidence');
  assert.equal(stageB.leakageChecksPassed, true);

  assert.equal(stageC.workspaceAbsentBeforeActivation, true);
  assert.equal(stageC.workspaceDiscoveredAfterActivation, true);
  assert.equal(stageC.supportedEntries, 3);
  assert.equal(stageC.emptyEntries, 0);
  assert.equal(stageC.emptyCapabilityStatus, 'unknown');
  assert.equal(stageC.emptyCapabilityReason, 'probe_returned_no_evidence');
  assert.equal(stageC.timeoutErrorCode, 'PROVIDER_TIMEOUT');
  assert.equal(stageC.responsiveAfterTimeout, true);
  assert.equal(stageC.responsiveAfterCancel, true);
  assert.equal(stageC.workspaceIdChanged, true);
  assert.equal(stageC.oldRouteErrorCode, 'WORKSPACE_DISCONNECTED');
  assert.equal(stageC.noReplayProviderCalls, 0);
  assert.equal(stageC.recoveredProviderCalls, 1);
  assert.equal(stageC.leakageChecksPassed, true);

  const report = {
    schemaVersion: 1,
    task: 'P6-002',
    vscodeVersion: stageB.vscodeVersion,
    activation: {
      workspaceAbsentBeforeCompanionActivation: stageC.workspaceAbsentBeforeActivation,
      workspaceDiscoveredAfterCompanionActivation: stageC.workspaceDiscoveredAfterActivation,
      companionActiveBeforeExplicitActivation: stageB.companionActiveBeforeExplicitActivation,
      companionActiveAfterExplicitActivation: stageB.companionActiveAfterExplicitActivation,
    },
    documentState: {
      initiallyClosed: stageB.semanticDocumentsInitiallyClosed,
      activatedWithoutVisibleEditor: stageB.closedDocumentsActivatedWithoutEditor,
      dirtyRemainedUnsaved: stageB.dirtyDocumentRemainedUnsaved,
      dirtyDocumentVisible: stageB.dirtyDocumentVisible,
      dirtyDiskRemainedOriginal: stageB.diskRemainedOriginal,
    },
    matrix: {
      definition: { closedDocument: true, dirtyDocument: stageB.dirtyDefinitionFound },
      references: { closedDocument: true, dirtyDocument: stageB.dirtyReferenceFound },
      documentSymbols: { closedDocument: stageB.hiddenSymbolsReturned > 0, dirtyDocument: stageB.dirtySymbolsReturned > 0 },
      workspaceSymbols: { workspaceScoped: true, documentState: 'not_applicable' },
      diagnostics: { dirtyDocument: stageB.diagnosticsReturned > 0, closedDocument: 'not_applicable' },
      capabilities: {
        dirtyDocument: stageB.capabilityAvailable > 0,
        unsupportedStatus: stageB.unsupportedCapabilityStatus,
        unsupportedReason: stageB.unsupportedCapabilityReason,
      },
      callHierarchy: {
        closedDocument: stageB.callHierarchyReturned > 0,
        dirtyDocument: stageB.dirtyCallHierarchyReturned > 0,
        unsupportedReturnsEmpty: stageB.unsupportedCallHierarchyReturned === 0,
      },
      typeHierarchy: {
        closedDocument: stageB.typeHierarchyReturned > 0,
        dirtyDocument: stageB.dirtyTypeHierarchyReturned > 0,
        unsupportedReturnsEmpty: stageB.unsupportedTypeHierarchyReturned === 0,
      },
    },
    lifecycle: {
      emptyIsSuccessfulCollection: stageC.emptyEntries === 0,
      timeoutErrorCode: stageC.timeoutErrorCode,
      cancellationDispatched: stageC.cancellationDispatched,
      responsiveAfterTimeout: stageC.responsiveAfterTimeout,
      responsiveAfterCancel: stageC.responsiveAfterCancel,
      staleRouteNotReplayed: stageC.noReplayProviderCalls === 0,
      recoveredWithNewWorkspaceId: stageC.workspaceIdChanged && stageC.recoveredProviderCalls === 1,
    },
    boundedResults: {
      referencesAvailable: stageB.referenceAvailable,
      referencesReturned: stageB.referenceWindowReturned,
      workspaceSymbolsAvailable: stageB.workspaceSymbolAvailable,
      workspaceSymbolsReturned: stageB.workspaceSymbolWindowReturned,
    },
    leakageChecksPassed: stageB.leakageChecksPassed && stageC.leakageChecksPassed,
  };

  const outputPath = process.env.P6_002_REPORT_PATH;
  if (outputPath !== undefined && outputPath.length > 0) {
    await mkdir(path.dirname(outputPath), { recursive: true });
    await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  }
  process.stdout.write(`P6-002 integration report:\n${JSON.stringify(report, null, 2)}\n`);
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}
