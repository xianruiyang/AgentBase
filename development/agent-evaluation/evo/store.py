"""Persistent Evo scheduling facts. SQLite owns state; receipts remain immutable files."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .spec import EvoError

ACTIVE = ('preparing', 'running', 'verifying')
RESOURCE_HELD = (*ACTIVE, 'uncertain')
TERMINAL = ('completed', 'failed', 'cancelled', 'uncertain')


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def positive(value: Any, label: str, maximum: int = 1_000_000_000) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise EvoError(f'{label} must be an integer in 1..{maximum}')
    return value


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / 'evo.sqlite3'

    @contextmanager
    def connect(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise EvoError('Evo state is not initialized; use evo init')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            if write:
                db.execute('BEGIN IMMEDIATE')
            try:
                yield db
            except BaseException:
                if write:
                    db.rollback()
                raise
            else:
                if write:
                    db.commit()
        finally:
            db.close()

    def migrate(self) -> None:
        """Apply additive runtime schema changes to an existing initialized state."""
        if not self.path.is_file():
            raise EvoError('Evo state is not initialized; use evo init')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
            for name, declaration in (
                ('reused_from', 'INTEGER'), ('workspace_slot', 'INTEGER'),
                ('disk_reservation', 'INTEGER NOT NULL DEFAULT 0'),
                ('attempt_seq', 'INTEGER NOT NULL DEFAULT 1'),
            ):
                if name not in columns:
                    db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {declaration}')
            # A retry is a fresh attempt. Preserve the prior zero-cost attempt in
            # events/attempt archives, while leaving current-attempt usage unknown.
            db.execute("UPDATE jobs SET usage=NULL,usage_complete=0 WHERE state='queued' "
                       "AND reason='explicit retry after confirmed non-invocation' "
                       "AND usage=0 AND usage_complete=1")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self, *, concurrency: int = 1, model_capacity: int = 4,
                   max_disk_mb: int = 4096, min_free_mb: int = 1024) -> dict:
        config = {'concurrency': positive(concurrency, 'concurrency', 64),
                  'model_capacity': positive(model_capacity, 'model_capacity', 256),
                  'max_disk_mb': positive(max_disk_mb, 'max_disk_mb'),
                  'min_free_mb': positive(min_free_mb, 'min_free_mb')}
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS studies (
                    id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    spec TEXT NOT NULL, project TEXT NOT NULL, work TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'ready', created REAL NOT NULL,
                    max_tokens INTEGER NOT NULL, concurrency INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, study INTEGER NOT NULL REFERENCES studies(id),
                    identity TEXT NOT NULL, plan TEXT NOT NULL, runtime TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued', reason TEXT,
                    model_slots INTEGER NOT NULL, token_reservation INTEGER NOT NULL,
                    usage INTEGER, usage_complete INTEGER NOT NULL DEFAULT 0,
                    started REAL, ended REAL, receipt TEXT, error TEXT,
                    reused_from INTEGER, workspace_slot INTEGER,
                    disk_reservation INTEGER NOT NULL DEFAULT 0,
                    attempt_seq INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(study,identity));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, study INTEGER, job INTEGER,
                    time REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
            for name, declaration in (
                ('reused_from', 'INTEGER'),
                ('workspace_slot', 'INTEGER'),
                ('disk_reservation', 'INTEGER NOT NULL DEFAULT 0'),
                ('attempt_seq', 'INTEGER NOT NULL DEFAULT 1'),
            ):
                if name not in columns:
                    db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {declaration}')
            previous = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
            if previous:
                if json.loads(previous[0]) != config:
                    raise EvoError('state already has different global limits; use its recorded limits')
            else:
                db.execute('INSERT INTO settings VALUES (1,?)', (canonical(config),))
            db.commit()
        finally:
            db.close()
        return config

    def config(self) -> dict:
        with self.connect() as db:
            return json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])

    @staticmethod
    def event(db, study, job, kind, payload):
        db.execute('INSERT INTO events(study,job,time,kind,payload) VALUES(?,?,?,?,?)',
                   (study, job, time.time(), kind, canonical(payload)))

    def submit(self, spec: dict, jobs: list[dict], project: Path, work: Path) -> int:
        budget = spec.get('budget', {})
        max_tokens = positive(budget.get('max_tokens', 1_000_000), 'budget.max_tokens')
        concurrency = positive(budget.get('concurrency', 1), 'budget.concurrency', 64)
        identity = fingerprint({'spec': spec, 'jobs': jobs, 'project': str(project), 'work': str(work)})
        with self.connect(True) as db:
            previous = db.execute('SELECT id FROM studies WHERE identity=?', (identity,)).fetchone()
            if previous:
                return previous[0]
            study = db.execute('INSERT INTO studies(identity,name,spec,project,work,created,max_tokens,concurrency) '
                               'VALUES(?,?,?,?,?,?,?,?)', (identity, spec['id'], canonical(spec), str(project),
                               str(work), time.time(), max_tokens, concurrency)).lastrowid
            for job in jobs:
                runtime = job['runtime']
                is_model = runtime['adapter'] == 'codex'
                slots = positive(runtime.get('max_agents', 1), 'max_agents', 256) if is_model else 0
                reservation = positive(runtime.get('token_reservation', 100_000), 'token_reservation') if is_model else 0
                disk_reservation = sum(entry['bytes'] for entries in job.get('source_inventory', {}).values() for entry in entries)
                db.execute('INSERT INTO jobs(study,identity,plan,runtime,model_slots,token_reservation,disk_reservation) VALUES(?,?,?,?,?,?,?)',
                           (study, job['execution_identity'], canonical(job), canonical(runtime), slots, reservation, disk_reservation))
            self.event(db, study, None, 'submitted', {'job_count': len(jobs)})
            return study

    def study(self, study: int) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM studies WHERE id=?', (study,)).fetchone()
            if not row:
                raise EvoError(f'unknown study s{study}')
            value = dict(row)
            value['spec'] = json.loads(value['spec'])
            return value

    def jobs(self, study: int | None = None) -> list[dict]:
        with self.connect() as db:
            query = 'SELECT * FROM jobs' + (' WHERE study=?' if study is not None else '') + ' ORDER BY id'
            rows = db.execute(query, (study,) if study is not None else ()).fetchall()
            values = []
            for row in rows:
                value = dict(row)
                value['plan'], value['runtime'] = json.loads(value['plan']), json.loads(value['runtime'])
                values.append(value)
            return values

    def work_roots(self) -> list[Path]:
        with self.connect() as db:
            return [Path(row[0]) for row in db.execute('SELECT DISTINCT work FROM studies ORDER BY work')]

    def claim(self, study_filter: int | None = None, exclude: set[int] | None = None) -> dict | None:
        config = self.config()
        with self.connect(True) as db:
            active = db.execute("SELECT * FROM jobs WHERE state IN ('preparing','running','verifying','uncertain')").fetchall()
            if len(active) >= config['concurrency']:
                return None
            models_used = sum(row['model_slots'] for row in active)
            # Round-robin by least recent dispatch, then FIFO. Resource-blocked jobs do not block others.
            query = "SELECT j.*,s.max_tokens,s.concurrency FROM jobs j JOIN studies s ON s.id=j.study WHERE j.state='queued' AND s.state='ready'"
            params = ()
            if study_filter is not None:
                query += ' AND j.study=?'
                params = (study_filter,)
            if exclude:
                query += ' AND j.id NOT IN (' + ','.join('?' for _ in exclude) + ')'
                params = (*params, *sorted(exclude))
            query += ' ORDER BY (SELECT COALESCE(MAX(started),0) FROM jobs h WHERE h.study=j.study),j.id'
            for row in db.execute(query, params).fetchall():
                reason = None
                reusable = db.execute(
                    "SELECT id,state,receipt,usage_complete FROM jobs WHERE identity=? AND id<>? "
                    "AND state IN ('completed','awaiting_human') AND receipt IS NOT NULL ORDER BY ended LIMIT 1",
                    (row['identity'], row['id'])).fetchone()
                if reusable:
                    db.execute("UPDATE jobs SET state=?,reason='reused existing execution receipt',receipt=?,usage=0,"
                               "usage_complete=1,reused_from=?,started=?,ended=? WHERE id=?",
                               (reusable['state'], reusable['receipt'], reusable['id'], time.time(), time.time(), row['id']))
                    self.event(db, row['study'], row['id'], 'reused', {'source_job': reusable['id'], 'new_usage': 0})
                    continue
                duplicate = db.execute(
                    "SELECT id FROM jobs WHERE identity=? AND id<>? AND state IN ('preparing','running','verifying') LIMIT 1",
                    (row['identity'], row['id'])).fetchone()
                if duplicate:
                    db.execute('UPDATE jobs SET reason=? WHERE id=?',
                               (f'waiting for identical execution j{duplicate[0]}', row['id']))
                    continue
                same = [j for j in active if j['study'] == row['study']]
                if len(same) >= row['concurrency']:
                    reason = 'study concurrency limit'
                elif models_used + row['model_slots'] > config['model_capacity']:
                    reason = 'model capacity (including reserved descendants)'
                settled = db.execute('SELECT COALESCE(SUM(usage),0) FROM jobs WHERE study=?', (row['study'],)).fetchone()[0]
                reserved = sum(j['token_reservation'] for j in same)
                unresolved = db.execute("SELECT COUNT(*) FROM jobs WHERE study=? AND model_slots>0 AND state IN ('failed','uncertain','cancelled','completed','awaiting_human') AND usage_complete=0", (row['study'],)).fetchone()[0]
                if row['model_slots'] and unresolved:
                    reason = 'unsettled model usage; reconcile before new model calls'
                elif settled + reserved + row['token_reservation'] > row['max_tokens']:
                    reason = 'study token budget'
                if reason:
                    db.execute('UPDATE jobs SET reason=? WHERE id=?', (reason, row['id']))
                    continue
                used_slots = {j['workspace_slot'] for j in active if j['workspace_slot'] is not None}
                slot = next((number for number in range(1, config['concurrency'] + 1) if number not in used_slots), None)
                if slot is None:
                    db.execute('UPDATE jobs SET reason=? WHERE id=?', ('no writable workspace slot available', row['id']))
                    continue
                db.execute("UPDATE jobs SET state='preparing',reason=NULL,started=?,workspace_slot=? WHERE id=?", (time.time(), slot, row['id']))
                self.event(db, row['study'], row['id'], 'claimed', {'model_slots': row['model_slots'], 'token_reservation': row['token_reservation']})
                value = dict(row)
                value['workspace_slot'] = slot
                value['plan'], value['runtime'] = json.loads(value['plan']), json.loads(value['runtime'])
                return value
            return None

    def phase(self, job: int, state: str) -> None:
        if state not in ACTIVE:
            raise EvoError('invalid active phase')
        with self.connect(True) as db:
            row = db.execute('SELECT study,state FROM jobs WHERE id=?', (job,)).fetchone()
            if not row or (row['state'] not in ACTIVE and not (row['state'] == 'uncertain' and state == 'verifying')):
                raise EvoError('job is no longer active')
            db.execute('UPDATE jobs SET state=? WHERE id=?', (state, job))
            self.event(db, row['study'], job, state, {})

    def finish(self, job: int, state: str, *, receipt: str | None = None, usage: int | None = None,
               usage_complete: bool = False, error: str | None = None) -> None:
        if state not in (*TERMINAL, 'awaiting_human'):
            raise EvoError('invalid terminal state')
        if usage is not None and (type(usage) is not int or usage < 0):
            raise EvoError('usage must be a nonnegative integer or unknown')
        with self.connect(True) as db:
            row = db.execute('SELECT study FROM jobs WHERE id=?', (job,)).fetchone()
            if not row:
                raise EvoError('unknown job')
            db.execute('UPDATE jobs SET state=?,receipt=?,usage=?,usage_complete=?,error=?,ended=? WHERE id=?',
                       (state, receipt, usage, int(usage_complete), error, time.time(), job))
            self.event(db, row['study'], job, state, {'receipt': receipt, 'error': error})

    def set_reason(self, job: int, reason: str) -> None:
        with self.connect(True) as db:
            db.execute('UPDATE jobs SET reason=? WHERE id=?', (reason[:800], job))

    def defer(self, job: int, reason: str) -> None:
        with self.connect(True) as db:
            row = db.execute('SELECT study,state FROM jobs WHERE id=?', (job,)).fetchone()
            if not row or row['state'] not in ACTIVE:
                raise EvoError('job is no longer active')
            db.execute("UPDATE jobs SET state='queued',reason=?,started=NULL,workspace_slot=NULL WHERE id=?",
                       (reason[:800], job))
            self.event(db, row['study'], job, 'deferred', {'reason': reason[:800]})

    def control(self, study: int, state: str) -> None:
        if state not in ('ready', 'paused', 'cancelled'):
            raise EvoError('invalid study control')
        self.study(study)
        with self.connect(True) as db:
            db.execute('UPDATE studies SET state=? WHERE id=?', (state, study))
            if state == 'cancelled':
                db.execute("UPDATE jobs SET state='cancelled',ended=?,reason='study cancelled before dispatch' WHERE study=? AND state='queued'", (time.time(), study))
            self.event(db, study, None, state, {})

    def reconcile_not_invoked(self, study: int, job: int, evidence: str) -> dict:
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 800:
            raise EvoError('reconciliation evidence must be 1..800 characters')
        with self.connect(True) as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND study=?', (job, study)).fetchone()
            if not row:
                raise EvoError('job does not belong to the selected study')
            if row['state'] != 'uncertain' and not (row['state'] == 'failed' and row['usage'] is None
                                                     and not row['usage_complete']):
                raise EvoError('only an uncertain or unsettled failed job can be reconciled as not invoked')
            if row['receipt'] is not None:
                raise EvoError('job already has a final receipt')
            db.execute("UPDATE jobs SET state='failed',reason='confirmed not invoked',usage=0,usage_complete=1,ended=? WHERE id=?",
                       (time.time(), job))
            self.event(db, study, job, 'reconciled_not_invoked',
                       {'evidence': evidence.strip(), 'preserved_error': row['error']})
            return dict(row)

    def retry_not_invoked(self, study: int, job: int, evidence: str, *, identity: str, plan: dict) -> int:
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 800:
            raise EvoError('retry evidence must be 1..800 characters')
        with self.connect(True) as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND study=?', (job, study)).fetchone()
            if not row:
                raise EvoError('job does not belong to the selected study')
            reconciled = db.execute("SELECT 1 FROM events WHERE job=? AND kind='reconciled_not_invoked'", (job,)).fetchone()
            if row['state'] != 'failed' or row['usage'] != 0 or not row['usage_complete'] or not reconciled:
                raise EvoError('retry requires a failed job explicitly reconciled as not invoked')
            attempt = row['attempt_seq'] + 1
            db.execute("UPDATE jobs SET state='queued',identity=?,plan=?,reason='explicit retry after confirmed non-invocation',"
                       "started=NULL,ended=NULL,receipt=NULL,error=NULL,reused_from=NULL,workspace_slot=NULL,"
                       "usage=NULL,usage_complete=0,attempt_seq=? WHERE id=?",
                       (identity, canonical(plan), attempt, job))
            self.event(db, study, job, 'retry_queued', {'attempt': attempt, 'prior_attempt': row['attempt_seq'],
                       'prior_execution_identity': row['identity'], 'execution_identity': identity,
                       'evidence': evidence.strip()})
            return attempt

    def require_retryable_not_invoked(self, study: int, job: int) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND study=?', (job, study)).fetchone()
            reconciled = db.execute("SELECT 1 FROM events WHERE job=? AND kind='reconciled_not_invoked'", (job,)).fetchone()
            if not row or row['state'] != 'failed' or row['usage'] != 0 or not row['usage_complete'] or not reconciled:
                raise EvoError('retry requires a failed job explicitly reconciled as not invoked')
            return dict(row)

    def trace(self, study: int, job: int | None = None, offset: int = 0, limit: int = 50,
              kind: str | None = None) -> list[dict]:
        positive(limit, 'trace limit', 500)
        if type(offset) is not int or offset < 0:
            raise EvoError('offset must be nonnegative')
        with self.connect() as db:
            sql = 'SELECT * FROM events WHERE study=?'
            args: list[Any] = [study]
            if job is not None:
                sql += ' AND job=?'
                args.append(job)
            if kind is not None:
                sql += ' AND kind=?'
                args.append(kind)
            rows = db.execute(sql + ' ORDER BY seq LIMIT ? OFFSET ?', [*args, limit, offset]).fetchall()
            return [{**dict(row), 'payload': json.loads(row['payload'])} for row in rows]

    def trace_summary(self, study: int, job: int | None = None, kind: str | None = None) -> dict:
        with self.connect() as db:
            sql, args = 'SELECT kind,COUNT(*) AS count FROM events WHERE study=?', [study]
            if job is not None:
                sql += ' AND job=?'
                args.append(job)
            if kind is not None:
                sql += ' AND kind=?'
                args.append(kind)
            rows = db.execute(sql + ' GROUP BY kind ORDER BY kind', args).fetchall()
            counts = {row['kind']: row['count'] for row in rows}
            latest_sql, latest_args = 'SELECT COALESCE(MAX(seq),0) FROM events WHERE study=?', [study]
            if job is not None:
                latest_sql += ' AND job=?'
                latest_args.append(job)
            return {'event_counts': counts, 'total': sum(counts.values()),
                    'latest_seq': db.execute(latest_sql, latest_args).fetchone()[0]}

    def lifecycle(self, job: int) -> dict[str, float | None]:
        with self.connect() as db:
            row = db.execute('SELECT j.started,j.ended,s.created FROM jobs j JOIN studies s ON s.id=j.study WHERE j.id=?',
                             (job,)).fetchone()
            if not row:
                raise EvoError('unknown job')
            times = {event['kind']: event['value'] for event in db.execute(
                'SELECT kind,MIN(time) AS value FROM events WHERE job=? GROUP BY kind', (job,)).fetchall()}
            claimed, running, verifying = times.get('claimed'), times.get('running'), times.get('verifying')
            return {
                'timing.queue_seconds': max(0.0, claimed - row['created']) if claimed is not None else None,
                'timing.prepare_seconds': max(0.0, running - claimed) if running is not None and claimed is not None else None,
                'timing.verify_seconds': max(0.0, row['ended'] - verifying) if row['ended'] is not None and verifying is not None else None,
            }

    def status(self, study: int | None = None, *, offset: int = 0, limit: int = 100) -> dict:
        if type(offset) is not int or offset < 0:
            raise EvoError('status offset must be nonnegative')
        positive(limit, 'status limit', 500)
        jobs = self.jobs(study)
        all_jobs = self.jobs()
        config = self.config()
        held = [job for job in all_jobs if job['state'] in RESOURCE_HELD]
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job['state']] = counts.get(job['state'], 0) + 1
        return {'schema': 'agentbase-evo-status/v1', 'study': f's{study}' if study else None,
                'counts': counts, 'total_jobs': len(jobs), 'tokens_observed': sum(j['usage'] or 0 for j in jobs),
                'tokens_reserved': sum(j['token_reservation'] for j in jobs if j['state'] in RESOURCE_HELD),
                'usage_unsettled': sum(j['model_slots'] > 0 and not j['usage_complete'] and j['state'] not in ('queued', *ACTIVE) for j in jobs),
                'resources': {'active_jobs': len(held), 'job_capacity': config['concurrency'],
                              'active_slots': len({j['workspace_slot'] for j in held if j['workspace_slot'] is not None}),
                              'model_slots_used': sum(j['model_slots'] for j in held),
                              'model_slot_capacity': config['model_capacity'],
                              'disk_reserved_bytes': sum(j['disk_reservation'] for j in held),
                              'reused_jobs': sum(j.get('reused_from') is not None for j in jobs)},
                'jobs': [{'job': f'j{j["id"]}', 'study': f's{j["study"]}', 'item': j['plan']['item'],
                          'combination': j['plan']['combination'], 'state': j['state'], 'reason': j['reason'],
                          'error': j['error'], 'receipt': j['receipt'], 'reused_from': f'j{j["reused_from"]}' if j.get('reused_from') else None,
                          'usage': j['usage'], 'usage_complete': bool(j['usage_complete']),
                          'workspace_slot': j['workspace_slot']} for j in jobs[offset:offset + limit]],
                'offset': offset, 'limit': limit, 'next_offset': offset + limit if offset + limit < len(jobs) else None,
                'truncated': offset + limit < len(jobs)}
