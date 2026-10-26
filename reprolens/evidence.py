import hashlib
import re

from .schemas import Extraction

QUESTIONS = {
    "environment": "Which OS, runtime and dependency versions reproduce this? / 复现时的系统、运行时和依赖版本是什么？",
    "steps": "What exact steps and minimal input reproduce the issue? / 哪些具体步骤和最小输入能复现？",
    "expected": "What should happen instead? / 你期望发生什么？",
    "observed": "What exact error or unexpected output did you observe? / 实际错误或异常输出是什么？",
}


def make_source(source_id, name, kind, text):
    return {"id": source_id, "name": name, "kind": kind, "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def validate_extraction(extraction: Extraction, sources, question_origin="model", fill_missing=True):
    by_id = {source["id"]: source for source in sources}
    claims = []
    for i, claim in enumerate(extraction.claims, 1):
        output = claim.model_dump()
        output["id"] = f"c{i}"
        # Causal language is never elevated to a verified fact by the system.
        if output["category"] == "cause":
            output["kind"] = "hypothesis"
        reasons = []
        for j, cite in enumerate(output["evidence"], 1):
            source = by_id.get(cite["source_id"])
            cite["valid"] = False
            if source is None:
                reason = "unknown_source"
            else:
                lines = source["text"].splitlines()
                start, end = cite["start_line"], cite["end_line"]
                if start > end or end > len(lines):
                    reason = "invalid_line_range"
                else:
                    actual = "\n".join(lines[start - 1:end])
                    char_start, char_end = cite.get('start_char'), cite.get('end_char')
                    if char_start is not None or char_end is not None:
                        if (start != end or char_start is None or char_end is None or
                                not 0 <= char_start < char_end <= len(actual)):
                            cite['error'] = 'invalid_character_range'
                            reasons.append(f'citation_{j}:invalid_character_range')
                            continue
                        actual = actual[char_start:char_end]
                    if actual != cite["quote"]:
                        reason = "quote_mismatch"
                    else:
                        reason = None
                        cite["valid"] = True
            cite["error"] = reason
            if reason:
                reasons.append(f"citation_{j}:{reason}")
        # A matching quote alone does not ground an unrelated generated assertion.
        # Facts in this MVP must be verbatim excerpts; interpretation belongs in hypotheses.
        if output["kind"] == "fact" and output["text"] not in [c["quote"] for c in output["evidence"]]:
            reasons.append("fact_not_verbatim")
        output["support"] = "source_matched" if not reasons else "unsupported"
        output["validation_errors"] = reasons
        output["certainty"] = "unconfirmed_hypothesis" if output["kind"] == "hypothesis" else "needs_human_review"
        claims.append(output)
    covered = {c["category"] for c in claims if c["support"] == "source_matched" and c["kind"] == "fact"}
    questions = [{**q.model_dump(), "origin": question_origin} for q in extraction.questions]
    for field, question in QUESTIONS.items():
        if fill_missing and field not in covered and not any(q["field"] == field for q in questions):
            questions.append({"field": field, "text": question, "origin": "rules"})
    return {"claims": claims, "questions": questions}


def rule_extract(sources):
    """Literal observations only. This is NOT AI inference or root-cause analysis."""
    claims = []
    for source in sources:
        for lineno, line in enumerate(source["text"].splitlines(), 1):
            if not line.strip():
                continue
            category = None
            if re.match(r"^(environment|runtime|python|node|os|环境|系统|版本)\b", line, re.I):
                category = "environment"
            elif re.match(r"^(steps?|复现|步骤)\s*[:：]", line, re.I):
                category = "steps"
            elif re.match(r"^(expected|期望|预期)\s*[:：]", line, re.I):
                category = "expected"
            elif re.match(r"^(actual|observed|result|实际|现象|结果)\s*[:：]", line, re.I):
                category = "observed"
            elif re.search(r"error|exception|traceback|failed|错误|异常|失败", line, re.I):
                category = "observed"
            elif source["id"] == "s0" and lineno == 1:
                category = "observed"
            if category and len(line) <= 1000:
                claims.append({"kind": "fact", "category": category, "text": line,
                               "evidence": [{"source_id": source["id"], "start_line": lineno,
                                             "end_line": lineno, "quote": line}]})
            if len(claims) >= 10:
                break
        if len(claims) >= 10:
            break
    if not claims:
        # A bounded literal excerpt provides something reviewable for arbitrary notes.
        source = sources[0]
        lineno, line = next((i, l) for i, l in enumerate(source["text"].splitlines(), 1) if l.strip())
        if len(line) > 1000:
            # Do not truncate a cited line and pretend it still matches.
            return None
        claims.append({"kind": "fact", "category": "observed", "text": line,
                       "evidence": [{"source_id": source["id"], "start_line": lineno, "end_line": lineno, "quote": line}]})
    return Extraction(claims=claims, questions=[])


def reviewed_content(analysis, decisions, category_overrides=None, excluded_questions=()):
    """Derive the report from reviewed evidence without changing original AI output.

    Category coverage is a checklist, never proof that the bug reproduces.
    """
    overrides = category_overrides or {}
    accepted = [{**c, "category": overrides.get(c["id"], c["category"]), "original_category": c["category"]}
                for c in analysis["claims"] if decisions.get(c["id"]) == "accept"]
    covered = {c["category"] for c in accepted if c["kind"] == "fact" and c["support"] == "source_matched"}
    missing = [field for field in QUESTIONS if field not in covered]
    # Old rule prompts describe the unreviewed extraction, so recompute them.
    # Model questions remain suggestions unless the reviewer explicitly excludes them.
    questions = [q for i, q in enumerate(analysis["questions"])
                 if q.get("origin") != "rules" and i not in excluded_questions]
    if analysis.get("contract") in {"line_selection_v2", "source_selection_v3"}:
        # A gap in accepted evidence does not prove a gap in the full source.
        questions += [{"field": field, "text": f"No accepted evidence in {field}. Check the original sources first; supplement only if absent. / 已采纳证据未覆盖 {field}，请先检查原文，仅在原文缺失时补充。", "origin": "rules"} for field in missing]
    else:
        questions += [{"field": field, "text": QUESTIONS[field], "origin": "rules"} for field in missing]
    return accepted, questions, missing

