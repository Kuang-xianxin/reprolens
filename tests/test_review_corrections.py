"""Review contracts with synthetic fixtures, never model-quality evidence."""
import copy
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from reprolens.app import CHECKLIST, create_app
from reprolens.model import ModelSettings

ROOT = Path(__file__).resolve().parents[1]


def session():
    return TestClient(create_app(ROOT / 'runtime/tests' / f'{uuid4()}.sqlite3', settings=ModelSettings()))


def ruled_case(client):
    case = client.post('/api/cases', json={
        'title': 'Review contract fixture',
        'description': 'Preview shows zero records.',
        'sources': [{'name': 'notes', 'text': 'Environment: Python 3.12\nSteps: preview the CSV\nExpected: one record'}],
    }).json()
    return client.post(f"/api/cases/{case['id']}/analyze", json={'revision': case['revision'], 'mode': 'rules'}).json()


def payload(case):
    return {'revision': case['revision'], 'decisions': {c['id']: 'accept' for c in case['analysis']['claims']},
            'checklist': {key: True for key in CHECKLIST}}


def test_rejected_environment_reappears_as_report_gap():
    with session() as client:
        case = ruled_case(client)
        review = payload(case)
        environment = next(c['id'] for c in case['analysis']['claims'] if c['category'] == 'environment')
        review['decisions'][environment] = 'reject'
        response = client.post(f"/api/cases/{case['id']}/review", json=review)
        assert response.status_code == 200, response.text
        assert response.json()['review']['missing_fields'] == ['environment']
        report = client.get(f"/api/cases/{case['id']}/report.md").text
        assert 'Which OS, runtime and dependency versions' in report
        assert 'Needs more evidence' in report


def test_environment_only_is_not_an_observed_problem():
    with session() as client:
        case = ruled_case(client)
        review = payload(case)
        review['decisions'] = {c['id']: 'accept' if c['category'] == 'environment' else 'reject' for c in case['analysis']['claims']}
        response = client.post(f"/api/cases/{case['id']}/review", json=review)
        assert response.status_code == 422
        assert client.get(f"/api/cases/{case['id']}/report.md").status_code == 409


def test_corrections_preserve_originals_persist_and_invalidate_on_append():
    with session() as client:
        # Preserve the historical failure pattern without a dependency on private
        # raw output: an actual result and an expectation were labelled as steps.
        # The original archived model response remains untouched in docs/evidence.
        case = ruled_case(client)
        by_category = {c['category']: copy.deepcopy(c) for c in case['analysis']['claims']}
        claims = [by_category[name] for name in ('environment', 'steps', 'observed', 'expected')]
        for index, claim in enumerate(claims, 1):
            claim['id'] = f'c{index}'
        claims[2]['category'] = claims[3]['category'] = 'steps'
        case['analysis']['claims'] = claims
        case['analysis']['questions'] = [
            {'field': 'expected', 'text': 'Expected: one record', 'origin': 'model'},
            {'field': 'steps', 'text': 'Expected: one record', 'origin': 'model'},
        ]
        case['id'] = str(uuid4())
        case['revision'] = 1
        case['review'] = None
        client.app.state.store.create(case)
        original_analysis = copy.deepcopy(case['analysis'])
        original_sources = copy.deepcopy(case['sources'])
        review = payload(case)
        review['category_overrides'] = {'c3': 'observed', 'c4': 'expected'}
        review['excluded_questions'] = [i for i, q in enumerate(case['analysis']['questions']) if q.get('origin') == 'model']
        response = client.post(f"/api/cases/{case['id']}/review", json=review)
        assert response.status_code == 200, response.text
        saved = client.get(f"/api/cases/{case['id']}").json()
        assert saved['analysis'] == original_analysis
        assert saved['sources'] == original_sources
        assert saved['review']['category_overrides'] == review['category_overrides']
        assert saved['review']['missing_fields'] == []
        report = client.get(f"/api/cases/{case['id']}/report.md").text
        assert 'c3 · observed' in report and 'c4 · expected' in report
        assert 'Reviewer correction' in report and 'steps → observed' in report
        assert 'No missing section' in report and 'reproduction has not been verified' in report
        # The bad question repeats a genuine source line, which must still be
        # exported as evidence. Check the question section, not raw text absence.
        assert '- [model]' not in report
        assert 'Reviewer excluded 2 model question(s)' in report
        rejected_environment = {**review, 'revision': saved['revision'],
                                'decisions': {**review['decisions'], 'c1': 'reject'}}
        updated = client.post(f"/api/cases/{case['id']}/review", json=rejected_environment)
        assert updated.status_code == 200, updated.text
        saved = updated.json()
        assert saved['review']['missing_fields'] == ['environment']
        gap_report = client.get(f"/api/cases/{case['id']}/report.md").text
        assert '- [model]' not in gap_report
        assert '[rules] Which OS, runtime and dependency versions' in gap_report
        added = client.post(f"/api/cases/{case['id']}/sources", json={'revision': saved['revision'], 'name': 'new observation', 'text': 'It also fails with two records.'})
        assert added.status_code == 200 and added.json()['review'] is None
        assert client.get(f"/api/cases/{case['id']}/report.md").status_code == 409
        assert client.post(f"/api/cases/{case['id']}/review", json=review).status_code == 409


def test_unknown_rejected_or_hypothesis_overrides_and_bad_question_indices_fail():
    with session() as client:
        case = ruled_case(client)
        base = payload(case)
        route = f"/api/cases/{case['id']}/review"
        for overrides in ({'unknown': 'observed'}, {'c1': 'cause'}):
            response = client.post(route, json={**base, 'category_overrides': overrides})
            assert response.status_code == 422
        rejected = copy.deepcopy(base)
        rejected['decisions']['c1'] = 'reject'
        rejected['category_overrides'] = {'c1': 'steps'}
        assert client.post(route, json=rejected).status_code == 422
        for indices in ([-1], [0], [99], [True], [0, 0]):
            assert client.post(route, json={**base, 'excluded_questions': indices}).status_code == 422
        cause_case = copy.deepcopy(case)
        cause_case['id'] = str(uuid4())
        cause_case['analysis']['claims'][1].update(kind='hypothesis', category='cause')
        client.app.state.store.create(cause_case)
        assert client.post(f"/api/cases/{cause_case['id']}/review", json={**payload(cause_case), 'category_overrides': {'c2': 'observed'}}).status_code == 422
