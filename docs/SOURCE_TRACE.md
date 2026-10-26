# Edit-aware source trace

Suppose the model copies “The file is empty” into Actual result. A reviewer changes it to “The file is not empty.” Retaining the old citation would make the new claim look supported. ReproLens recomputes exact matches from the current field text on every input; the changed line becomes wording to check.

Python and JavaScript build the same source index. Each entry maps normalized literal text to up to three source/line locations, character spans and a total occurrence count. Full lines and punctuation-delimited fragments are indexed. Only ASCII outer spaces are ignored; negation, digits and wording remain significant. Unicode spans count code points on both sides, using Array.from in JavaScript to match Python's string offsets. A shared golden fixture checks parity.

Lookup is deliberately exact. It is quick to explain and does not use another uncertain model to certify the first model. A legitimate paraphrase loses automatic linkage; users can still keep it and review it themselves. Identical text in multiple files is ambiguous: UI shows available locations/count, export uses the first location. No claim of semantic entailment, truth or completeness is made.

Each field has a compact expandable comparison. Clicking a match opens the correct source and focuses the original line; Back to report returns to that field. The visual emphasis is a source location, not a confidence score. Export can include only matched excerpts without attaching every source. Confirmation is still tied to the latest saved report revision.

## 学习与面试
技术栈是Python/FastAPI/Pydantic、SQLite、原生JavaScript和本地模型。这个改动把不确定的语义判断留给模型，把可验证的引用位置交给代码。

1. 为什么不用“AI说有来源”当证明？因为来源可能真的存在，但并不支持改后的句子。应校验引用、分类和完整性三个不同问题。
2. 为什么要比较Unicode码点？JavaScript普通下标按UTF-16码元，Python按码点；emoji会让同一个偏移指向不同位置。
3. 为什么改一个字就取消自动匹配？确定性检查必须诚实表达自己的边界。可以人工改写，但不能继承旧证据标签。
4. 为什么不默认导出所有日志？复核只需相关片段时，全文增加阅读负担和隐私暴露；仍保留独立的全文选项。
5. 为什么AI排队返回202不等于完成？后台任务可能失败或被新版本取代。真正的完成是保存结果且版本仍匹配。

验证命令：`python scripts/check.py`、`node scripts/check-source-trace.mjs`、`node scripts/check-frontend.mjs`。浏览器核查与模型语义评测单独记录。实际测试成绩不能替代用户作答或个人掌握程度。
