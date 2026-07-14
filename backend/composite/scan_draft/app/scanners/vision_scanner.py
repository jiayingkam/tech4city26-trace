import os
import base64
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from PIL import Image

# House numbers, street signs, and license plates are all text — those are
# handled by ocr_scanner.py, which localizes them with Tesseract's real pixel
# coordinates instead of asking this model to guess. Testing showed gpt-4o-mini
# recognizes that a location cue is present far more reliably than it can say
# *where* it is, so this scanner is left with only non-text visual cues, where
# there's no OCR alternative anyway.
_SYSTEM_PROMPT = (
    "You scan a photo for school uniforms, crests, or badges that could "
    "identify which school the person in the photo attends. Flag these as "
    "category 'document'. Do NOT flag faces, house numbers, street signs, or "
    "license plates — those are handled elsewhere. If there are multiple "
    "distinct instances — several uniforms or crests — return one separate "
    "finding per instance, each with its own bounding box. Never summarize "
    "multiple instances into a single finding or a single box spanning "
    "several of them. For each finding give exposure_score 1 (low risk) to 5 "
    "(high risk), confidence 0.0-1.0, a one-line plain-language detail, and a "
    "bounding box as FRACTIONS of image width/height (x_frac, y_frac, w_frac, "
    "h_frac, each 0-1) so it maps to pixels at any resolution. Omit "
    "bounding_box only if the finding has no single localizable region. "
    "Return no findings if the photo is safe."
)


class BoundingBoxFrac(BaseModel):
    x_frac: float = Field(ge=0.0, le=1.0)
    y_frac: float = Field(ge=0.0, le=1.0)
    w_frac: float = Field(ge=0.0, le=1.0)
    h_frac: float = Field(ge=0.0, le=1.0)


class VisualFinding(BaseModel):
    category: Literal["document"]
    exposure_score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    detail: str
    bounding_box: Optional[BoundingBoxFrac] = None


class VisionScanResult(BaseModel):
    findings: List[VisualFinding]


def _frac_to_pixels(box, width, height):
    return {
        "x": round(box.x_frac * width),
        "y": round(box.y_frac * height),
        "w": round(box.w_frac * width),
        "h": round(box.h_frac * height),
    }


def scan_image(image_path):
    """Returns a list of detection dicts for faces/location cues/identifying documents in an image."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(VisionScanResult)
    result = structured_llm.invoke([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": "Scan this photo."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]},
    ])

    with Image.open(image_path) as img:
        width, height = img.size

    findings = []
    for f in result.findings:
        findings.append({
            "category": f.category,
            "source_type": "image",
            "exposure_score": f.exposure_score,
            "confidence": f.confidence,
            "model_version": "gpt-4o-mini",
            "detail": f.detail,
            "bounding_region": _frac_to_pixels(f.bounding_box, width, height) if f.bounding_box else None,
        })
    return findings
