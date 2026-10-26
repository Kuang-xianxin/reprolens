"""Product transactions and recovery, retained on-disk fixtures; no bulk cleanup."""
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from reprolens.app import create_app
from reprolens.database import inspect,restore
from reprolens.model import ModelSettings
from reprolens.store import Store,Conflict

ROOT=Path(__file__).resolve().parents[1]
def path(): return ROOT/'runtime/tests'/('product-'+str(uuid4())+'.sqlite3')
def client(db=None): return TestClient(create_app(db or path(),settings=ModelSettings()))
def create(c): return c.post('/api/cases',json={'title':'CSV drops a row','description':'Last row missing','request_id':str(uuid4())}).json()
def draft(c,case,text='Only first record appeared'):
    r=c.put('/api/cases/'+case['id']+'/draft',json={'revision':case['revision'],'title':case['title'],'fields':{'environment':'Python 3.12','steps':'Create two rows\nExport CSV','observed':text,'expected':'Both rows'}})
    assert r.status_code==200,r.text
    return r.json()
def confirm(c,case):
    r=c.post('/api/cases/'+case['id']+'/confirm',json={'revision':case['revision'],'sources_reviewed':True,'privacy_reviewed':True})
    assert r.status_code==200,r.text
    return r.json()

def test_manual_issue_history_restore_restart_export():
    db=path()
    with client(db) as c:
        case=create(c); original=copy.deepcopy(case)
        case=draft(c,case); saved=case['revision']; case=confirm(c,case)
        export=c.get('/api/cases/'+case['id']+'/issue.md?lang=en&revision='+str(case['revision']))
        assert export.status_code==200 and '## Actual result' in export.text and 'Only first record' in export.text
        assert 'Original sources' not in export.text
        assert '## 原始材料' in c.get('/api/cases/'+case['id']+'/issue.md?lang=zh&sources=true').text
        oldrev=case['revision']; case=draft(c,case,'Nothing appeared')
        assert c.get('/api/cases/'+case['id']+'/issue.md').status_code==409
        assert c.get('/api/cases/'+case['id']+'/issue.md?revision='+str(oldrev)).status_code==409
        history=c.get('/api/cases/'+case['id']+'/history').json()
        assert len(history)==4
        assert c.get('/api/cases/'+case['id']+'/history/1').json()==original
        response=c.post('/api/cases/'+case['id']+'/restore',json={'revision':case['revision'],'target_revision':saved})
        assert response.status_code==200
        case=response.json()
        assert case['revision']==5 and case['review'] is None and case['draft']['fields']['observed']=='Only first record appeared'
        assert len(c.get('/api/cases/'+case['id']+'/history').json())==5
    with client(db) as reopened:
        assert reopened.get('/api/cases/'+case['id']).json()==case
        assert reopened.get('/api/ready').json()['schema_version']==2

def test_retry_create_and_concurrent_edits():
    with client() as c:
        payload={'title':'Duplicate request','description':'An error','request_id':str(uuid4())}
        first=c.post('/api/cases',json=payload).json()
        assert c.post('/api/cases',json=payload).json()==first
        assert c.post('/api/cases',json={**payload,'title':'Different'}).status_code==409
        updated=draft(c,first)
        r=c.put('/api/cases/'+first['id']+'/draft',json={'revision':1,'title':'stale','fields':{}})
        assert r.status_code==409
        assert c.get('/api/cases/'+first['id']).json()==updated
        assert len(c.get('/api/cases').json())==1

def test_failure_preserves_confirmed_work_and_addition_invalidates():
    with client() as c:
        case=confirm(c,draft(c,create(c))); previous=copy.deepcopy(case)
        case=c.post('/api/cases/'+case['id']+'/analyze',json={'revision':case['revision'],'mode':'ai'}).json()
        assert case['last_attempt']['error']=='not_configured'
        assert case['draft']==previous['draft'] and case['review']==previous['review']
        assert c.get('/api/cases/'+case['id']+'/issue.md').status_code==200
        case=c.post('/api/cases/'+case['id']+'/sources',json={'revision':case['revision'],'name':'reply','text':'Also happens on Linux'}).json()
        assert case['draft']==previous['draft'] and case['review'] is None
        assert c.get('/api/cases/'+case['id']+'/issue.md').status_code==409

def test_missing_actual_result_and_false_checks_are_rejected():
    with client() as c:
        case=draft(c,create(c),'')
        assert c.post('/api/cases/'+case['id']+'/confirm',json={'revision':case['revision'],'sources_reviewed':True,'privacy_reviewed':True}).status_code==422
        case=draft(c,case,'Actual error')
        assert c.post('/api/cases/'+case['id']+'/confirm',json={'revision':case['revision'],'sources_reviewed':False,'privacy_reviewed':True}).status_code==422

def test_rules_keep_original_selections_after_edit():
    with client() as c:
        case=create(c)
        case=c.post('/api/cases/'+case['id']+'/analyze',json={'revision':case['revision'],'mode':'rules'}).json()
        analysis=copy.deepcopy(case['analysis'])
        case=draft(c,case,'Reviewer wording')
        assert case['analysis']==analysis and case['draft']['origin']=='reviewer'
        assert c.get('/api/cases/'+case['id']+'/history/2').json()['analysis']==analysis

def test_legacy_migration_and_online_backup_restore():
    legacy=path();legacy.parent.mkdir(parents=True,exist_ok=True)
    document={'id':'legacy','revision':7,'title':'Preserved','created_at':'2026-10-20T00:00:00Z','sources':[],'analysis':{'raw_response':{'failed':'retained'}},'review':None}
    with sqlite3.connect(legacy) as conn:
        conn.execute('CREATE TABLE cases (id TEXT PRIMARY KEY,revision INTEGER NOT NULL,document TEXT NOT NULL)')
        conn.execute('INSERT INTO cases VALUES (?,?,?)',('legacy',7,json.dumps(document)))
    store=Store(legacy)
    assert store.get('legacy')==document and store.version('legacy',7)==document
    backups=list(legacy.parent.glob(legacy.name+'.pre-v1-*.bak'))
    assert len(backups)==1 and inspect(backups[0])['schema_version']==0
    backup=path();store.backup(backup)
    destination=path();assert restore(backup,destination)==inspect(legacy)
    assert Store(destination).get('legacy')==document
    with pytest.raises(FileExistsError): restore(backup,destination)
    with pytest.raises(FileExistsError): store.backup(backup)
    assert inspect(legacy)['cases']==1

def test_two_writers_only_one_revision_commits():
    with client() as c:
        case=create(c);store=c.app.state.store
        def write(title):
            candidate=copy.deepcopy(case);candidate['title']=title
            try: store.save(candidate,1,'parallel'); return True
            except Conflict: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(write,['one','two']))==[False,True]
        assert len(store.history(case['id']))==2

def test_search_limits_and_mime():
    with client() as c:
        a=create(c);b=confirm(c,draft(c,create(c)))
        assert len(c.get('/api/cases?status=confirmed').json())==1
        assert len(c.get('/api/cases?q=CSV&limit=1').json())==1
        assert c.get('/api/cases?q=nevermatched').json()==[]
        assert c.get('/api/cases?status=wrong').status_code==422
        assert 'text/css' in c.get('/static/workbench.css').headers['content-type']
        assert 'application/javascript' in c.get('/static/workbench.js').headers['content-type']
        assert c.get('/api/cases/'+b['id']+'/case.json').json()['review']['kind']=='issue'

def test_safe_environment_and_model_repr(monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('serve',ROOT/'scripts/serve.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setenv('OPENAI_API_KEY','fixture-secret-never-real')
    monkeypatch.setenv('ANTHROPIC_API_KEY','fixture-secret-never-real')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','fixture-secret-never-real')
    assert not any('KEY' in key for key in module.clean_environment())
    assert 'fixture-secret-never-real' not in repr(ModelSettings(api_key='fixture-secret-never-real'))
