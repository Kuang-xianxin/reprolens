import json
import hashlib
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

MAX_CASES=10000
MAX_REVISIONS=1000
MAX_DATABASE_BYTES=512*1024*1024


class Capacity(Exception):
    pass


class Corrupt(Exception):
    pass


class Conflict(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=1)) as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version > 2:
                raise RuntimeError('Database schema is newer than this application')
            exists = conn.execute("SELECT name FROM sqlite_master WHERE name='cases'").fetchone()
            if version < 2 and exists:
                backup = self.path + f'.pre-v{version+1}-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.bak'
                with closing(sqlite3.connect(backup)) as target:
                    conn.backup(target)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=FULL')
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute("CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>0), document TEXT NOT NULL CHECK(json_valid(document)))")
                conn.execute('CREATE TABLE IF NOT EXISTS revisions (case_id TEXT NOT NULL REFERENCES cases(id), revision INTEGER NOT NULL, action TEXT NOT NULL, saved_at TEXT NOT NULL, document TEXT NOT NULL CHECK(json_valid(document)), PRIMARY KEY(case_id,revision))')
                conn.execute('CREATE TABLE IF NOT EXISTS create_requests (request_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), fingerprint TEXT NOT NULL)')
                conn.execute("CREATE INDEX IF NOT EXISTS cases_updated_idx ON cases(json_extract(document,'$.updated_at') DESC)")
                conn.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), source_revision INTEGER NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, error TEXT)')
                conn.execute('CREATE INDEX IF NOT EXISTS operations_case_idx ON operations(case_id,started_at DESC)')
                conn.execute("INSERT OR IGNORE INTO revisions SELECT id,revision,'legacy_import',?,document FROM cases", (now(),))
                conn.execute("CREATE TABLE IF NOT EXISTS case_summaries (id TEXT PRIMARY KEY REFERENCES cases(id), title TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, confirmed INTEGER NOT NULL, analysis_status TEXT NOT NULL)")
                conn.execute('CREATE INDEX IF NOT EXISTS summary_updated_idx ON case_summaries(updated_at DESC,id)')
                conn.execute('CREATE INDEX IF NOT EXISTS summary_status_idx ON case_summaries(confirmed,updated_at DESC,id)')
                conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(id),source_revision INTEGER NOT NULL,request_id TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,language TEXT NOT NULL CHECK(language IN ('auto','zh','en')),status TEXT NOT NULL CHECK(status IN ('queued','running','ready','needs_evidence','failed','cancelled','superseded')),phase TEXT NOT NULL CHECK(phase IN ('pending','extracted','finished')),attempts INTEGER NOT NULL CHECK(attempts BETWEEN 0 AND 2),created_at REAL NOT NULL,updated_at REAL NOT NULL,error TEXT,result_revision INTEGER,checkpoint TEXT CHECK(checkpoint IS NULL OR json_valid(checkpoint)),checkpoint_hash TEXT)")
                conn.execute('CREATE INDEX IF NOT EXISTS jobs_queue_idx ON jobs(status,created_at)')
                conn.execute('CREATE INDEX IF NOT EXISTS jobs_case_idx ON jobs(case_id,created_at DESC)')
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_case_idx ON jobs(case_id) WHERE status IN ('queued','running')")
                if version < 2:
                    for (raw,) in conn.execute('SELECT document FROM cases'):
                        self._summary(conn,self._decode(raw))
                conn.execute('PRAGMA user_version=2')

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=1)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA synchronous=FULL')
            deadline=time.monotonic()+.5
            conn.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
            with conn:
                yield conn

    def get(self, case_id):
        with self.connection() as conn:
            row = conn.execute("SELECT document,revision FROM cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            raise KeyError(case_id)
        doc=self._decode(row[0])
        if doc['revision']!=row[1]:
            raise Corrupt('Stored revision mismatch')
        return doc

    @staticmethod
    def _decode(raw):
        try:
            doc=json.loads(raw)
            for source in doc['sources']:
                if hashlib.sha256(source['text'].encode('utf-8')).hexdigest()!=source['sha256']:
                    raise Corrupt('Source integrity check failed')
            return doc
        except (KeyError,TypeError,ValueError):
            raise Corrupt('Stored document is invalid') from None

    def list(self, query='', status='all', offset=0, limit=100):
        sql="SELECT id,title,revision,created_at,updated_at,confirmed,analysis_status FROM case_summaries"
        clauses=[];params=[]
        if query:
            clauses.append('instr(lower(title),lower(?))>0');params.append(query)
        if status!='all':
            clauses.append('confirmed=?');params.append(int(status=='confirmed'))
        if clauses:sql+=' WHERE '+' AND '.join(clauses)
        sql+=' ORDER BY updated_at DESC,id LIMIT ? OFFSET ?'
        with self.connection() as conn:
            rows = conn.execute(sql,(*params,limit,offset)).fetchall()
        return [dict(zip(('id','title','revision','created_at','updated_at','confirmed','analysis_status'),r)) for r in rows]

    @staticmethod
    def _summary(conn,doc):
        conn.execute('INSERT OR REPLACE INTO case_summaries VALUES(?,?,?,?,?,?,?)', (doc['id'],doc['title'],doc['revision'],doc['created_at'],doc.get('updated_at',doc['created_at']),int(bool(doc.get('review'))),(doc.get('analysis') or {}).get('status','none')))

    @staticmethod
    def summary(doc):
        return {"id": doc["id"], "title": doc["title"], "revision": doc["revision"],
                "created_at": doc["created_at"], "confirmed": bool(doc.get("review")),
                "updated_at": doc.get("updated_at", doc["created_at"]),
                "analysis_status": (doc.get("analysis") or {}).get("status", "none")}

    def create(self, doc, request_id=None):
        fingerprint = hashlib.sha256(json.dumps([doc['title'],doc['sources']], sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if request_id:
                previous = conn.execute('SELECT case_id,fingerprint FROM create_requests WHERE request_id=?',(request_id,)).fetchone()
                if previous:
                    if previous[1] != fingerprint:
                        raise Conflict('Request already used with different content / 此请求已用于其他内容')
                    return json.loads(conn.execute('SELECT document FROM cases WHERE id=?',(previous[0],)).fetchone()[0])
            self._capacity(conn)
            if conn.execute('SELECT count(*) FROM cases').fetchone()[0]>=MAX_CASES:
                raise Capacity('Case capacity reached; back up and use a new database / 问题数量已达上限，请备份后使用新数据库')
            conn.execute("INSERT INTO cases VALUES (?, ?, ?)", (doc["id"], doc["revision"], json.dumps(doc, ensure_ascii=False)))
            self._snapshot(conn,doc,'created')
            self._summary(conn,doc)
            if request_id:
                conn.execute('INSERT INTO create_requests VALUES (?,?,?)',(request_id,doc['id'],fingerprint))
        return doc

    def save(self, doc, expected_revision, action='updated'):
        doc["revision"] = expected_revision + 1
        doc["updated_at"] = now()
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._capacity(conn,doc['id'])
            cursor = conn.execute("UPDATE cases SET revision=?, document=? WHERE id=? AND revision=?",
                                  (doc["revision"], json.dumps(doc, ensure_ascii=False), doc["id"], expected_revision))
            if cursor.rowcount != 1:
                raise Conflict("Case changed; reload before continuing / 案例已更新，请重新载入")
            self._snapshot(conn,doc,action)
            self._summary(conn,doc)
        return doc

    def _capacity(self,conn,case_id=None):
        size=sum(p.stat().st_size for p in [Path(self.path),Path(self.path+'-wal')] if p.exists())
        if size>=MAX_DATABASE_BYTES:
            raise Capacity('Database capacity reached; back up and use a new database / 数据库容量已达上限，请备份后使用新数据库')
        if case_id and conn.execute('SELECT count(*) FROM revisions WHERE case_id=?',(case_id,)).fetchone()[0]>=MAX_REVISIONS:
            raise Capacity('Version capacity reached; export and start a new case / 版本数量已达上限，请导出后新建问题')

    def start_operation(self,operation_id,case_id,revision):
        with self.connection() as conn:
            self._capacity(conn,case_id)
            if conn.execute('SELECT count(*) FROM operations WHERE case_id=?',(case_id,)).fetchone()[0]>=MAX_REVISIONS:
                raise Capacity('Operation history capacity reached / 整理记录数量已达上限')
            conn.execute('INSERT INTO operations VALUES (?,?,?,?,?,NULL,NULL)',(operation_id,case_id,revision,'running',now()))

    def recover_operations(self):
        with self.connection() as conn:
            conn.execute("UPDATE operations SET status='interrupted',finished_at=?,error='service_restarted' WHERE status='running'",(now(),))

    def finish_operation(self,operation_id,status,error=None):
        with self.connection() as conn:
            conn.execute('UPDATE operations SET status=?,finished_at=?,error=? WHERE id=?',(status,now(),error,operation_id))

    def operations(self,case_id):
        with self.connection() as conn:
            rows=conn.execute('SELECT id,source_revision,status,started_at,finished_at,error FROM operations WHERE case_id=? ORDER BY started_at DESC LIMIT 20',(case_id,)).fetchall()
        return [dict(zip(('id','source_revision','status','started_at','finished_at','error'),r)) for r in rows]

    @staticmethod
    def _snapshot(conn,doc,action):
        conn.execute('INSERT INTO revisions VALUES (?,?,?,?,?)',(doc['id'],doc['revision'],action,now(),json.dumps(doc,ensure_ascii=False)))

    def history(self,case_id):
        with self.connection() as conn:
            rows = conn.execute('SELECT revision,action,saved_at FROM revisions WHERE case_id=? ORDER BY revision DESC',(case_id,)).fetchall()
        return [dict(revision=r[0],action=r[1],saved_at=r[2]) for r in rows]

    def revision(self,case_id):
        with self.connection() as conn:
            row=conn.execute('SELECT revision FROM cases WHERE id=?',(case_id,)).fetchone()
        if not row: raise KeyError(case_id)
        return row[0]

    def version(self,case_id,revision):
        with self.connection() as conn:
            row = conn.execute('SELECT document FROM revisions WHERE case_id=? AND revision=?',(case_id,revision)).fetchone()
        if not row:
            raise KeyError(revision)
        return self._decode(row[0])

    def ready(self):
        with self.connection() as conn:
            conn.execute('SELECT revision FROM cases LIMIT 1').fetchall()
            return conn.execute('PRAGMA user_version').fetchone()[0]

    def backup(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb'):
            pass
        with self.connection() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            result = target.execute('PRAGMA integrity_check').fetchone()[0]
            if result != 'ok':
                raise RuntimeError('Backup integrity check failed; retained for inspection')
        return str(destination)

