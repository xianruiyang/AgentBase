import assert from 'node:assert/strict';
import test from 'node:test';
import { parseCapabilitiesBridgeResponse } from './capability-bridge.js';

test('capability bridge parser preserves the four public states and safe reasons', () => {
  assert.deepEqual(parseCapabilitiesBridgeResponse({
    status: 'completed',
    candidates: [
      { name: 'documentSymbols', status: 'available' },
      { name: 'definition', status: 'unknown', reason: 'probe_returned_no_evidence' },
      { name: 'rename', status: 'unavailable', reason: 'provider_command_unavailable' },
      { name: 'typeHierarchy', status: 'timedOut', reason: 'provider_timed_out' },
    ],
  }), {
    status: 'completed',
    candidates: [
      { name: 'documentSymbols', status: 'available' },
      { name: 'definition', status: 'unknown', reason: 'probe_returned_no_evidence' },
      { name: 'rename', status: 'unavailable', reason: 'provider_command_unavailable' },
      { name: 'typeHierarchy', status: 'timedOut', reason: 'provider_timed_out' },
    ],
  });
  assert.deepEqual(parseCapabilitiesBridgeResponse({ status: 'failed' }), { status: 'failed' });
});

test('capability bridge parser rejects duplicates, invented reasons, and mixed terminal fields', () => {
  assert.throws(() => parseCapabilitiesBridgeResponse({
    status: 'completed',
    candidates: [
      { name: 'definition', status: 'unknown', reason: 'probe_failed' },
      { name: 'definition', status: 'unknown', reason: 'provider_not_ready' },
    ],
  }), TypeError);
  assert.throws(() => parseCapabilitiesBridgeResponse({
    status: 'completed',
    candidates: [{ name: 'definition', status: 'unknown', reason: 'raw_provider_error' }],
  }), TypeError);
  assert.throws(() => parseCapabilitiesBridgeResponse({
    status: 'completed',
    candidates: [{ name: 'definition', status: 'available', reason: 'probe_failed' }],
  }), TypeError);
  assert.throws(() => parseCapabilitiesBridgeResponse({ status: 'failed', candidates: [] }), TypeError);
});
