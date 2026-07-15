import base64
import io
import os
from typing import List, Literal
from google.cloud import vision
from PIL import Image
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from .cloud_vision_client import get_vision_client

# Tesseract's own confidence scale is 0-100. Below CLASSIFY_CONFIDENCE the
# read text is trusted enough to hand to the text classifier below; below
# that it's still kept as a *candidate region* (see UNCLEAR_* constants) —
# dropping it outright meant blurry/distant signage was silently skipped
# even when a human could tell something sign-shaped was there.
CLASSIFY_CONFIDENCE = 55

# Below CLASSIFY_CONFIDENCE, only bother checking a region at all if it's a
# plausible sign size and has a couple of characters — filters out single
# stray marks (a "|" or "=" misread from a window frame) before spending an
# API call on them. This does NOT reliably separate real blurry signage from
# misread textures on its own — that's what the vision check below is for.
UNCLEAR_MIN_AREA = 800
UNCLEAR_MIN_CHARS = 2
# Caps the number of vision "does this look like signage" calls per image so
# one noisy, texture-heavy photo can't rack up unbounded API calls.
UNCLEAR_MAX_CHECKS = 6

_CLASSIFY_PROMPT = (
    "You are given a numbered list of short text snippets read off objects, "
    "signs, documents, screens, or surfaces in a photo via OCR. Each snippet "
    "was read off a physically separate spot in the photo. For each snippet, "
    "decide whether it reveals personal information a stranger could use to "
    "identify, locate, contact, or defraud the person in the photo, and if "
    "so flag it under exactly one of these categories:\n"
    "- 'location': a house, unit, or block number, a street name/sign, or "
    "another marker that pins down a specific real-world place. A bare 2-5 "
    "digit number with no other words next to it (e.g. '308') is still very "
    "often a standalone house/unit/block number sign — flag these at low "
    "confidence rather than dismissing them, unless something in the "
    "snippet itself marks it as a price, score, or date instead.\n"
    "- 'financial': a credit/debit card number, CVV, bank account or "
    "PayNow-style payment number, or a cheque's account/routing details.\n"
    "- 'contact': a phone number, email address, or a home/mailing address "
    "written as text (e.g. on a letter, parcel, or delivery label) — "
    "including a full name paired with that address.\n"
    "- 'document': a vehicle license/number plate, or an ID number from an "
    "official document or credential — passport, national ID/IC, driver's "
    "license, boarding pass booking reference, medical prescription, or a "
    "hospital/event wristband.\n"
    "- 'credentials': a password, PIN, login, or access/security code — "
    "e.g. on a sticky note, whiteboard, or visible on a screen.\n"
    "Ignore shop names, brand names, decorative text, and generic on-screen "
    "UI chrome — most OCR snippets from a photo are noise and should NOT be "
    "flagged. For each flagged snippet, return its text_index (matching the "
    "numbered list), the category, exposure_score 1 (low risk) to 5 (high "
    "risk), confidence 0.0-1.0, and a one-line plain-language detail. "
    "Return no findings if nothing is sensitive."
)

_SIGNAGE_CHECK_PROMPT = (
    "This is a small, cropped, possibly blurry section of a larger photo — "
    "OCR could not read it clearly. Decide if it shows a sign, plaque, "
    "marker, or license plate that could reveal a specific location or "
    "vehicle (a house/unit/block number, street name, or number plate), "
    "even though the text itself isn't legible here. Say no for windows, "
    "foliage, textures, shadows, or anything that is not a sign/plaque/plate. "
    "If yes, guess whether it's more likely a location marker ('location') "
    "or a vehicle plate ('document')."
)


class OcrFinding(BaseModel):
    text_index: int
    category: Literal["location", "financial", "contact", "document", "credentials"]
    exposure_score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    detail: str


class OcrScanResult(BaseModel):
    findings: List[OcrFinding]


# Kept narrower than OcrFinding's categories on purpose: this only fires when
# OCR couldn't read the text at all, so the model is guessing from shape/
# context alone (see _looks_like_signage below). Guessing 'location' or a
# vehicle plate ('document') from a blurry sign shape is reasonable; guessing
# 'financial' or 'credentials' from unreadable text would be unfounded.
class SignageCheck(BaseModel):
    is_signage: bool
    category: Literal["location", "document"] = "location"
    confidence: float = Field(ge=0.0, le=1.0)
    detail: str


def _ocr_lines(img, min_confidence=0):
    """Groups OCR'd words back into paragraphs and returns each one's text,
    average confidence (0-100, to match the scale the rest of this module's
    thresholds already assume), and a bounding box in real pixel coordinates
    (relative to `img` as given) — from Cloud Vision's own detected word
    boxes, no LLM spatial guessing involved. Replaced Tesseract here because
    Tesseract is built for scanned documents and kept missing/misreading
    sparse scene text (a sign photographed at an angle, from a distance);
    Vision's document-text detection handles that case natively. Shared by
    the full-photo pass and the padded-crop re-localization pass below,
    which just hand it different images."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    response = get_vision_client().document_text_detection(image=vision.Image(content=buf.getvalue()))
    if response.error.message:
        raise RuntimeError(f"Cloud Vision error: {response.error.message}")

    results = []
    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                words, confidences, xs, ys = [], [], [], []
                for word in paragraph.words:
                    words.append("".join(symbol.text for symbol in word.symbols))
                    confidences.append(word.confidence)
                    for vertex in word.bounding_box.vertices:
                        xs.append(vertex.x)
                        ys.append(vertex.y)
                if not words:
                    continue
                confidence = (sum(confidences) / len(confidences)) * 100
                if confidence < min_confidence:
                    continue
                results.append({
                    "text": " ".join(words),
                    "confidence": confidence,
                    "region": {
                        "x": min(xs),
                        "y": min(ys),
                        "w": max(xs) - min(xs),
                        "h": max(ys) - min(ys),
                    },
                })
    return results


def _extract_text_lines(image_path):
    return _ocr_lines(Image.open(image_path))


def _merge_nearby_regions(entries, max_gap=10):
    """Merges OCR results whose regions sit close together into one candidate.

    Under PSM 11 (sparse text), Tesseract gives nearly every text island its
    own block, so a multi-line sign like "308 / CHOA CHU KANG / AVENUE 4"
    comes back as three disconnected entries. Classified in isolation, a bare
    "308" reads as ambiguous (could be a price, anything) and gets missed —
    and just as importantly, an unmerged number would never get blurred even
    if the street name next to it does. Merging by proximity first means the
    whole sign is judged, and later blurred, as one unit.
    """
    n = len(entries)
    if n == 0:
        return []

    # Union-find over every pair, not just neighbors in sorted order — an
    # unrelated fragment sitting at a similar height but a different x (e.g.
    # a window frame reflection) would otherwise wedge itself between two
    # lines of the same sign and break the merge.
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    def close(a, b):
        vertical_gap = max(a["y"], b["y"]) - min(a["y"] + a["h"], b["y"] + b["h"])
        horizontal_overlap = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
        return vertical_gap <= max_gap and horizontal_overlap > -max_gap

    for i in range(n):
        for j in range(i + 1, n):
            if close(entries[i]["region"], entries[j]["region"]):
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(entries[i])

    merged = []
    for group in groups.values():
        group.sort(key=lambda e: (e["region"]["y"], e["region"]["x"]))
        xs = [e["region"]["x"] for e in group]
        ys = [e["region"]["y"] for e in group]
        x2s = [e["region"]["x"] + e["region"]["w"] for e in group]
        y2s = [e["region"]["y"] + e["region"]["h"] for e in group]
        merged.append({
            "text": " ".join(e["text"] for e in group),
            "confidence": sum(e["confidence"] for e in group) / len(group),
            "region": {
                "x": min(xs),
                "y": min(ys),
                "w": max(x2s) - min(xs),
                "h": max(y2s) - min(ys),
            },
        })
    return merged


def _classify_by_text(candidates):
    """Sends cleanly-read candidates to the text classifier — precise
    category/severity from the actual words, no image call needed."""
    if not candidates:
        return []

    numbered = "\n".join(f"{i}: {c['text']}" for i, c in enumerate(candidates))
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(OcrScanResult)
    result = structured_llm.invoke([
        {"role": "system", "content": _CLASSIFY_PROMPT},
        {"role": "user", "content": numbered},
    ])

    findings = []
    for f in result.findings:
        if not 0 <= f.text_index < len(candidates):
            continue
        findings.append({
            "category": f.category,
            "source_type": "image",
            "exposure_score": f.exposure_score,
            "confidence": f.confidence,
            "model_version": "gpt-4o-mini+cloud-vision",
            "detail": f.detail,
            "bounding_region": candidates[f.text_index]["region"],
        })
    return findings


def _crop_with_padding(img, region, padding_ratio=1.0):
    """Returns the padded crop plus its own box in the original image's pixel
    coordinates — OCR's tight box is where Tesseract's misread landed, which
    can sit just next to the real sign rather than on it. The padded box is
    what the vision check actually looks at, so it's what should get blurred
    if the check says yes, not the tighter box that may have missed it."""
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    pad_x, pad_y = int(w * padding_ratio), int(h * padding_ratio)
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(img.width, x + w + pad_x)
    bottom = min(img.height, y + h + pad_y)
    padded_region = {"x": left, "y": top, "w": right - left, "h": bottom - top}
    return img.crop((left, top, right, bottom)), padded_region


# Confidence floor for the re-localization OCR pass below. Lower than
# CLASSIFY_CONFIDENCE (55) on purpose: at this stage the text doesn't need to
# be readable enough to classify, just legible enough to say roughly where it
# sits — and upscaling recovers some signal Tesseract missed at full-photo
# resolution, but rarely all of it.
RELOCALIZE_CONFIDENCE = 35
RELOCALIZE_UPSCALE = 3


def _relocalize_via_ocr(img, padded_region):
    """Re-runs Tesseract on just the padded crop, enlarged, to find the real
    pixel location of whatever the vision check flagged inside it.

    Asking the LLM itself for a bounding box was tried and measurably
    unreliable here — the same failure mode already ruled out for the main
    OCR pass (see _extract_text_lines), just resurfacing in the fallback
    path. Re-OCRing the crop instead keeps every reported box grounded in
    real Tesseract pixel coordinates. The upscale matters: text too small to
    read at full-photo resolution can become legible once cropped and
    enlarged on its own. Returns None (caller falls back to the full padded
    region) if nothing legible enough turns up.

    The padded crop can also contain unrelated noise (a window frame,
    foliage) that Tesseract reads with deceptively *higher* confidence than
    the real sign it's misreading through the padding — a plain window-frame
    edge scored 83 against the actual "308" text's 42 in testing — so raw
    confidence alone can't pick the winning cluster. House/unit numbers,
    street signs, and plates virtually always contain a digit, so any
    digit-bearing cluster is preferred over a higher-confidence non-digit
    one; if no cluster has a digit, there's nothing trustworthy to point at.
    """
    x, y, w, h = padded_region["x"], padded_region["y"], padded_region["w"], padded_region["h"]
    crop = img.crop((x, y, x + w, y + h))
    upscaled = crop.resize((w * RELOCALIZE_UPSCALE, h * RELOCALIZE_UPSCALE), Image.LANCZOS)
    lines = _ocr_lines(upscaled, min_confidence=RELOCALIZE_CONFIDENCE)
    if not lines:
        return None

    clusters = _merge_nearby_regions(lines, max_gap=15 * RELOCALIZE_UPSCALE)
    digit_clusters = [c for c in clusters if any(ch.isdigit() for ch in c["text"])]
    if not digit_clusters:
        return None
    best = max(digit_clusters, key=lambda c: c["confidence"])
    r = best["region"]
    return {
        "x": x + r["x"] // RELOCALIZE_UPSCALE,
        "y": y + r["y"] // RELOCALIZE_UPSCALE,
        "w": max(1, r["w"] // RELOCALIZE_UPSCALE),
        "h": max(1, r["h"] // RELOCALIZE_UPSCALE),
    }


def _looks_like_signage(img, region):
    """Crops just the unclear region (plus padding) and asks the vision model
    a narrow question — recognizing 'this looks like a sign' in a small,
    isolated crop plays to what vision models are actually good at, unlike
    asking them to both find and read small text across an entire photo.
    Returns (SignageCheck, region_to_report), where region_to_report is
    tightened via a Tesseract re-pass when one succeeds, since the padding
    is meant to give the model context, not to define the blur area, and a
    hit can legitimately be a real sign near the edge of the crop rather
    than filling it. If re-localization fails to find anything, falls back
    to the original *unpadded* OCR region rather than the padded one —
    padding_ratio=1.0 doubles the box on every side to give the model
    surrounding context, which is fine for asking "is this signage" but far
    too generous to actually blur: at that size the box routinely spills
    into whatever is next to the sign (a nearby face, in testing)."""
    crop, padded_region = _crop_with_padding(img, region)
    buf = io.BytesIO()
    crop.convert("RGB").save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(SignageCheck)
    result = structured_llm.invoke([
        {"role": "system", "content": _SIGNAGE_CHECK_PROMPT},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]},
    ])

    report_region = padded_region
    if result.is_signage:
        report_region = _relocalize_via_ocr(img, padded_region) or region
    return result, report_region


def _classify_by_vision_check(image_path, candidates):
    """For OCR text too garbled to classify by content, falls back to asking
    the vision model whether the isolated region merely looks like signage —
    a lower-precision, higher-recall net for blurry/distant markers that
    would otherwise be silently dropped."""
    eligible = [
        c for c in candidates
        if c["region"]["w"] * c["region"]["h"] >= UNCLEAR_MIN_AREA
        and len(c["text"].replace(" ", "")) >= UNCLEAR_MIN_CHARS
    ][:UNCLEAR_MAX_CHECKS]
    if not eligible:
        return []

    img = Image.open(image_path)
    findings = []
    for candidate in eligible:
        result, report_region = _looks_like_signage(img, candidate["region"])
        if not result.is_signage:
            continue
        findings.append({
            "category": result.category,
            "source_type": "image",
            # Content is unknown (that's the whole reason this path exists),
            # so severity is a fixed, moderate default rather than a guess.
            "exposure_score": 2,
            "confidence": result.confidence,
            "model_version": "gpt-4o-mini+cloud-vision(unclear)",
            "detail": result.detail or "Possible signage detected, but the text was too unclear to read confidently.",
            "bounding_region": report_region,
        })
    return findings


def scan_ocr(image_path):
    """Returns detection dicts for location-identifying text (house/unit
    numbers, street signs) or license plates found via OCR. Clearly-read
    candidates are classified by their text; candidates too garbled to read
    fall back to a focused vision check on just that cropped region, so
    blurry/distant signage isn't silently dropped."""
    candidates = _merge_nearby_regions(_extract_text_lines(image_path))
    if not candidates:
        return []

    classifiable = [c for c in candidates if c["confidence"] >= CLASSIFY_CONFIDENCE]
    unclear = [c for c in candidates if c["confidence"] < CLASSIFY_CONFIDENCE]

    return _classify_by_text(classifiable) + _classify_by_vision_check(image_path, unclear)
