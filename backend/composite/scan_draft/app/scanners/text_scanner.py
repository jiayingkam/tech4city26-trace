import os
from typing import List, Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

TEXT_CATEGORIES = ("contact", "financial", "document")

_SYSTEM_PROMPT = (
    "You scan short social media captions for personal information that would let a "
    "stranger identify or locate the poster. Flag phone numbers and home/street "
    "addresses as category 'contact', payment/account numbers as 'financial', and "
    "full birthdates (day+month+year) or ID numbers as 'document'. Do not flag "
    "first names, general locations like a country or city name, or vague plans. "
    "For each finding return exposure_score from 1 (low risk) to 5 (high risk), a "
    "confidence from 0.0 to 1.0, and a one-line plain-language detail. Return no "
    "findings if the caption is safe."
)


class TextFinding(BaseModel):
    category: Literal["contact", "financial", "document"]
    exposure_score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    detail: str


class TextScanResult(BaseModel):
    findings: List[TextFinding]


def scan_text(caption):
    """Returns a list of detection dicts for personal details found in caption text.

    Findings never carry a bounding_region — text leaks are handled by redaction,
    not blur/metadata-strip, so downstream remediation must branch on category
    rather than assuming every detection needs an image edit.
    """
    if not caption or not caption.strip():
        return []

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(TextScanResult)
    result = structured_llm.invoke([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": caption},
    ])

    return [{
        "category": f.category,
        "source_type": "text",
        "exposure_score": f.exposure_score,
        "confidence": f.confidence,
        "model_version": "gpt-4o-mini",
        "detail": f.detail,
        "bounding_region": None,
    } for f in result.findings]
