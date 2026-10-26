from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool, field_validator, model_validator

MAX_CHARS = 12_000
MAX_BYTES = 24_000
MAX_SELECTED_LINES = 12


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def safe_text(value: str) -> str:
    if not value.strip():
        raise ValueError("Text must not be blank / 文本不能为空")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError("Only plain text is supported / 仅支持纯文本")
    return value


class SourceInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["log", "code", "note"] = "note"
    text: str = Field(min_length=1, max_length=MAX_CHARS)

    @field_validator("text", "name")
    @classmethod
    def plain_text(cls, value):
        return safe_text(value)

    @field_validator("name")
    @classmethod
    def filename_only(cls, value):
        if any(c in value for c in "\\/\r\n"):
            raise ValueError("Source names are labels, not paths")
        return value


class CaseInput(StrictModel):
    request_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9-]{16,64}$')
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=6000)
    sources: list[SourceInput] = Field(default_factory=list, max_length=6)

    @field_validator("title", "description")
    @classmethod
    def plain_text(cls, value):
        return safe_text(value)

    @field_validator("title")
    @classmethod
    def single_line(cls, value):
        if "\n" in value or "\r" in value:
            raise ValueError("Title must be one line")
        return value.strip()

    @model_validator(mode="after")
    def bounded(self):
        enforce_budget([self.description] + [s.text for s in self.sources])
        return self


def enforce_budget(texts):
    if sum(len(t) for t in texts) > MAX_CHARS or sum(len(t.encode("utf-8")) for t in texts) > MAX_BYTES:
        raise ValueError("Case limit: 12,000 characters / 24,000 UTF-8 bytes")


class Citation(StrictModel):
    source_id: str = Field(min_length=1, max_length=20)
    start_line: StrictInt = Field(ge=1, le=12000)
    end_line: StrictInt = Field(ge=1, le=12000)
    quote: str = Field(min_length=1, max_length=6000)
    start_char: StrictInt | None = Field(default=None, ge=0, le=12000)
    end_char: StrictInt | None = Field(default=None, ge=1, le=12000)


class Claim(StrictModel):
    kind: Literal["fact", "hypothesis"]
    category: Literal["observed", "environment", "steps", "expected", "cause"]
    text: str = Field(min_length=1, max_length=1000)
    evidence: list[Citation] = Field(min_length=1, max_length=4)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        return safe_text(value)


class Question(StrictModel):
    field: Literal["observed", "environment", "steps", "expected", "cause"]
    text: str = Field(min_length=1, max_length=500)


class Extraction(StrictModel):
    claims: list[Claim] = Field(min_length=0, max_length=MAX_SELECTED_LINES)
    questions: list[Question] = Field(max_length=6)


class SelectedLine(StrictModel):
    ref: str = Field(min_length=1, max_length=32)
    category: Literal["observed", "environment", "steps", "expected"]


class ModelSelection(StrictModel):
    selected_lines: list[SelectedLine] = Field(min_length=0, max_length=MAX_SELECTED_LINES)
    questions: list[Question] = Field(max_length=2)


class AnalyzeInput(StrictModel):
    revision: StrictInt = Field(ge=1)
    mode: Literal["rules", "ai"]
    language: Literal['auto','zh','en'] = 'auto'


class JobInput(StrictModel):
    revision: StrictInt = Field(ge=1)
    language: Literal['auto','zh','en'] = 'auto'
    request_id: str = Field(pattern=r'^[a-zA-Z0-9-]{16,64}$')


class AppendInput(SourceInput):
    revision: StrictInt = Field(ge=1)


class ReviewInput(StrictModel):
    revision: StrictInt = Field(ge=1)
    decisions: dict[str, Literal["accept", "reject"]]
    checklist: dict[str, StrictBool]
    category_overrides: dict[str, Literal["observed", "environment", "steps", "expected"]] = Field(default_factory=dict)
    excluded_questions: list[StrictInt] = Field(default_factory=list, max_length=6)


class IssueFields(StrictModel):
    environment: str = Field(default='',max_length=6000)
    steps: str = Field(default='',max_length=6000)
    observed: str = Field(default='',max_length=6000)
    expected: str = Field(default='',max_length=6000)

    @field_validator('*')
    @classmethod
    def valid_plain(cls,value):
        if value.strip():
            safe_text(value)
        return value

    @model_validator(mode='after')
    def bounded(self):
        enforce_budget(self.model_dump().values())
        return self


class DraftInput(StrictModel):
    revision: StrictInt = Field(ge=1)
    title: str = Field(min_length=1,max_length=160)
    fields: IssueFields

    @field_validator('title')
    @classmethod
    def title_line(cls,value):
        safe_text(value)
        if '\n' in value or '\r' in value:
            raise ValueError('Title must be one line')
        return value.strip()


class ConfirmInput(StrictModel):
    revision: StrictInt = Field(ge=1)
    sources_reviewed: StrictBool
    privacy_reviewed: StrictBool


class RestoreInput(StrictModel):
    revision: StrictInt = Field(ge=1)
    target_revision: StrictInt = Field(ge=1)

