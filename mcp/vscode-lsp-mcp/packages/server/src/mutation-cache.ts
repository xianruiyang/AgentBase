import { Buffer } from 'node:buffer';
import {
  canonicalizeJson,
  systemRuntimePrimitives,
  type JsonObject,
  type JsonValue,
  type NormalizedWorkspaceEdit,
  type RuntimePrimitives,
  type TextDocumentSnapshot,
  type WorkspaceRouteIdentity,
} from '@simplechat/vscode-lsp-mcp-protocol';

export const PREVIEW_ACTIVE_TTL_MS = 300_000;
export const PREVIEW_TOMBSTONE_TTL_MS = 300_000;
export const ACTION_SET_TTL_MS = 120_000;

export interface MutationCacheLimits {
  readonly previewsPerClient: number;
  readonly previewsPerWorkspace: number;
  readonly actionSetsPerClient: number;
  readonly actionSetsPerWorkspace: number;
  readonly tombstonesPerClient: number;
  readonly sharedBytes: number;
  readonly frameBytes: number;
}

export const MUTATION_CACHE_LIMITS: MutationCacheLimits = Object.freeze({
  previewsPerClient: 64,
  previewsPerWorkspace: 16,
  actionSetsPerClient: 32,
  actionSetsPerWorkspace: 8,
  tombstonesPerClient: 256,
  sharedBytes: 64 * 1024 * 1024,
  frameBytes: 16 * 1024 * 1024,
});

export interface MutationCacheIdentity {
  readonly clientSessionId: string;
  readonly workspace: WorkspaceRouteIdentity;
}

interface OwnedMutationCacheIdentity {
  readonly clientSessionId: string;
  readonly workspace: {
    readonly workspaceId: WorkspaceRouteIdentity['workspaceId'];
    readonly generation: number;
  };
}

export type MutationOperationKind = 'rename' | 'codeAction' | 'format';

export interface PreviewCommitInput {
  readonly identity: MutationCacheIdentity;
  readonly operationKind: MutationOperationKind;
  readonly requestSummary: JsonObject;
  readonly normalizedEdit: NormalizedWorkspaceEdit;
}

export interface PreviewCommitResult {
  readonly previewId?: string;
}

export interface CachedPreview {
  readonly previewId: string;
  readonly applyAttemptId: string;
  readonly identity: OwnedMutationCacheIdentity;
  readonly operationKind: MutationOperationKind;
  readonly requestSummary: JsonObject;
  readonly normalizedEdit: NormalizedWorkspaceEdit;
  readonly createdAtMonotonic: number;
  readonly expiresAtMonotonic: number;
}

export type PreviewPeekResult =
  | { readonly status: 'active'; readonly preview: CachedPreview }
  | { readonly status: 'expired' }
  | { readonly status: 'notFound' };

export interface PreviewClaim {
  readonly preview: CachedPreview;
}

export type PreviewClaimResult =
  | { readonly status: 'claimed'; readonly claim: PreviewClaim }
  | { readonly status: 'expired' }
  | { readonly status: 'notFound' };

export interface ActionSetCandidateInput {
  readonly title: string;
  readonly kind?: string;
  readonly normalizedEdit: NormalizedWorkspaceEdit;
}

export interface ActionSetCommitInput {
  readonly identity: MutationCacheIdentity;
  readonly requestSummary: JsonObject;
  readonly sourceSnapshot: TextDocumentSnapshot;
  readonly candidates: readonly ActionSetCandidateInput[];
  readonly available: number;
}

export interface PublicCachedAction {
  readonly actionId: string;
  readonly title: string;
  readonly kind?: string;
}

export interface ActionSetCommitResult {
  readonly actionSetId?: string;
  readonly actions: readonly PublicCachedAction[];
  readonly available: number;
}

interface CachedAction extends PublicCachedAction {
  readonly normalizedEdit: NormalizedWorkspaceEdit;
}

export interface ActionClaim {
  readonly actionSetId: string;
  readonly action: CachedAction;
  readonly identity: OwnedMutationCacheIdentity;
  readonly requestSummary: JsonObject;
  readonly sourceSnapshot: TextDocumentSnapshot;
}

export type ActionClaimResult =
  | { readonly status: 'claimed'; readonly claim: ActionClaim }
  | { readonly status: 'notFound' };

export interface MutationCacheStats {
  readonly activePreviews: number;
  readonly applyingPreviews: number;
  readonly actionSets: number;
  readonly previewTombstones: number;
  readonly totalChargeBytes: number;
}

export type MutationCacheErrorReason =
  | 'capacity'
  | 'clock'
  | 'identity'
  | 'payload'
  | 'randomness';

export class MutationCacheError extends Error {
  readonly reason: MutationCacheErrorReason;

  constructor(reason: MutationCacheErrorReason, message: string) {
    super(message);
    this.name = 'MutationCacheError';
    this.reason = reason;
  }
}

interface ChargedPreview extends CachedPreview {
  readonly byteCharge: number;
  readonly sequence: number;
}

interface ActionSetRecord {
  readonly actionSetId: string;
  readonly identity: OwnedMutationCacheIdentity;
  readonly requestSummary: JsonObject;
  readonly sourceSnapshot: TextDocumentSnapshot;
  readonly actions: readonly CachedAction[];
  readonly available: number;
  readonly createdAtMonotonic: number;
  readonly expiresAtMonotonic: number;
  readonly byteCharge: number;
  readonly sequence: number;
}

interface PreviewTombstone {
  readonly previewId: string;
  readonly bindingKey: string;
  readonly state: 'consumed' | 'expired';
  readonly expiresAtMonotonic: number;
  readonly sequence: number;
  readonly clientSessionId: string;
}

interface ApplyingPreview {
  readonly record: ChargedPreview;
  readonly claim: PreviewClaim;
}

const deepFreeze = <T>(value: T): T => {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const nested of Array.isArray(value) ? value : Object.values(value)) {
      deepFreeze(nested);
    }
    Object.freeze(value);
  }
  return value;
};

const ownJson = <T>(value: T): T => {
  try {
    return deepFreeze(canonicalizeJson(value) as unknown as T);
  } catch {
    throw new MutationCacheError('payload', 'Mutation cache payload is not strict JSON.');
  }
};

const byteCharge = (value: JsonValue): number =>
  Buffer.byteLength(JSON.stringify(value), 'utf8');

const validateLimits = (limits: MutationCacheLimits): MutationCacheLimits => {
  for (const value of Object.values(limits)) {
    if (!Number.isSafeInteger(value) || value < 1) {
      throw new MutationCacheError('capacity', 'Mutation cache limits must be positive safe integers.');
    }
  }
  if (limits.frameBytes > limits.sharedBytes) {
    throw new MutationCacheError('capacity', 'Mutation cache frame limit exceeds its shared budget.');
  }
  return Object.freeze({ ...limits });
};

const mergeLimits = (overrides: Partial<MutationCacheLimits> | undefined): MutationCacheLimits =>
  validateLimits({ ...MUTATION_CACHE_LIMITS, ...overrides });

const bindingKey = (identity: OwnedMutationCacheIdentity): string =>
  `${identity.clientSessionId}\u0000${identity.workspace.workspaceId}\u0000${identity.workspace.generation}`;

const workspaceKey = (identity: OwnedMutationCacheIdentity): string =>
  `${identity.workspace.workspaceId}\u0000${identity.workspace.generation}`;

const sameBinding = (
  left: OwnedMutationCacheIdentity,
  right: MutationCacheIdentity,
): boolean => left.clientSessionId === right.clientSessionId &&
  left.workspace.workspaceId === right.workspace.workspaceId &&
  left.workspace.generation === right.workspace.generation;

const ownIdentity = (identity: MutationCacheIdentity): OwnedMutationCacheIdentity => {
  if (typeof identity.clientSessionId !== 'string' || identity.clientSessionId.length < 1 ||
      identity.clientSessionId.length > 512 || typeof identity.workspace.workspaceId !== 'string' ||
      !Number.isSafeInteger(identity.workspace.generation) || identity.workspace.generation < 1) {
    throw new MutationCacheError('identity', 'Mutation cache identity is invalid.');
  }
  return ownJson({
    clientSessionId: identity.clientSessionId,
    workspace: {
      workspaceId: identity.workspace.workspaceId,
      generation: identity.workspace.generation,
    },
  });
};

const assertClientSessionId = (clientSessionId: string): void => {
  if (typeof clientSessionId !== 'string' || clientSessionId.length < 1 ||
      clientSessionId.length > 512) {
    throw new MutationCacheError('identity', 'Mutation cache client session identity is invalid.');
  }
};

const assertNormalizedEditShape = (
  value: NormalizedWorkspaceEdit,
  allowEmpty: boolean,
): void => {
  if (!Array.isArray(value.textChanges) || !Array.isArray(value.targets) ||
      value.textChanges.length !== value.targets.length ||
      (!allowEmpty && value.textChanges.length === 0)) {
    throw new MutationCacheError('payload', 'Normalized mutation payload has inconsistent targets.');
  }
};

export interface MutationCache {
  commitPreview(input: PreviewCommitInput): PreviewCommitResult;
  peekPreview(identity: MutationCacheIdentity, previewId: string): PreviewPeekResult;
  peekPreviewForClient(clientSessionId: string, previewId: string): PreviewPeekResult;
  claimPreview(identity: MutationCacheIdentity, previewId: string): PreviewClaimResult;
  claimPreviewForClient(clientSessionId: string, previewId: string): PreviewClaimResult;
  completePreviewClaim(claim: PreviewClaim): boolean;
  commitActionSet(input: ActionSetCommitInput): ActionSetCommitResult;
  claimAction(
    identity: MutationCacheIdentity,
    actionSetId: string,
    actionId: string,
  ): ActionClaimResult;
  claimActionForClient(
    clientSessionId: string,
    actionSetId: string,
    actionId: string,
  ): ActionClaimResult;
  invalidateActionSet(claim: ActionClaim): boolean;
  stats(): MutationCacheStats;
}

class MutationCacheImpl implements MutationCache {
  readonly #primitives: RuntimePrimitives;
  readonly #limits: MutationCacheLimits;
  readonly #activePreviews = new Map<string, ChargedPreview>();
  readonly #applyingPreviews = new Map<string, ApplyingPreview>();
  readonly #previewTombstones = new Map<string, PreviewTombstone>();
  readonly #actionSets = new Map<string, ActionSetRecord>();
  #lastNow = -1;
  #nextSequence = 1;
  #totalChargeBytes = 0;

  constructor(primitives: RuntimePrimitives, limits: MutationCacheLimits) {
    this.#primitives = primitives;
    this.#limits = limits;
  }

  #now(): number {
    const now = this.#primitives.monotonicNowMs();
    if (!Number.isFinite(now) || now < 0 || now > Number.MAX_SAFE_INTEGER || now < this.#lastNow) {
      throw new MutationCacheError('clock', 'Mutation cache monotonic clock is invalid.');
    }
    this.#lastNow = now;
    return now;
  }

  #sequence(): number {
    if (!Number.isSafeInteger(this.#nextSequence) || this.#nextSequence < 1) {
      throw new MutationCacheError('capacity', 'Mutation cache sequence capacity was exhausted.');
    }
    const sequence = this.#nextSequence;
    this.#nextSequence += 1;
    return sequence;
  }

  #expiry(now: number, ttl: number): number {
    const expiresAt = now + ttl;
    if (!Number.isFinite(expiresAt) || expiresAt > Number.MAX_SAFE_INTEGER) {
      throw new MutationCacheError('clock', 'Mutation cache expiration exceeds the safe timestamp range.');
    }
    return expiresAt;
  }

  #hasId(id: string): boolean {
    if (this.#activePreviews.has(id) || this.#applyingPreviews.has(id) ||
        this.#previewTombstones.has(id) || this.#actionSets.has(id)) return true;
    for (const preview of this.#activePreviews.values()) {
      if (preview.applyAttemptId === id) return true;
    }
    for (const applying of this.#applyingPreviews.values()) {
      if (applying.record.applyAttemptId === id) return true;
    }
    for (const set of this.#actionSets.values()) {
      if (set.actions.some((action) => action.actionId === id)) return true;
    }
    return false;
  }

  #id(prefix: 'ac_' | 'ap_' | 'as_' | 'pv_'): string {
    for (let attempt = 0; attempt < 32; attempt += 1) {
      const bytes = this.#primitives.secureRandomBytes(16);
      if (!(bytes instanceof Uint8Array) || bytes.length !== 16) {
        throw new MutationCacheError('randomness', 'Mutation cache CSPRNG returned an invalid byte sequence.');
      }
      const id = `${prefix}${Buffer.from(bytes).toString('base64url')}`;
      if (!this.#hasId(id)) return id;
    }
    throw new MutationCacheError('randomness', 'Mutation cache could not allocate a unique handle.');
  }

  #addTombstone(
    record: ChargedPreview,
    state: PreviewTombstone['state'],
    expiresAt: number,
    now: number,
  ): void {
    if (expiresAt <= now) return;
    this.#previewTombstones.set(record.previewId, Object.freeze({
      previewId: record.previewId,
      bindingKey: bindingKey(record.identity),
      clientSessionId: record.identity.clientSessionId,
      state,
      expiresAtMonotonic: expiresAt,
      sequence: this.#sequence(),
    }));
    this.#trimTombstones(record.identity.clientSessionId);
  }

  #trimTombstones(clientSessionId: string): void {
    const candidates = [...this.#previewTombstones.values()]
      .filter((candidate) => candidate.clientSessionId === clientSessionId)
      .sort((left, right) => left.sequence - right.sequence);
    while (candidates.length > this.#limits.tombstonesPerClient) {
      const removed = candidates.shift();
      if (removed !== undefined) this.#previewTombstones.delete(removed.previewId);
    }
  }

  #removeActivePreview(id: string): boolean {
    const record = this.#activePreviews.get(id);
    if (record === undefined) return false;
    this.#activePreviews.delete(id);
    this.#totalChargeBytes -= record.byteCharge;
    return true;
  }

  #removeActionSet(id: string): boolean {
    const record = this.#actionSets.get(id);
    if (record === undefined) return false;
    this.#actionSets.delete(id);
    this.#totalChargeBytes -= record.byteCharge;
    return true;
  }

  #cleanup(now: number): void {
    for (const record of [...this.#activePreviews.values()]) {
      if (record.expiresAtMonotonic <= now) {
        this.#removeActivePreview(record.previewId);
        this.#addTombstone(
          record,
          'expired',
          this.#expiry(record.expiresAtMonotonic, PREVIEW_TOMBSTONE_TTL_MS),
          now,
        );
      }
    }
    for (const record of [...this.#actionSets.values()]) {
      if (record.expiresAtMonotonic <= now) this.#removeActionSet(record.actionSetId);
    }
    for (const tombstone of [...this.#previewTombstones.values()]) {
      if (tombstone.expiresAtMonotonic <= now) {
        this.#previewTombstones.delete(tombstone.previewId);
      }
    }
  }

  #oldestPreview(predicate: (record: ChargedPreview) => boolean): ChargedPreview | undefined {
    let oldest: ChargedPreview | undefined;
    for (const record of this.#activePreviews.values()) {
      if (predicate(record) && (oldest === undefined || record.sequence < oldest.sequence)) {
        oldest = record;
      }
    }
    return oldest;
  }

  #oldestActionSet(predicate: (record: ActionSetRecord) => boolean): ActionSetRecord | undefined {
    let oldest: ActionSetRecord | undefined;
    for (const record of this.#actionSets.values()) {
      if (predicate(record) && (oldest === undefined || record.sequence < oldest.sequence)) {
        oldest = record;
      }
    }
    return oldest;
  }

  #evictOldestActive(): boolean {
    const preview = this.#oldestPreview(() => true);
    const actionSet = this.#oldestActionSet(() => true);
    if (preview === undefined && actionSet === undefined) return false;
    if (actionSet === undefined ||
        (preview !== undefined && preview.sequence < actionSet.sequence)) {
      return this.#removeActivePreview(preview?.previewId ?? '');
    }
    return this.#removeActionSet(actionSet.actionSetId);
  }

  #ensurePreviewCounts(identity: OwnedMutationCacheIdentity): void {
    while ([...this.#activePreviews.values()].filter((record) =>
      record.identity.clientSessionId === identity.clientSessionId).length >=
      this.#limits.previewsPerClient) {
      const oldest = this.#oldestPreview((record) =>
        record.identity.clientSessionId === identity.clientSessionId);
      if (oldest === undefined) break;
      this.#removeActivePreview(oldest.previewId);
    }
    const key = workspaceKey(identity);
    while ([...this.#activePreviews.values()].filter((record) =>
      workspaceKey(record.identity) === key).length >= this.#limits.previewsPerWorkspace) {
      const oldest = this.#oldestPreview((record) => workspaceKey(record.identity) === key);
      if (oldest === undefined) break;
      this.#removeActivePreview(oldest.previewId);
    }
  }

  #ensureActionSetCounts(identity: OwnedMutationCacheIdentity): void {
    while ([...this.#actionSets.values()].filter((record) =>
      record.identity.clientSessionId === identity.clientSessionId).length >=
      this.#limits.actionSetsPerClient) {
      const oldest = this.#oldestActionSet((record) =>
        record.identity.clientSessionId === identity.clientSessionId);
      if (oldest === undefined) break;
      this.#removeActionSet(oldest.actionSetId);
    }
    const key = workspaceKey(identity);
    while ([...this.#actionSets.values()].filter((record) =>
      workspaceKey(record.identity) === key).length >= this.#limits.actionSetsPerWorkspace) {
      const oldest = this.#oldestActionSet((record) => workspaceKey(record.identity) === key);
      if (oldest === undefined) break;
      this.#removeActionSet(oldest.actionSetId);
    }
  }

  #ensureCharge(newCharge: number): void {
    if (!Number.isSafeInteger(newCharge) || newCharge < 1 ||
        newCharge > this.#limits.frameBytes || newCharge > this.#limits.sharedBytes) {
      throw new MutationCacheError('capacity', 'Mutation cache entry exceeds its bounded payload size.');
    }
    if (this.#totalChargeBytes + newCharge <= this.#limits.sharedBytes) return;
    const previewsBefore = new Map(this.#activePreviews);
    const actionSetsBefore = new Map(this.#actionSets);
    const chargeBefore = this.#totalChargeBytes;
    while (this.#totalChargeBytes + newCharge > this.#limits.sharedBytes) {
      if (!this.#evictOldestActive()) {
        this.#activePreviews.clear();
        this.#actionSets.clear();
        for (const [id, record] of previewsBefore) this.#activePreviews.set(id, record);
        for (const [id, record] of actionSetsBefore) this.#actionSets.set(id, record);
        this.#totalChargeBytes = chargeBefore;
        throw new MutationCacheError('capacity', 'Mutation cache shared payload budget is exhausted.');
      }
    }
  }

  commitPreview(input: PreviewCommitInput): PreviewCommitResult {
    const now = this.#now();
    this.#cleanup(now);
    const identity = ownIdentity(input.identity);
    assertNormalizedEditShape(input.normalizedEdit, true);
    if (input.normalizedEdit.textChanges.length === 0) return Object.freeze({});
    const previewId = this.#id('pv_');
    const applyAttemptId = this.#id('ap_');
    const base = ownJson({
      previewId,
      applyAttemptId,
      identity,
      operationKind: input.operationKind,
      requestSummary: input.requestSummary,
      normalizedEdit: input.normalizedEdit,
      createdAtMonotonic: now,
      expiresAtMonotonic: this.#expiry(now, PREVIEW_ACTIVE_TTL_MS),
    }) as CachedPreview;
    const charge = byteCharge(base as unknown as JsonValue);
    const sequence = this.#sequence();
    this.#ensureCharge(charge);
    this.#ensurePreviewCounts(identity);
    const record: ChargedPreview = Object.freeze({
      ...base,
      byteCharge: charge,
      sequence,
    });
    this.#activePreviews.set(previewId, record);
    this.#totalChargeBytes += charge;
    return Object.freeze({ previewId });
  }

  #previewResult(identity: MutationCacheIdentity, previewId: string): PreviewPeekResult {
    const active = this.#activePreviews.get(previewId);
    if (active !== undefined && sameBinding(active.identity, identity)) {
      return Object.freeze({ status: 'active', preview: active });
    }
    const tombstone = this.#previewTombstones.get(previewId);
    if (tombstone !== undefined && tombstone.bindingKey === bindingKey(ownIdentity(identity)) &&
        tombstone.state === 'expired') {
      return Object.freeze({ status: 'expired' });
    }
    return Object.freeze({ status: 'notFound' });
  }

  #previewResultForClient(clientSessionId: string, previewId: string): PreviewPeekResult {
    assertClientSessionId(clientSessionId);
    const active = this.#activePreviews.get(previewId);
    if (active !== undefined && active.identity.clientSessionId === clientSessionId) {
      return Object.freeze({ status: 'active', preview: active });
    }
    const tombstone = this.#previewTombstones.get(previewId);
    if (tombstone !== undefined && tombstone.clientSessionId === clientSessionId &&
        tombstone.state === 'expired') {
      return Object.freeze({ status: 'expired' });
    }
    return Object.freeze({ status: 'notFound' });
  }

  peekPreview(identity: MutationCacheIdentity, previewId: string): PreviewPeekResult {
    const now = this.#now();
    this.#cleanup(now);
    return this.#previewResult(identity, previewId);
  }

  peekPreviewForClient(clientSessionId: string, previewId: string): PreviewPeekResult {
    const now = this.#now();
    this.#cleanup(now);
    return this.#previewResultForClient(clientSessionId, previewId);
  }

  claimPreview(identity: MutationCacheIdentity, previewId: string): PreviewClaimResult {
    const now = this.#now();
    this.#cleanup(now);
    const found = this.#previewResult(identity, previewId);
    if (found.status !== 'active') return found;
    const record = this.#activePreviews.get(previewId);
    if (record === undefined) return Object.freeze({ status: 'notFound' });
    this.#activePreviews.delete(previewId);
    const claim: PreviewClaim = Object.freeze({ preview: record });
    this.#applyingPreviews.set(previewId, Object.freeze({ record, claim }));
    return Object.freeze({ status: 'claimed', claim });
  }

  claimPreviewForClient(clientSessionId: string, previewId: string): PreviewClaimResult {
    const now = this.#now();
    this.#cleanup(now);
    const found = this.#previewResultForClient(clientSessionId, previewId);
    if (found.status !== 'active') return found;
    const record = this.#activePreviews.get(previewId);
    if (record === undefined) return Object.freeze({ status: 'notFound' });
    this.#activePreviews.delete(previewId);
    const claim: PreviewClaim = Object.freeze({ preview: record });
    this.#applyingPreviews.set(previewId, Object.freeze({ record, claim }));
    return Object.freeze({ status: 'claimed', claim });
  }

  completePreviewClaim(claim: PreviewClaim): boolean {
    const now = this.#now();
    this.#cleanup(now);
    const previewId = claim.preview.previewId;
    const applying = this.#applyingPreviews.get(previewId);
    if (applying === undefined || applying.claim !== claim) return false;
    this.#applyingPreviews.delete(previewId);
    this.#totalChargeBytes -= applying.record.byteCharge;
    this.#addTombstone(
      applying.record,
      'consumed',
      this.#expiry(now, PREVIEW_TOMBSTONE_TTL_MS),
      now,
    );
    return true;
  }

  #actionSetCharge(record: Omit<ActionSetRecord, 'byteCharge' | 'sequence'>): number {
    return byteCharge(record as unknown as JsonValue);
  }

  commitActionSet(input: ActionSetCommitInput): ActionSetCommitResult {
    const now = this.#now();
    this.#cleanup(now);
    const identity = ownIdentity(input.identity);
    if (!Number.isSafeInteger(input.available) || input.available < input.candidates.length ||
        input.candidates.length > 100) {
      throw new MutationCacheError('payload', 'ActionSet availability or result window is invalid.');
    }
    if (input.candidates.length === 0) {
      return Object.freeze({ actions: Object.freeze([]), available: input.available });
    }
    const actionSetId = this.#id('as_');
    const actions = input.candidates.map((candidate) => {
      if (typeof candidate.title !== 'string' || candidate.title.length < 1 ||
          (candidate.kind !== undefined &&
            (typeof candidate.kind !== 'string' || candidate.kind.length < 1))) {
        throw new MutationCacheError('payload', 'Cached code action metadata is invalid.');
      }
      assertNormalizedEditShape(candidate.normalizedEdit, false);
      return {
        actionId: this.#id('ac_'),
        title: candidate.title,
        ...(candidate.kind === undefined ? {} : { kind: candidate.kind }),
        normalizedEdit: candidate.normalizedEdit,
      };
    });
    const owned = ownJson({
      actionSetId,
      identity,
      requestSummary: input.requestSummary,
      sourceSnapshot: input.sourceSnapshot,
      actions,
      available: input.available,
      createdAtMonotonic: now,
      expiresAtMonotonic: this.#expiry(now, ACTION_SET_TTL_MS),
    }) as Omit<ActionSetRecord, 'byteCharge' | 'sequence'>;
    const charge = this.#actionSetCharge(owned);
    const sequence = this.#sequence();
    this.#ensureCharge(charge);
    this.#ensureActionSetCounts(identity);
    const record: ActionSetRecord = Object.freeze({
      ...owned,
      byteCharge: charge,
      sequence,
    });
    this.#actionSets.set(actionSetId, record);
    this.#totalChargeBytes += charge;
    return Object.freeze({
      actionSetId,
      actions: Object.freeze(record.actions.map((action) => Object.freeze({
        actionId: action.actionId,
        title: action.title,
        ...(action.kind === undefined ? {} : { kind: action.kind }),
      }))),
      available: record.available,
    });
  }

  claimAction(
    identity: MutationCacheIdentity,
    actionSetId: string,
    actionId: string,
  ): ActionClaimResult {
    const now = this.#now();
    this.#cleanup(now);
    const set = this.#actionSets.get(actionSetId);
    if (set === undefined || !sameBinding(set.identity, identity)) {
      return Object.freeze({ status: 'notFound' });
    }
    const action = set.actions.find((candidate) => candidate.actionId === actionId);
    if (action === undefined) return Object.freeze({ status: 'notFound' });
    this.#actionSets.delete(actionSetId);
    this.#totalChargeBytes -= set.byteCharge;
    const remaining = set.actions.filter((candidate) => candidate.actionId !== actionId);
    if (remaining.length > 0) {
      const base = {
        actionSetId: set.actionSetId,
        identity: set.identity,
        requestSummary: set.requestSummary,
        sourceSnapshot: set.sourceSnapshot,
        actions: Object.freeze(remaining),
        available: set.available,
        createdAtMonotonic: set.createdAtMonotonic,
        expiresAtMonotonic: set.expiresAtMonotonic,
      };
      const charge = this.#actionSetCharge(base);
      const updated: ActionSetRecord = Object.freeze({
        ...base,
        byteCharge: charge,
        sequence: set.sequence,
      });
      this.#actionSets.set(actionSetId, updated);
      this.#totalChargeBytes += charge;
    }
    const claim: ActionClaim = Object.freeze({
      actionSetId,
      action,
      identity: set.identity,
      requestSummary: set.requestSummary,
      sourceSnapshot: set.sourceSnapshot,
    });
    return Object.freeze({ status: 'claimed', claim });
  }

  claimActionForClient(
    clientSessionId: string,
    actionSetId: string,
    actionId: string,
  ): ActionClaimResult {
    assertClientSessionId(clientSessionId);
    const now = this.#now();
    this.#cleanup(now);
    const set = this.#actionSets.get(actionSetId);
    if (set === undefined || set.identity.clientSessionId !== clientSessionId) {
      return Object.freeze({ status: 'notFound' });
    }
    return this.claimAction(set.identity, actionSetId, actionId);
  }

  invalidateActionSet(claim: ActionClaim): boolean {
    this.#cleanup(this.#now());
    const set = this.#actionSets.get(claim.actionSetId);
    if (set === undefined || bindingKey(set.identity) !== bindingKey(claim.identity)) return false;
    return this.#removeActionSet(set.actionSetId);
  }

  stats(): MutationCacheStats {
    this.#cleanup(this.#now());
    return Object.freeze({
      activePreviews: this.#activePreviews.size,
      applyingPreviews: this.#applyingPreviews.size,
      actionSets: this.#actionSets.size,
      previewTombstones: this.#previewTombstones.size,
      totalChargeBytes: this.#totalChargeBytes,
    });
  }
}

export const createMutationCache = (): MutationCache =>
  new MutationCacheImpl(systemRuntimePrimitives, MUTATION_CACHE_LIMITS);

export interface MutationCacheTestingOptions {
  readonly primitives: RuntimePrimitives;
  readonly limits?: Partial<MutationCacheLimits>;
}

export const createMutationCacheForTesting = (
  options: MutationCacheTestingOptions,
): MutationCache => new MutationCacheImpl(options.primitives, mergeLimits(options.limits));
