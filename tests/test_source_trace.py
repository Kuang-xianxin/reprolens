import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from reprolens.app import create_app
from reprolens.issue import render_issue
from reprolens.model import ModelSettings
from reprolens.trace import source_index, trace_text

ROOT = Path(__file__).resolve().parents[1]


def test_shared_trace_contract_and_bounded_duplicates():
    fixture = json.loads((ROOT/'examples/source-trace.json').read_text(encoding='utf-8'))
    assert trace_text(fixture['text'], source_index(fixture['sources'])) == fixture['expected']
    index = source_index([{'text': 'x\n' * 6000}])
    result = trace_text('x\n' * 6000, index)
    assert result['matched'] == 6000 and result['omitted'] == 5920
    assert len(result['entries']) == 80 and len(index['x']['matches']) == 3


def test_export_uses_current_wording_and_only_referenced_lines():
    case = {'title': 'CSV import', 'sources': [{'name': 'log.txt', 'text': 'KeyError: amount\nPRIVATE UNRELATED NOTE\n<script>alert(1)</script>'}],
            'draft': {'fields': {'environment': '', 'steps': '', 'observed': 'KeyError: amount', 'expected': 'Import both rows'}}}
    plain = render_issue(case)
    assert '[^src-' not in plain and 'PRIVATE' not in plain
    linked = render_issue(case, include_evidence=True)
    assert '[^src-1-1]' in linked and 'PRIVATE' not in linked
    assert 'Import both rows [^' not in linked
    case['draft']['fields']['observed'] = 'KeyError: different'
    assert '[^src-' not in render_issue(case, include_evidence=True)
    case['draft']['fields']['observed'] = '<script>alert(1)</script>'
    escaped = render_issue(case, 'zh', include_evidence=True)
    assert '<script>' not in escaped and '&lt;script&gt;' in escaped and '引用定位' in escaped


def test_evidence_export_keeps_confirmation_revision_gate_and_js_mime():
    with TestClient(create_app(ROOT/'runtime/tests'/f'trace-{uuid4()}.sqlite3', settings=ModelSettings())) as client:
        case = client.post('/api/cases', json={'title':'Trace review', 'description':'File is empty\nUnshared detail'}).json()
        url = f"/api/cases/{case['id']}"
        case = client.put(url+'/draft', json={'revision':case['revision'],'title':case['title'],'fields':{'observed':'File is empty'}}).json()
        assert client.get(url+'/issue.md?evidence=true').status_code == 409
        case = client.post(url+'/confirm',json={'revision':case['revision'],'sources_reviewed':True,'privacy_reviewed':True}).json()
        exported = client.get(url+f"/issue.md?evidence=true&revision={case['revision']}")
        assert exported.status_code == 200 and '[^src-1-1]' in exported.text and 'Unshared detail' not in exported.text
        old_revision = case['revision']
        case = client.put(url+'/draft', json={'revision':case['revision'],'title':case['title'],'fields':{'observed':'File is not empty'}}).json()
        assert client.get(url+f'/issue.md?evidence=true&revision={old_revision}').status_code == 409
        static = client.get('/static/source-trace.js')
        assert static.status_code == 200 and static.headers['content-type'].startswith('application/javascript')
