import re

from .evidence import reviewed_content


def escape(text):
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", text)


def blockquote(text):
    return "\n".join("> " + escape(line) for line in text.splitlines())


def render_report(case):
    analysis = case["analysis"]
    review = case["review"]
    accepted, questions, missing = reviewed_content(analysis, review["decisions"], review.get("category_overrides"), review.get("excluded_questions", []))
    parts = [f"# {escape(case['title'])}",
             f"Case: {case['id']} · revision {case['revision']}",
             "## User description / 用户描述", blockquote(case["sources"][0]["text"]),
             "## Provenance / 来源",
             f"Mode: {analysis['mode']}. Model: {escape(analysis.get('model') or 'none — deterministic rules')}. Generated: {analysis['created_at']}.",
             "Exact quote matches verify location only, not semantic truth or causation. Human acceptance approves inclusion; hypotheses remain unconfirmed.",
             "精确引用校验仅证明原文位置；人工采纳代表同意纳入报告，候选原因仍未证实。",
             f"Human review confirmed: {review['confirmed_at']}"]
    parts += ["## Evidence checklist / 采纳证据检查",
              ("Needs more evidence / 仍需补充: " + ", ".join(missing)) if missing else
              "No missing section in accepted categories; reproduction has not been verified. / 已采纳分类覆盖四栏，不代表复现已验证。"]
    if review.get("excluded_questions"):
        parts.append(f"Reviewer excluded {len(review['excluded_questions'])} model question(s); original output remains in the saved case. / 审阅者排除了模型问题，原始输出仍保留在案例中。")
    if analysis.get("contract") in {"line_selection_v1", "line_selection_v2", "source_selection_v3"}:
        parts.append(f"Selection contract / 选择契约: {analysis['contract']}")
        parts.append("AI selected line references and categories; Python copied the original text verbatim. "
                     "The excerpt wording is source text, not model-generated prose. Questions marked model are model-generated; "
                     "rule prompts are separate. Categories and questions still need independent review.\n\n"
                     "AI 选择行号并分类，程序逐字取回原文；摘录文字不是模型生成。分类与问题仍需独立复核。")
    for kind, heading in [("fact", "Reviewed observations / 已复核观察"), ("hypothesis", "Unconfirmed hypotheses / 未证实的候选原因")]:
        parts.append("## " + heading)
        selected = [c for c in accepted if c["kind"] == kind]
        if not selected:
            parts.append("None included / 未纳入")
        for claim in selected:
            parts.append(f"### {claim['id']} · {claim['category']}")
            if claim["category"] != claim["original_category"]:
                parts.append(f"Reviewer correction / 审阅者纠正: {claim['original_category']} → {claim['category']}. Original extraction preserved / 原提取结果已保留。")
            parts.append(escape(claim["text"]))
            if kind == "hypothesis":
                parts.append("**UNCONFIRMED / 未证实 — requires investigation.**")
            for cite in claim["evidence"]:
                parts.append(f"Evidence: {cite['source_id']} lines {cite['start_line']}–{cite['end_line']} (exact match)")
                parts.append(blockquote(cite["quote"]))
    parts.append("## Missing information / 待补充信息")
    parts += ["- [" + q.get("origin", "legacy_unspecified") + "] " + escape(q["text"]) for q in questions] or ["No additional prompt generated; completeness is not guaranteed."]
    parts += ["## Review checklist / 人工检查", *[f"- [x] {key}" for key in review["checklist"]],
              "## Original evidence / 原始材料", "Includes all deliberately supplied sources. Review privacy again before sharing."]
    for source in case["sources"]:
        parts += [f"### {source['id']} · {escape(source['name'])}", f"SHA-256 (original UTF-8 text): {source['sha256']}",
                  blockquote("\n".join(f"{i}: {line}" for i, line in enumerate(source["text"].splitlines(), 1)))]
    parts += ["---", "Prepared with ReproLens. No submitted code was executed. Edit and validate reproduction steps before filing an issue."]
    return "\n\n".join(parts) + "\n"

