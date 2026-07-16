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
    precision: float = Field(description="0.0–1.0: subjective narrowing power of this single observation")


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

The `constraint` field is critical — it must be a predicate over people in Singapore, not a topic label:
  BAD:  "mentions a gym"
  GOOD: "regularly attends a gym with 6 am classes, likely within ~1 km of home or workplace"

  BAD:  "mentions bus"
  GOOD: "resides or works within ~400 m of a route 174 bus stop"

  BAD:  "has a dog"
  GOOD: "owns a dog, consistent with HDB pet rules (small breed) or private housing"

If the text contains no locating information, return an empty observations list."""


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
