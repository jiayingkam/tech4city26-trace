import os
from typing import Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from .extraction import Observation


class Inference(BaseModel):
    statement: str = Field(
        description="A conclusion phrased as what a stranger could deduce about the person, "
        "written in second person. e.g. 'You study at Dunman High' or 'You usually reach home around 4pm'."
    )
    category: Literal["location", "temporal", "affiliation", "physical", "relation", "possession"]
    confidence: Literal["high", "medium", "low"]
    based_on: list[str] = Field(
        description="The exact observation surfaces or entities this inference rests on. "
        "MUST be non-empty — an inference with nothing to cite must not be made."
    )


class StrangerView(BaseModel):
    inferences: list[Inference]


_SYSTEM = (
    "You are shown structured privacy observations that were already extracted from a "
    "person's social media posts. Your job is to write what a STRANGER could infer about "
    "this person by combining those observations — the cumulative 'mosaic' picture that no "
    "single post reveals on its own. You never invent facts; you only combine what is given."
)

_HUMAN = """\
Each observation below has:
  - kind: the type of signal (location, temporal, affiliation, physical, relation, possession)
  - entity: a resolved real-world thing (a named place/school/employer), or null if unknown
  - constraint: what this observation narrows about the person
  - surface: the original phrase or image finding it came from

Write the inferences a stranger could draw by combining these observations.

HARD RULES — follow every one:
1. Every inference MUST cite, in `based_on`, the observation surfaces/entities it rests on.
   If you cannot cite a real observation, DO NOT make the claim.
2. Name a SPECIFIC place, school, or employer ONLY when an observation's `entity` field
   actually contains that name. If entity is null, generalise instead:
     - a school uniform with no identified name  -> "You attend a specific school" (NOT a named one)
     - a bus route with no named neighbourhood   -> "You live or work near a specific bus route"
3. Set confidence:
     - high   = a named entity is present, OR two or more observations agree
     - medium = one clear constraint but no named entity
     - low    = a single weak or merely-implied signal
4. NEVER infer family situation, relationships, or emotional state unless an observation
   explicitly states it. "home alone" is NOT "parents are overseas". Do not guess these.
5. Prefer fewer, well-grounded inferences over many speculative ones. Combine related
   observations into a single inference where natural.

Observations:
{observations}"""


def _format_observations(observations: list[Observation]) -> str:
    lines = []
    for o in observations:
        entity = o.entity if o.entity else "null"
        lines.append(
            f"- kind={o.kind}; entity={entity}; constraint=\"{o.constraint}\"; surface=\"{o.surface}\""
        )
    return "\n".join(lines)


def synthesise_stranger_view(observations: list[Observation]) -> list[dict]:
    """Combine extracted observations into plain-English 'what a stranger learns' inferences.

    Returns a list of inference dicts (statement/category/confidence/based_on). Every
    inference is grounded in the supplied observations — the prompt forbids uncited claims.
    Returns [] on any failure so the endpoint degrades gracefully.
    """
    if not observations:
        return []

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(StrangerView)
    chain = ChatPromptTemplate.from_messages([("system", _SYSTEM), ("human", _HUMAN)]) | structured_llm

    try:
        result = chain.invoke({"observations": _format_observations(observations)})
        # Drop any inference the model produced without a citation, enforcing rule 1
        # even if the model ignored it.
        return [inf.model_dump() for inf in result.inferences if inf.based_on]
    except Exception:
        return []
