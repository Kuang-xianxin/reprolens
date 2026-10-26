"""Durable bounded queue: one owned worker; every final state and report commit is atomic."""
import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .issue import fields_from_analysis
from .model import ModelFailure
from .store import Capacity, Conflict, Corrupt, now
from .workflow import run_workflow, source_key

ACTIVE = ('queued', 'running')
MAX_QUEUE = 4


async def db_call(function, *args):
    # Cancelling to_thread alone does not stop the underlying SQLite operation.
    # Drain that bounded operation before releasing a task slot or service lease.
    task=asyncio.create_task(asyncio.to_thread(function,*args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task,return_exceptions=True)
        raise


class Job(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    case_id: str
    source_revision: int = Field(ge=1)
    status: Literal['queued', 'running', 'ready', 'needs_evidence', 'failed', 'cancelled', 'superseded']
    phase: Literal['pending', 'extracted', 'finished']
    attempts: int = Field(ge=0, le=2)
    created_at: float
    updated_at: float
    error: str | None = None
    result_revision: int | None = None


class QueueFull(Exception):
    pass


class InstanceLease:
    """OS lock survives neither crash nor exit. Its retained file is not a stale lock."""
    def __init__(self, path):
        self.path = Path(str(path) + '.worker.lock')
        self.file = None

    def acquire(self):
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            import os
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file = None
            raise RuntimeError('This database already has an active service') from None

    def release(self):
        if self.file:
            self.file.close(); self.file = None


class JobStore:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def public(row):
        return Job.model_validate({k: row[k] for k in Job.model_fields}).model_dump()

    def get(self, job_id):
        with self.store.connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return dict(row)

    def list(self, case_id):
        with self.store.connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            rows = conn.execute('SELECT * FROM jobs WHERE case_id=? ORDER BY created_at DESC LIMIT 20', (case_id,)).fetchall()
        return [self.public(row) for row in rows]

    def replay(self,case_id,revision,language,request_id):
        with self.store.connection() as conn:
            conn.row_factory=__import__('sqlite3').Row
            row=conn.execute('SELECT * FROM jobs WHERE request_id=?',(request_id,)).fetchone()
        if row is None:return None
        if (row['case_id'],row['source_revision'],row['language'])!=(case_id,revision,language):
            raise Conflict('Request already used with different content / 请求标识已用于其他材料')
        return self.public(row)

    def submit(self, case, settings, language, request_id):
        fingerprint = source_key(case, settings, language)
        with self.store.connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            conn.execute('BEGIN IMMEDIATE')
            prior = conn.execute('SELECT * FROM jobs WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise Conflict('Request already used with different content / 请求标识已用于其他材料')
                return self.public(prior)
            revision = conn.execute('SELECT revision FROM cases WHERE id=?', (case['id'],)).fetchone()[0]
            if revision != case['revision']:
                raise Conflict('Case changed; reload before organizing / 材料已更新，请重新载入')
            active = conn.execute("SELECT * FROM jobs WHERE case_id=? AND status IN ('queued','running')", (case['id'],)).fetchone()
            if active:
                if active['fingerprint'] != fingerprint:
                    raise Conflict('A different proposal is in progress; cancel it first / 请先取消进行中的整理')
                return self.public(active)
            if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= MAX_QUEUE:
                raise QueueFull()
            self.store._capacity(conn, case['id'])
            if conn.execute('SELECT count(*) FROM jobs WHERE case_id=?', (case['id'],)).fetchone()[0] >= 1000:
                raise Capacity('Task history capacity reached / 整理记录已达上限')
            job_id, ts = str(uuid4()), time.time()
            conn.execute("INSERT INTO jobs(id,case_id,source_revision,request_id,fingerprint,language,status,phase,attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,'queued','pending',0,?,?)",
                         (job_id,case['id'],case['revision'],request_id,fingerprint,language,ts,ts))
            return self.public(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def recover(self):
        with self.store.connection() as conn:
            conn.execute("UPDATE jobs SET status=CASE WHEN attempts<2 THEN 'queued' ELSE 'failed' END,error=CASE WHEN attempts<2 THEN NULL ELSE 'restart_limit' END,updated_at=? WHERE status='running'", (time.time(),))

    def take(self):
        with self.store.connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE jobs SET status='failed',phase='finished',error='queue_expired',updated_at=? WHERE status='queued' AND created_at<?", (time.time(),time.time()-600))
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return None
            conn.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (time.time(),row['id']))
            return dict(conn.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())

    def heartbeat(self, job_id):
        with self.store.connection() as conn:
            conn.execute("UPDATE jobs SET updated_at=? WHERE id=? AND status='running'", (time.time(),job_id))

    def checkpoint(self, job_id, state):
        raw = json.dumps(state,ensure_ascii=False)
        if len(raw.encode()) > 256_000:
            raise ModelFailure('checkpoint_too_large')
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.store.connection() as conn:
            cur = conn.execute("UPDATE jobs SET checkpoint=?,checkpoint_hash=?,phase='extracted',updated_at=? WHERE id=? AND status='running'", (raw,digest,time.time(),job_id))
            if cur.rowcount != 1:
                raise ModelFailure('cancelled')

    def finish(self, job_id, status, error=None, analysis=None):
        if status not in ('ready','needs_evidence','failed','cancelled','superseded'):
            raise ValueError('Invalid terminal state')
        with self.store.connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row['status'] not in ACTIVE:
                return self.public(row)
            result_revision = None
            if analysis is not None:
                current = conn.execute('SELECT document,revision FROM cases WHERE id=?', (row['case_id'],)).fetchone()
                if current['revision'] != row['source_revision']:
                    status, error = 'superseded', 'revision_conflict'
                else:
                    self.store._capacity(conn,row['case_id'])
                    doc = self.store._decode(current['document'])
                    doc['analysis'], doc['last_attempt'], doc['review'] = analysis, analysis, None
                    if status == 'ready':
                        doc['draft'] = dict(fields=fields_from_analysis(analysis),origin='ai',saved_at=now())
                    doc['revision'] += 1
                    doc['updated_at'] = now()
                    result_revision = doc['revision']
                    conn.execute('UPDATE cases SET document=?,revision=? WHERE id=?', (json.dumps(doc,ensure_ascii=False),doc['revision'],doc['id']))
                    self.store._snapshot(conn,doc,'organized_ai' if status=='ready' else 'analysis_needs_evidence')
                    self.store._summary(conn,doc)
            conn.execute("UPDATE jobs SET status=?,phase='finished',error=?,result_revision=?,updated_at=? WHERE id=?", (status,error,result_revision,time.time(),job_id))
            return self.public(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


class JobWorker:
    def __init__(self, store, gateway):
        self.store, self.jobs, self.gateway = store, JobStore(store), gateway
        self.lease = InstanceLease(store.path)
        self.task = self.active = None
        self.active_id = None
        self.wake = asyncio.Event()
        self.stopping = False
        self.errors = 0
        self.needs_recovery = False
        self.last_tick = time.monotonic()

    async def start(self):
        self.lease.acquire()
        try:
            await db_call(self.jobs.recover)
            self.task = asyncio.create_task(self.loop(), name='reprolens-worker')
        except BaseException:
            self.lease.release()
            raise

    async def stop(self):
        self.stopping = True
        if self.active:
            self.active.cancel()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
        self.lease.release()

    async def cancel(self, job_id):
        result = await db_call(self.jobs.finish,job_id,'cancelled','cancelled')
        if self.active_id == job_id and self.active:
            self.active.cancel()
            await asyncio.gather(self.active,return_exceptions=True)
        self.wake.set()
        return result

    async def run(self, row):
        case = await db_call(self.store.get,row['case_id'])
        if case['revision'] != row['source_revision']:
            return await db_call(self.jobs.finish,row['id'],'superseded','revision_conflict')
        if source_key(case,self.gateway.settings,row['language']) != row['fingerprint']:
            raise ModelFailure('configuration_changed')
        checkpoint = None
        if row['checkpoint']:
            if hashlib.sha256(row['checkpoint'].encode()).hexdigest() != row['checkpoint_hash']:
                raise ModelFailure('checkpoint_mismatch')
            checkpoint = json.loads(row['checkpoint'])
        async def save(value):
            await db_call(self.jobs.checkpoint,row['id'],value)
        analysis = await run_workflow(self.gateway,case,row['language'],checkpoint,save)
        return await db_call(self.jobs.finish,row['id'],analysis['status'],analysis.get('error'),analysis)

    async def loop(self):
        while not self.stopping:
            row = None
            try:
                self.last_tick = time.monotonic()
                if self.needs_recovery:
                    await db_call(self.jobs.recover)
                    self.needs_recovery=False
                row = await db_call(self.jobs.take)
                if row is None:
                    self.wake.clear()
                    try: await asyncio.wait_for(self.wake.wait(),.5)
                    except TimeoutError: pass
                    continue
                self.active_id = row['id']
                self.active = asyncio.create_task(self.run(row),name='reprolens-proposal')
                while not self.active.done():
                    await asyncio.wait([self.active],timeout=2)
                    self.last_tick = time.monotonic()
                    if not self.active.done():
                        await db_call(self.jobs.heartbeat,row['id'])
                await self.active
            except asyncio.CancelledError:
                if self.stopping:
                    if self.active:
                        self.active.cancel()
                        await asyncio.gather(self.active,return_exceptions=True)
                    break
                if row:
                    await db_call(self.jobs.finish,row['id'],'cancelled','cancelled')
            except Exception as exc:
                self.errors += 1
                if self.active and not self.active.done():
                    self.active.cancel()
                    await asyncio.gather(self.active,return_exceptions=True)
                if row:
                    try:
                        await db_call(self.jobs.finish,row['id'],'failed',exc.code if isinstance(exc,ModelFailure) else 'processing_failed')
                    except Exception:
                        # Bounded DB retry on the next tick, rather than killing the worker.
                        await asyncio.sleep(1)
                        self.needs_recovery=True
                await asyncio.sleep(.1)
            finally:
                self.active = None
                self.active_id = None
