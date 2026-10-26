"""Input guard contract only: MockTransport never contacts a real model."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from reprolens.model import ModelFailure, ModelSettings, call_model


@pytest.fixture(autouse=True)
def isolated_model_environment(monkeypatch):
    # Inherited workstation credentials must never enter fixture repr or logs.
    for name in ('OPENAI_BASE_URL', 'OPENAI_MODEL', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)


def test_default_environment_and_example_use_6000(monkeypatch):
    monkeypatch.delenv('REPROLENS_AI_INPUT_CHARS', raising=False)
    assert ModelSettings().input_char_limit == 6000
    assert ModelSettings.from_env().input_char_limit == 6000
    example = (Path(__file__).resolve().parents[1] / '.env.example').read_text(encoding='utf-8')
    assert 'REPROLENS_AI_INPUT_CHARS=6000' in example.splitlines()


def test_configuration_repr_omits_credential():
    settings = ModelSettings(api_key='fixture-secret-not-a-real-key')
    assert 'fixture-secret-not-a-real-key' not in repr(settings)
    assert settings.api_key == 'fixture-secret-not-a-real-key'


@pytest.mark.parametrize('value,expected', [('invalid', 6000), ('1500', 1500), ('6000', 6000), ('1', 500), ('13000', 12000)])
def test_explicit_override_and_invalid_fallback(monkeypatch, value, expected):
    monkeypatch.setenv('REPROLENS_AI_INPUT_CHARS', value)
    assert ModelSettings.from_env().input_char_limit == expected


@pytest.mark.parametrize('size', [1501, 5999, 6000, 6001])
@pytest.mark.parametrize('character', ['x', '中', '😀'])
def test_total_source_character_boundary_before_transport(size, character):
    # Two sources ensure this is a combined budget, including source newlines.
    text = character * (size - 1) + '\n'
    sources = [{'id': 's0', 'text': text[:3000]}, {'id': 's1', 'text': text[3000:]}]
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'model': 'fixture-model', 'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{"selected_lines":[],"questions":[]}'}}
        ]})

    settings = ModelSettings('http://127.0.0.1:9999/v1', 'fixture-model')
    operation = call_model(settings, sources, transport=httpx.MockTransport(respond))
    if size > 6000:
        with pytest.raises(ModelFailure, match='model_input_too_large'):
            asyncio.run(operation)
        assert calls == []
    else:
        asyncio.run(operation)
        assert len(calls) == 1
        sent = json.loads(calls[0]['messages'][1]['content'])['untrusted_sources']
        assert [item['text'] for item in sent] == [s['text'].rstrip('\n') for s in sources if s['text'].rstrip('\n')]
        assert calls[0]['max_tokens'] == 800
