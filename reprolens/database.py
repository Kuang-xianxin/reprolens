"""Non-destructive SQLite maintenance. Restore always targets a new path."""
import argparse
import json
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from .store import Store


def inspect(path):
    path=Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        foreign=conn.execute('PRAGMA foreign_key_check').fetchall()
        if integrity!='ok' or foreign:
            raise RuntimeError('Database integrity failed')
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'cases' not in tables:
            raise RuntimeError('Not a ReproLens database')
        for (raw,) in conn.execute('SELECT document FROM cases'):
            Store._decode(raw)
        if 'revisions' in tables:
            for (raw,) in conn.execute('SELECT document FROM revisions'):
                Store._decode(raw)
        if 'jobs' in tables:
            for raw,digest in conn.execute('SELECT checkpoint,checkpoint_hash FROM jobs WHERE checkpoint IS NOT NULL'):
                if hashlib.sha256(raw.encode()).hexdigest()!=digest:
                    raise RuntimeError('Stored checkpoint integrity failed')
        if 'case_summaries' in tables:
            mismatches=conn.execute("SELECT count(*) FROM cases c LEFT JOIN case_summaries s ON s.id=c.id WHERE s.id IS NULL OR s.revision<>c.revision OR s.title<>json_extract(c.document,'$.title') OR s.confirmed<>(json_extract(c.document,'$.review') IS NOT NULL)").fetchone()[0]
            if mismatches:raise RuntimeError('Stored summary integrity failed')
        return {'integrity':integrity,'schema_version':conn.execute('PRAGMA user_version').fetchone()[0],
                'cases':conn.execute('SELECT count(*) FROM cases').fetchone()[0],
                'revisions':conn.execute('SELECT count(*) FROM revisions').fetchone()[0] if 'revisions' in tables else 0,
                'operations':conn.execute('SELECT count(*) FROM operations').fetchone()[0] if 'operations' in tables else 0,
                'create_requests':conn.execute('SELECT count(*) FROM create_requests').fetchone()[0] if 'create_requests' in tables else 0,
                'jobs':conn.execute('SELECT count(*) FROM jobs').fetchone()[0] if 'jobs' in tables else 0,
                'summaries':conn.execute('SELECT count(*) FROM case_summaries').fetchone()[0] if 'case_summaries' in tables else 0}


def restore(source,destination):
    source=Path(source).resolve(strict=True)
    destination=Path(destination).resolve()
    before=inspect(source)
    if before['schema_version']>2:
        raise RuntimeError('Backup schema is newer than this application')
    if source==destination or destination.exists():
        raise FileExistsError('Restore requires a new destination; existing data will not be overwritten')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb'):
        pass
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
    after=inspect(destination)
    if before!=after:
        raise RuntimeError('Restore counts differ; destination retained for inspection')
    return after


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','migrate','backup','restore'])
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.action in {'backup','restore'} and args.output is None:
        parser.error('--output is required')
    if args.action=='migrate':
        Store(args.db)
        result=inspect(args.db)
    elif args.action=='backup':
        inspect(args.db)
        Store(args.db).backup(args.output)
        result=inspect(args.output)
    elif args.action=='restore':
        result=restore(args.db,args.output)
    else:
        result=inspect(args.db)
    print(json.dumps(result))

if __name__=='__main__':
    main()
