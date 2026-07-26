import os
from typing import List, Literal
from google.cloud import videointelligence
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from .cloud_video_client import get_video_client

# Caps how many distinct on-screen text strings get sent to the LLM
# classifier per video, mirroring ocr_scanner.py's UNCLEAR_MAX_CHECKS /
# vision_scanner.py's MAX_FACES_CHECKED — keeps one text-heavy clip (e.g. a
# scrolling credits reel) from racking up unbounded API calls.
MAX_TEXT_CANDIDATES = 20

# A face simply being on camera is flagged at a fixed, moderate severity —
# unlike image scanning, there's no per-face LLM classification pass here
# (no school-uniform-crest check, no chest-band localization): report-only
# scope only needs to tell the user *that* and *when* a face appears, not
# analyze what it's wearing.
FACE_EXPOSURE_SCORE = 3

_TEXT_CLASSIFY_PROMPT = (
    "You are given a numbered list of short text strings that appeared "
    "on-screen at some point in a video (captions, signage, screens, "
    "documents held up to the camera, etc.), as read by Cloud Video "
    "Intelligence's text detector. For each string, decide whether it "
    "reveals personal information a stranger could use to identify, locate, "
    "contact, or defraud the person in the video, and if so flag it under "
    "exactly one of these categories:\n"
    "- 'location': a house, unit, or block number, a street name/sign, or "
    "another marker that pins down a specific real-world place.\n"
    "- 'financial': a credit/debit card number, CVV, bank account or "
    "PayNow-style payment number, or a cheque's account/routing details.\n"
    "- 'contact': a phone number, email address, or a home/mailing address.\n"
    "- 'document': a vehicle license/number plate, or an ID number from an "
    "official document or credential — passport, national ID/IC, driver's "
    "license, boarding pass booking reference, medical prescription, or a "
    "hospital/event wristband.\n"
    "- 'credentials': a password, PIN, login, or access/security code — "
    "e.g. on a sticky note, whiteboard, or visible on a screen.\n"
    "Ignore shop names, brand names, decorative text, and generic on-screen "
    "UI chrome — most detected strings are noise and should NOT be flagged. "
    "For each flagged string, return its text_index (matching the numbered "
    "list), the category, exposure_score 1 (low risk) to 5 (high risk), "
    "confidence 0.0-1.0, and a one-line plain-language detail. Return no "
    "findings if nothing is sensitive."
)


class VideoTextFinding(BaseModel):
    text_index: int
    category: Literal["location", "financial", "contact", "document", "credentials"]
    exposure_score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    detail: str


class VideoTextScanResult(BaseModel):
    findings: List[VideoTextFinding]


def start_video_scan(gcs_uri):
    """Kicks off an async Cloud Video Intelligence job and returns its
    operation name (a plain string) — not the Operation object itself.
    Cloud Run may route the request that starts this job and the request
    that later polls it to two different container instances, so only the
    durable name (persisted on the draft) can be relied on to still mean
    anything by the time polling happens."""
    client = get_video_client()
    operation = client.annotate_video(request={
        "input_uri": gcs_uri,
        "features": [
            videointelligence.Feature.FACE_DETECTION,
            videointelligence.Feature.TEXT_DETECTION,
        ],
    })
    return operation.operation.name


def poll_video_scan(operation_name):
    """Returns (done, response). response is None while not done. Reconstructs
    the job's status from just its name via the client's raw operations
    client, since the original Operation object from start_video_scan isn't
    available here — see start_video_scan's docstring for why."""
    client = get_video_client()
    raw_op = client.transport.operations_client.get_operation(operation_name)
    if not raw_op.done:
        return False, None
    if raw_op.HasField("error") and raw_op.error.code != 0:
        raise RuntimeError(f"Video Intelligence job failed: {raw_op.error.message}")
    response = videointelligence.AnnotateVideoResponse.deserialize(raw_op.response.value)
    return True, response


def _face_findings(results):
    findings = []
    for annotation in results.face_detection_annotations:
        for track in annotation.tracks:
            findings.append({
                "category": "face",
                "source_type": "video",
                "exposure_score": FACE_EXPOSURE_SCORE,
                "confidence": track.confidence,
                "model_version": "cloud-video-intelligence(face_detection)",
                "detail": "A face appears on camera.",
                "bounding_region": None,
                "time_range": {
                    "start": round(track.segment.start_time_offset.total_seconds(), 2),
                    "end": round(track.segment.end_time_offset.total_seconds(), 2),
                },
            })
    return findings


def _text_candidates(results):
    candidates = []
    for annotation in results.text_annotations:
        for segment in annotation.segments:
            candidates.append({
                "text": annotation.text,
                "start": round(segment.segment.start_time_offset.total_seconds(), 2),
                "end": round(segment.segment.end_time_offset.total_seconds(), 2),
            })
    return candidates


def _classify_text(candidates):
    """Sends detected on-screen text to the same category set ocr_scanner.py
    uses for image text, so a video and a photo report look consistent to
    the user. Kept as its own small copy here rather than importing
    scan_draft's ocr_scanner — that module's classifier is entangled with
    OCR-specific concepts (confidence-based candidate splitting, the
    unclear-signage vision fallback) that don't apply to Video
    Intelligence's already-transcribed text."""
    if not candidates:
        return []

    numbered = "\n".join(f"{i}: {c['text']}" for i, c in enumerate(candidates))
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(VideoTextScanResult)
    result = structured_llm.invoke([
        {"role": "system", "content": _TEXT_CLASSIFY_PROMPT},
        {"role": "user", "content": numbered},
    ])

    findings = []
    for f in result.findings:
        if not 0 <= f.text_index < len(candidates):
            continue
        c = candidates[f.text_index]
        findings.append({
            "category": f.category,
            "source_type": "video",
            "exposure_score": f.exposure_score,
            "confidence": f.confidence,
            "model_version": "gpt-4o-mini+cloud-video-intelligence",
            "detail": f.detail,
            "bounding_region": None,
            "time_range": {"start": c["start"], "end": c["end"]},
        })
    return findings


def collect_findings(response):
    """Turns a completed AnnotateVideoResponse into detection dicts: one per
    tracked face (category 'face') and one per sensitive on-screen text
    string (location/financial/contact/document/credentials), each carrying
    a time_range instead of the bounding_region image findings use — this is
    report-only, so there's no pixel region to blur, only a moment in the
    video to point the user at."""
    results = response.annotation_results[0]
    findings = _face_findings(results)
    findings += _classify_text(_text_candidates(results)[:MAX_TEXT_CANDIDATES])
    return findings
