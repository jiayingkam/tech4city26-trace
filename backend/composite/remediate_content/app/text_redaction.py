import os
from pydantic import BaseModel
from langchain_openai import ChatOpenAI

_SYSTEM_PROMPT = (
    "You rewrite social media captions to remove personal information that "
    "could let a stranger identify or locate the poster, while keeping the "
    "rest of the tone and message as close to the original as possible. "
    "Remove or generalize phone numbers, home/street addresses, full "
    "birthdates, and financial/account details flagged below. Do not add new "
    "information or change anything that wasn't flagged. Return only the "
    "rewritten caption, nothing else."
)


class RedactedCaption(BaseModel):
    rewritten_caption: str


def redact_caption(caption, findings):
    """Returns a copy-pasteable, redacted version of the caption with the
    already-flagged personal details removed. Takes the scanner's findings as
    input rather than re-detecting anything itself."""
    findings_summary = "; ".join(f.get("detail") or f.get("category") for f in findings)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(RedactedCaption)
    result = structured_llm.invoke([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Caption: {caption}\nFlagged issues: {findings_summary}"},
    ])
    return result.rewritten_caption
