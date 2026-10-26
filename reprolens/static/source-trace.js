// Literal line lookup only. Shared fixtures check parity with trace.py.
export const normalizeLine = (text) => text.replace(/^[ \t\r]+|[ \t\r]+$/g, '');
export const splitSource = (text) => text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/);

export function sourceUnits(sources) {
  const units = [];
  sources.forEach((source, sourceNumber) => splitSource(source.text).forEach((line, number) => {
    if (!line.trim()) return;
    const chars = Array.from(line), common = {source:sourceNumber, line:number+1};
    units.push({...common, text:line});
    const cuts = [0];
    chars.forEach((ch,i) => { if (';；，。！？'.includes(ch) || (',.!?'.includes(ch) && (i+1 === chars.length || ' \t'.includes(chars[i+1])))) cuts.push(i+1); });
    cuts.push(chars.length);
    const spans = [];
    for (let i=1;i<cuts.length;i++) {
      let start=cuts[i-1],end=cuts[i];
      while(start<end && ' \t\r'.includes(chars[start])) start++;
      while(end>start && ' \t\r'.includes(chars[end-1])) end--;
      if(end>start) spans.push({start,end});
    }
    if(spans.length>1) for(const span of spans) units.push({...common,...span,text:chars.slice(span.start,span.end).join('')});
  }));
  return units;
}

export function sourceIndex(sources) {
  const index = new Map();
  for (const unit of sourceUnits(sources)) {
      const key = normalizeLine(unit.text);
      if (!key) continue;
      let item = index.get(key);
      if (!item) { item = {count: 0, matches: []}; index.set(key, item); }
      item.count++;
      if (item.matches.length < 3) {
        const match={source:unit.source,line:unit.line};
        if(unit.start !== undefined) Object.assign(match,{start:unit.start,end:unit.end});
        item.matches.push(match);
      }
  }
  return index;
}

export function traceText(text, index, limit = 80) {
  const result = {total: 0, matched: 0, edited: 0, omitted: 0, entries: []};
  splitSource(text).forEach((line, lineNumber) => {
    const key = normalizeLine(line);
    if (!key) return;
    const found = index.get(key) || {count: 0, matches: []};
    result.total++;
    if (found.count) result.matched++;
    if (result.entries.length < limit) result.entries.push({line: lineNumber + 1, text: line, ...found});
  });
  result.edited = result.total - result.matched;
  result.omitted = result.total - result.entries.length;
  return result;
}
