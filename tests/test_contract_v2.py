"""Boundary fixtures only; these are not real model-quality evidence."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from reprolens.app import CHECKLIST, create_app
from reprolens.evidence import make_source
from reprolens.model import ModelFailure, ModelSettings, call_model

SETTINGS = ModelSettings('http://127.0.0.1:9999/v1', 'fixture-model', constrained_json=True)


def runner_for(selection):
    envelope = {'model': 'fixture-model', 'choices': [{'finish_reason': 'stop',
                'message': {'content': json.dumps(selection)}}], 'usage': {'total_tokens': 20}}
    async def runner(settings, sources):
        return await call_model(SETTINGS, sources, httpx.MockTransport(lambda request: httpx.Response(200, json=envelope)))
    return runner, envelope


def session(selection):
    runner, _ = runner_for(selection)
    return TestClient(create_app(Path(__file__).resolve().parents[1] / 'runtime/tests' / f'{uuid4()}.sqlite3', model_runner=runner))


def analyze(client, description='A result was displayed.'):
    case = client.post('/api/cases', json={'title':'Contract fixture', 'description':description}).json()
    return client.post(f"/api/cases/{case['id']}/analyze", json={'revision':case['revision'],'mode':'ai'}).json()


def review(case):
    return {'revision':case['revision'], 'decisions':{c['id']:'accept' for c in case['analysis']['claims']},
            'checklist':{k:True for k in CHECKLIST}}


def test_empty_selection_is_persisted_supplement_state_not_ready_or_connection_error():
    selection = {'selected_lines':[], 'questions':[{'field':'observed','text':'What software result did you observe?'}]}
    _, envelope = runner_for(selection)
    with session(selection) as client:
        case = analyze(client, 'Please write a welcome greeting.')
        a = case['analysis']
        assert a['status'] == 'needs_evidence'
        assert a['error'] == 'no_relevant_evidence'
        assert a['contract'] == 'source_selection_v3'
        assert a['raw_selection'] == selection and a['raw_response'] == envelope
        assert a['claims'] == [] and a['questions'][0]['origin'] == 'model'
        assert client.get(f"/api/cases/{case['id']}").json() == case
        assert client.post(f"/api/cases/{case['id']}/review", json=review(case)).status_code == 409
        assert client.get(f"/api/cases/{case['id']}/report.md").status_code == 409
        added = client.post(f"/api/cases/{case['id']}/sources", json={'revision':case['revision'],'name':'observation','text':'The app showed Error 12.'})
        assert added.status_code == 200 and added.json()['analysis'] is None
        assert client.post(f"/api/cases/{case['id']}/review", json=review(case)).status_code == 409


@pytest.mark.parametrize('count', [5, 12])
def test_multiple_steps_and_observations_within_bound_are_copied(count):
    lines = [f'Action or result {i}' for i in range(1, count+1)]
    selection = {'selected_lines':[{'ref':f's0:{i}', 'category':'steps' if i < count else 'observed'} for i in range(1,count+1)],'questions':[]}
    runner, _ = runner_for(selection)
    extraction, meta = asyncio.run(runner(SETTINGS, [make_source('s0','notes','note','\n'.join(lines))]))
    assert [c.text for c in extraction.claims] == lines
    assert [c.evidence[0].start_line for c in extraction.claims] == list(range(1,count+1))
    assert meta['raw_selection'] == selection


@pytest.mark.parametrize('refs,reason', [([f's0:{i}' for i in range(1,14)],'invalid_response'), (['s0:99'],'unknown_reference'), (['s0:1','s0:1'],'duplicate_reference')])
def test_bound_unknown_and_duplicate_refs_rejected(refs, reason):
    runner, _ = runner_for({'selected_lines':[{'ref':r,'category':'observed'} for r in refs],'questions':[]})
    with pytest.raises(ModelFailure, match=reason):
        asyncio.run(runner(SETTINGS,[make_source('s0','notes','note','\n'.join(f'line {i}' for i in range(1,14)))]))


def test_no_observed_still_blocks_confirmation():
    with session({'selected_lines':[{'ref':'s0:1','category':'environment'}], 'questions':[]}) as client:
        case = analyze(client,'Python 3.12 on Windows 11.')
        assert case['analysis']['status'] == 'ready'
        assert client.post(f"/api/cases/{case['id']}/review",json=review(case)).status_code == 422
        assert client.get(f"/api/cases/{case['id']}/report.md").status_code == 409


def test_unselected_supplied_text_is_not_declared_missing_by_program():
    # Deliberately incomplete selection: do not turn its omission into a question
    # claiming the original input lacked a version. Review gaps concern inclusion.
    with session({'selected_lines':[{'ref':'s0:2','category':'observed'}], 'questions':[]}) as client:
        case = analyze(client,'Python 3.12 on Windows 11.\nThe program displayed Error 12.')
        assert case['analysis']['questions'] == []
        confirmed = client.post(f"/api/cases/{case['id']}/review",json=review(case))
        assert confirmed.status_code == 200
        assert 'environment' in confirmed.json()['review']['missing_fields']
        report = client.get(f"/api/cases/{case['id']}/report.md").text
        assert 'Check the original sources first' in report
        assert 'source_selection_v3' in report
