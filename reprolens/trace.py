"""Locate report lines in supplied sources; matching is not semantic verification."""


def normalize_line(text):
    return text.strip(' \t\r')


def source_units(sources):
    """Offer whole lines and literal punctuation-delimited fragments, never labels."""
    for source_number, source in enumerate(sources):
        for line_number, line in enumerate(source['text'].splitlines(), 1):
            if not line.strip():
                continue
            common = {'source': source_number, 'source_id': source.get('id', str(source_number)), 'line': line_number}
            yield {**common, 'ref': f"{common['source_id']}:{line_number}", 'text': line,
                   'start': 0, 'end': len(line), 'fragment': False}
            cuts = [0] + [i+1 for i, ch in enumerate(line) if ch in ';；，。！？' or
                          (ch in ',.!?' and (i+1 == len(line) or line[i+1] in ' \t'))] + [len(line)]
            spans = []
            for start, end in zip(cuts, cuts[1:]):
                while start < end and line[start] in ' \t\r': start += 1
                while end > start and line[end-1] in ' \t\r': end -= 1
                if end > start: spans.append((start, end))
            if len(spans) > 1:
                for part, (start, end) in enumerate(spans, 1):
                    yield {**common, 'ref': f"{common['source_id']}:{line_number}.{part}", 'text': line[start:end],
                           'start': start, 'end': end, 'fragment': True}


def source_index(sources):
    index = {}
    for unit in source_units(sources):
        key = normalize_line(unit['text'])
        item = index.setdefault(key, {'count': 0, 'matches': []})
        item['count'] += 1
        if len(item['matches']) < 3:
            match = {'source': unit['source'], 'line': unit['line']}
            if unit['fragment']: match.update(start=unit['start'], end=unit['end'])
            item['matches'].append(match)
    return index


def trace_text(text, index, limit=80):
    entries, total, matched = [], 0, 0
    for line_number, line in enumerate(text.splitlines(), 1):
        key = normalize_line(line)
        if not key:
            continue
        total += 1
        found = index.get(key, {'count': 0, 'matches': []})
        matched += bool(found['count'])
        if len(entries) < limit:
            entries.append({'line': line_number, 'text': line, **found})
    return {'total': total, 'matched': matched, 'edited': total-matched,
            'omitted': total-len(entries), 'entries': entries}
