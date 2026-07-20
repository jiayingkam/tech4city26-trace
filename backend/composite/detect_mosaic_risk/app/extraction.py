import os
from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate


class Observation(BaseModel):
    kind: Literal["location", "temporal", "affiliation", "physical", "relation", "possession"]
    target: Literal["home", "work", "routine", "identity", "network"]
    surface: str = Field(description="Exact phrase or sentence from the post")
    entity: Optional[str] = Field(default=None, description="Resolved real-world entity, if identifiable")
    constraint: str = Field(
        description=(
            "A predicate over the population of Singapore that this observation rules in or out. "
            "Must describe what it narrows, not what it mentions. "
            "GOOD: 'resides or works within ~400m of a route 174 bus stop' "
            "BAD: 'mentions public transport'"
        )
    )
    contribution_bits: float = Field(
        description=(
            "How many bits of identifying information this single observation reveals. "
            "1 bit halves the candidate population; 2 bits quarters it. "
            "Calibration anchors: "
            "'works in CBD' ~5 bits (200K/6M); "
            "'lives in Tampines' ~4.5 bits (250K/6M); "
            "'takes bus 174 daily' ~1.5 bits; "
            "'has a dog' ~3 bits; "
            "'same fixed running loop, pre-work' ~2 bits; "
            "'specific name/face/address' 8–10 bits. "
            "Must be >= 0. Max 10."
        )
    )


class _ExtractionResult(BaseModel):
    observations: list[Observation]


_SYSTEM = (
    "You are a privacy analyst. Your job is to extract typed observations from social media "
    "post text. Each observation must describe a constraint that narrows where the author "
    "lives, works, travels, or who they are. Extract ONLY facts about the post author's own "
    "life. Ignore facts about third parties, events, or general opinions."
)

_HUMAN = """\
Post text:
\"\"\"
{text}
\"\"\"

For each piece of information that could narrow the author's home, workplace, daily routine, \
physical identity, social network, or possessions, extract one observation.

The `constraint` field must be a predicate over people in Singapore, not a topic label:
  BAD:  "mentions a gym"
  GOOD: "regularly attends a gym with 6 am classes, likely within ~1 km of home or workplace"

  BAD:  "mentions bus"
  GOOD: "resides or works within ~400 m of a route 174 bus stop"

  BAD:  "has a dog"
  GOOD: "owns a dog, consistent with HDB pet rules (small breed) or private housing"

  BAD:  "mentions a run"
  GOOD: "runs a fixed route regularly, likely within ~1 km of home or a regular commute point"

  BAD:  "mentions food near office"
  GOOD: "workplace is within walking distance (~500 m) of a kaya toast stall"

Subtle phrasing counts too — implied routines, fixed habits, and recurring places all narrow \
the anonymity set even without an explicit place name. Extract these even when no location \
name appears.

For `contribution_bits`: estimate bits of identifying information revealed by this observation alone.
  - "works in CBD" → 5.0 (CBD workers ~200 K out of 6 M)
  - "lives in Tampines" → 4.5 (~250 K residents)
  - "takes bus 174 daily" → 1.5 (narrows by route geography)
  - "has a dog" → 3.0 (~700 K dog-owning households)
  - "same fixed running loop, pre-work" → 2.0 (routine + implied geography)
  - "6am class near home" → 2.5 (time + implied proximity)
  - specific face / name / address → 8–10

If the text contains absolutely no information about the author's life, habits, or context, \
return an empty observations list."""


def extract_observations(text: str) -> list[Observation]:
    if not text or not text.strip():
        return []

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(_ExtractionResult)
    chain = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)]) | structured_llm

    try:
        result = chain.invoke({"text": text})
        return result.observations
    except Exception:
        return []
