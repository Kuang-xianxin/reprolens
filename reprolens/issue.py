"""User-facing issue fields. Model selections remain untouched in analysis."""
from .report import escape, blockquote
from .trace import source_index, normalize_line

FIELDS = ('environment','steps','observed','expected')


def fields_from_analysis(analysis):
    result = {key: [] for key in FIELDS}
    for claim in (analysis or {}).get('claims',[]):
        if claim['kind']=='fact' and claim['support']=='source_matched' and claim['category'] in result:
            result[claim['category']].append(claim['text'])
    return {key:'\n'.join(lines) for key,lines in result.items()}


def render_issue(case, language='en', include_sources=False, include_evidence=False):
    zh = language == 'zh'
    fields = case['draft']['fields']
    headings = {'environment':'环境与版本','steps':'复现步骤','observed':'实际结果','expected':'预期结果'} if zh else {'environment':'Environment','steps':'Steps to reproduce','observed':'Actual result','expected':'Expected result'}
    parts = ['# '+escape(case['title'])]
    index = source_index(case['sources']) if include_evidence else {}
    cited = {}
    for key in FIELDS:
        lines = []
        for line in fields[key].split('\n'):
            found = index.get(normalize_line(line))
            if found:
                match = found['matches'][0]
                ref = f"src-{match['source']+1}-{match['line']}" + (f"-c{match['start']}" if 'start' in match else '')
                cited[ref] = match
                lines.append(escape(line) + f' [^{ref}]')
            else:
                lines.append(escape(line))
        parts += ['## '+headings[key], '\n'.join(lines) if fields[key].strip() else ('待补充' if zh else 'Not provided')]
    parts += ['---', ('已由报告整理者复核；尚未验证问题复现。' if zh else 'Reviewed by the report author. Reproduction has not been verified.')]
    if include_evidence:
        parts += ['## '+('引用定位' if zh else 'Source references'),
                  ('引用定位到相同原文行或片段（忽略首尾空格），不证明事实或根因。无引用的文字需人工核对；重复文本定位到首次出现处。' if zh else
                   'References locate equal source lines or fragments (ignoring outer spaces), not verified facts or causes. Unreferenced wording needs manual comparison. Duplicate text links to its first occurrence.')]
        for ref, match in cited.items():
            source = case['sources'][match['source']]
            quote = source['text'].splitlines()[match['line']-1]
            if 'start' in match: quote = quote[match['start']:match['end']]
            parts.append(f"[^{ref}]: {escape(source['name'])}, {'第' if zh else 'line '}{match['line']}{'行' if zh else ''} — {escape(quote)}")
        if not cited:
            parts.append('没有找到相同原文行或片段。' if zh else 'No equal source lines or fragments found.')
    if include_sources:
        parts += ['## '+('原始材料' if zh else 'Original sources')]
        for source in case['sources']:
            parts += ['### '+escape(source['name']),blockquote(source['text'])]
    return '\n\n'.join(parts)+'\n'
