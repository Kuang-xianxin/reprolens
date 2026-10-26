"""Typed proposal workflow. No execution tools, hidden retries or remote tracing."""
import asyncio
import copy
import hashlib
import json
import random
import time
from collections import OrderedDict
from dataclasses import replace
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field

from .evidence import validate_extraction
from .model import ModelFailure, SYSTEM_PROMPT
from .schemas import Extraction
from .store import now


class FlowState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stage: Literal['pending', 'extracted', 'review_ready', 'needs_evidence'] = 'pending'
    sources: list[dict] = Field(max_length=12, repr=False)
    source_revision: int = Field(ge=1)
    language: Literal['auto', 'zh', 'en'] = 'auto'
    extraction: Extraction | None = None
    meta: dict = Field(default_factory=dict, repr=False)
    analysis: dict = Field(default_factory=dict, repr=False)


def source_key(case, settings, language):
    # Revision and case identity bind the cache to exactly the reviewed material.
    data = [case['id'], case['revision'], [(s['id'], s['sha256']) for s in case['sources']],
            settings.base_url, settings.model, settings.max_tokens, settings.input_char_limit,
            settings.constrained_json, language, SYSTEM_PROMPT, 'workflow-v1']
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


class ModelGateway:
    """Bounded LRU, same-key singleflight, deadline and dependency circuit breaker."""
    def __init__(self, settings, runner, capacity=32, ttl=60, cooldown=20):
        self.settings, self.runner = settings, runner
        self.capacity, self.ttl, self.cooldown = capacity, ttl, cooldown
        self.cache, self.flights = OrderedDict(), {}
        self.failures, self.open_until = 0, 0.0
        self.metrics = dict(calls=0, hits=0, coalesced=0, failures=0, circuit_rejections=0)

    async def infer(self, key, sources, language):
        clock = time.monotonic()
        for old in [k for k, (deadline, _) in self.cache.items() if deadline <= clock]:
            self.cache.pop(old, None)
        if key in self.cache:
            self.metrics['hits'] += 1
            self.cache.move_to_end(key)
            return copy.deepcopy(self.cache[key][1])
        if key in self.flights:
            self.metrics['coalesced'] += 1
            try:
                async with asyncio.timeout(self.settings.timeout + 1):
                    return copy.deepcopy(await asyncio.shield(self.flights[key]))
            except TimeoutError:
                raise ModelFailure('timeout') from None
        if clock < self.open_until:
            self.metrics['circuit_rejections'] += 1
            raise ModelFailure('model_cooling_down')
        # One actual invocation; callers of another key receive backpressure.
        if self.flights:
            raise ModelFailure('model_busy')
        future = asyncio.get_running_loop().create_future()
        self.flights[key] = future
        try:
            self.metrics['calls'] += 1
            async with asyncio.timeout(self.settings.timeout):
                result = await self.runner(replace(self.settings, response_language=language), sources)
            extraction, meta = result
            result = (Extraction.model_validate(extraction), meta)
            self.failures = 0
            self.open_until = 0
            self.cache[key] = (time.monotonic() + self.ttl * random.uniform(.85, 1.15), copy.deepcopy(result))
            while len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
            future.set_result(result)
            return copy.deepcopy(result)
        except BaseException as exc:
            failure = ModelFailure('timeout') if isinstance(exc, TimeoutError) else exc
            # A failed/cancelled leader must wake every waiter; never leak exception repr.
            future.cancel()
            if not isinstance(exc, asyncio.CancelledError):
                self.metrics['failures'] += 1
                self.failures += 1
                if self.failures >= 3:
                    self.open_until = time.monotonic() + self.cooldown
            raise failure from None
        finally:
            self.flights.pop(key, None)


async def run_workflow(gateway, case, language='auto', checkpoint=None, save_checkpoint=None):
    key = source_key(case, gateway.settings, language)
    state = FlowState(sources=case['sources'], source_revision=case['revision'], language=language)
    if checkpoint:
        state = FlowState.model_validate(checkpoint)
        if state.source_revision != case['revision'] or state.sources != case['sources'] or state.language != language:
            raise ModelFailure('checkpoint_mismatch')

    async def infer(current: FlowState):
        extraction, meta = await gateway.infer(key, current.sources, current.language)
        next_state = current.model_copy(update={'stage': 'extracted', 'extraction': extraction, 'meta': meta})
        if save_checkpoint:
            await save_checkpoint(next_state.model_dump(mode='json'))
        return {'stage': 'extracted', 'extraction': extraction, 'meta': meta}

    def verify(current: FlowState):
        extraction = current.extraction
        if extraction is None:
            raise ModelFailure('invalid_checkpoint')
        validated = validate_extraction(extraction, current.sources, question_origin='model',
                                        fill_missing=current.meta.get('contract') not in {'line_selection_v2', 'source_selection_v3'})
        # Unsupported/hypothetical claims remain marked for review; the draft
        # builder and confirmation gate only accept matched factual evidence.
        status = 'ready' if extraction.claims else 'needs_evidence'
        analysis = {**current.meta, **validated, 'status': status, 'mode': 'ai', 'created_at': now(),
                    'question_language': current.language, 'workflow': 'langgraph-v1', 'source_revision': current.source_revision}
        if not extraction.claims:
            analysis['error'] = 'no_relevant_evidence'
        return {'stage': 'review_ready' if extraction.claims else 'needs_evidence', 'analysis': analysis}

    graph = StateGraph(FlowState)
    graph.add_node('extract', infer)
    graph.add_node('verify_sources', verify)
    graph.add_conditional_edges(START, lambda s: 'verify_sources' if s.stage == 'extracted' else 'extract')
    graph.add_edge('extract', 'verify_sources')
    graph.add_edge('verify_sources', END)
    with tracing_context(enabled=False):
        result = await graph.compile().ainvoke(state.model_dump(), {'recursion_limit': 4, 'callbacks': []})
    return FlowState.model_validate(result).analysis
