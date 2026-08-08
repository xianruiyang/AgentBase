import {
  CAPABILITY_NAMES,
  type Capability,
  type CapabilityName,
} from './dto.js';

export const CAPABILITIES_BRIDGE_METHOD = 'capabilities.probe' as const;

export const CAPABILITY_PROBE_REASONS = [
  'document_required',
  'execution_policy_not_configured',
  'probe_cancelled',
  'probe_failed',
  'probe_returned_no_evidence',
  'provider_command_unavailable',
  'provider_not_ready',
  'provider_timed_out',
] as const;

export type CapabilityProbeReason = (typeof CAPABILITY_PROBE_REASONS)[number];

export type CapabilitiesBridgeResponse =
  | {
      readonly status: 'completed';
      readonly candidates: readonly Capability[];
    }
  | { readonly status: 'failed' };

const capabilityNames = new Set<CapabilityName>(CAPABILITY_NAMES);
const capabilityStatuses = new Set<Capability['status']>([
  'available',
  'unavailable',
  'unknown',
  'timedOut',
]);
const capabilityReasons = new Set<CapabilityProbeReason>(CAPABILITY_PROBE_REASONS);

const asRecord = (value: unknown, label: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
};

const exactFields = (
  value: Record<string, unknown>,
  allowed: readonly string[],
  label: string,
): void => {
  const allowedSet = new Set(allowed);
  if (Object.keys(value).some((field) => !allowedSet.has(field))) {
    throw new TypeError(`${label} contains an unknown field.`);
  }
};

const parseCandidate = (value: unknown, index: number): Capability => {
  const label = `capability candidate ${index}`;
  const record = asRecord(value, label);
  exactFields(record, ['name', 'status', 'reason'], label);
  if (typeof record.name !== 'string' || !capabilityNames.has(record.name as CapabilityName)) {
    throw new TypeError(`${label}.name is invalid.`);
  }
  if (typeof record.status !== 'string' ||
      !capabilityStatuses.has(record.status as Capability['status'])) {
    throw new TypeError(`${label}.status is invalid.`);
  }
  if (record.status === 'available') {
    if (record.reason !== undefined) {
      throw new TypeError(`${label}.reason is forbidden for available capabilities.`);
    }
    return Object.freeze({
      name: record.name as CapabilityName,
      status: 'available',
    });
  }
  if (typeof record.reason !== 'string' ||
      !capabilityReasons.has(record.reason as CapabilityProbeReason)) {
    throw new TypeError(`${label}.reason is required and invalid.`);
  }
  return Object.freeze({
    name: record.name as CapabilityName,
    status: record.status as Exclude<Capability['status'], 'available'>,
    reason: record.reason,
  });
};

export const parseCapabilitiesBridgeResponse = (value: unknown): CapabilitiesBridgeResponse => {
  const record = asRecord(value, 'capabilities bridge response');
  if (record.status === 'failed') {
    exactFields(record, ['status'], 'capabilities bridge response');
    return Object.freeze({ status: 'failed' });
  }
  if (record.status !== 'completed' || !Array.isArray(record.candidates)) {
    throw new TypeError('Capabilities bridge response is invalid.');
  }
  exactFields(record, ['status', 'candidates'], 'capabilities bridge response');
  const candidates = Object.freeze(record.candidates.map(parseCandidate));
  if (new Set(candidates.map((candidate) => candidate.name)).size !== candidates.length) {
    throw new TypeError('Capabilities bridge response contains duplicate capabilities.');
  }
  return Object.freeze({ status: 'completed', candidates });
};
