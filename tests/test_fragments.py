import asyncio
import json

import httpx
import pytest

from reprolens.evidence import make_source, validate_extraction
from reprolens.model import ModelFailure, ModelSettings, call_model
from reprolens.schemas import Extraction
from reprolens.trace import source_units, source_index, trace_text


def infer(sources,selection):
    settings=ModelSettings(base_url='http://127.0.0.1:9999/v1',model='fixture')
    body={'model':'fixture','choices':[{'finish_reason':'stop','message':{'content':json.dumps(selection)}}]}
    return asyncio.run(call_model(settings,sources,httpx.MockTransport(lambda r:httpx.Response(200,json=body))))


def test_literal_fragments_preserve_unicode_offsets_and_reject_tampering():
    sources=[make_source('s0','notes','note','🧪 Windows 11, click Export. The file is empty; it should have two rows.')]
    units=list(source_units(sources))
    selection={'selected_lines':[{'ref':'s0:1.1','category':'environment'},{'ref':'s0:1.2','category':'steps'},{'ref':'s0:1.3','category':'observed'},{'ref':'s0:1.4','category':'expected'}],'questions':[]}
    extraction,meta=infer(sources,selection)
    assert [c.text for c in extraction.claims]==['🧪 Windows 11,','click Export.','The file is empty;','it should have two rows.']
    assert all(c['support']=='source_matched' for c in validate_extraction(extraction,sources)['claims'])
    assert meta['contract']=='source_selection_v3'
    tampered=extraction.model_dump();tampered['claims'][2]['evidence'][0]['start_char']+=1
    assert validate_extraction(Extraction.model_validate(tampered),sources)['claims'][2]['support']=='unsupported'
    assert trace_text('The file is empty;',source_index(sources))['matched']==1


def test_overlapping_full_line_is_not_offered_to_the_model():
    source=make_source('s0','notes','note','Open file. Error 12.')
    with pytest.raises(ModelFailure,match='unknown_reference'):
        infer([source],{'selected_lines':[{'ref':'s0:1','category':'observed'},{'ref':'s0:1.2','category':'observed'}],'questions':[]})


def test_redundant_questions_are_preserved_raw_but_not_reasked():
    raw={'selected_lines':[{'ref':'s0:1','category':'expected'}],'questions':[{'field':'expected','text':'What should happen?'},{'field':'environment','text':'Which version?'}]}
    extraction,meta=infer([make_source('s0','notes','note','Both rows should be present.')],raw)
    assert [q.field for q in extraction.questions]==['environment']
    assert meta['raw_selection']==raw and meta['suppressed_questions']==[raw['questions'][0]]


def test_legacy_full_line_citations_still_validate():
    source=make_source('s0','notes','note','Error 12')
    extraction=Extraction.model_validate({'claims':[{'kind':'fact','category':'observed','text':'Error 12','evidence':[{'source_id':'s0','start_line':1,'end_line':1,'quote':'Error 12'}]}],'questions':[]})
    assert validate_extraction(extraction,[source])['claims'][0]['support']=='source_matched'
