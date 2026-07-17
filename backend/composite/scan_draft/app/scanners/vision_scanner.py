import os
import io
import base64
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from PIL import Image

from .pose_localizer import compute_chest_band
from .face_localizer import detect_faces, estimate_torso_crop, estimate_chest_band_from_face

# House numbers, street signs, and license plates are all text — those are
# handled by ocr_scanner.py, which localizes them with Cloud Vision's real
# pixel coordinates instead of asking this model to guess.
#
# School uniforms/crests/badges have no such text-detector shortcut, so
# localization here finds each person first (via Cloud Vision Face
# Detection — see face_localizer.py for why faces, not Object Localization's
# "Person" boxes, are used to count/locate people), then checks each
# person's clothing in isolation. Judging one person's clothing at a time is
# what actually keeps multiple badges from being merged into a single
# oversized box — asking gpt-4o not to merge them in a crowded group photo
# was tried and unreliable even on a capable model.
_PERSON_CROP_PROMPT = (
    "This is a cropped photo of one person. Look at their clothing for a "
    "school uniform crest or badge that could identify which school they "
    "attend. If one is visible, return is_present=true, exposure_score 1 "
    "(low risk) to 5 (high risk), confidence 0.0-1.0, a one-line "
    "plain-language detail, and a tight bounding box around JUST the "
    "crest/badge itself as FRACTIONS of THIS crop's width/height (x_frac, "
    "y_frac, w_frac, h_frac, each 0-1). If no crest/badge is visible on this "
    "person, return is_present=false and leave the rest at their defaults."
)

# Fallback prompt used only when no faces are found at all (e.g. a badge
# photographed on its own, with nobody wearing it in frame).
_WHOLE_IMAGE_FALLBACK_PROMPT = (
    "You scan a photo for school uniforms, crests, or badges that could "
    "identify which school the person in the photo attends. Flag these as "
    "category 'document'. Do NOT flag faces, house numbers, street signs, or "
    "license plates — those are handled elsewhere by a dedicated OCR pass and "
    "will be caught even if you skip them here. If you do end up flagging a "
    "house number, street sign, or plate anyway, use category 'location' "
    "instead of 'document' so it's labeled correctly. For each finding give "
    "exposure_score 1 (low risk) to 5 (high risk), confidence 0.0-1.0, a "
    "one-line plain-language detail, and a bounding box as FRACTIONS of "
    "image width/height (x_frac, y_frac, w_frac, h_frac, each 0-1) so it "
    "maps to pixels at any resolution. Omit bounding_box only if the "
    "finding has no single localizable region. Return no findings if the "
    "photo is safe."
)


class BoundingBoxFrac(BaseModel):
    x_frac: float = Field(ge=0.0, le=1.0)
    y_frac: float = Field(ge=0.0, le=1.0)
    w_frac: float = Field(ge=0.0, le=1.0)
    h_frac: float = Field(ge=0.0, le=1.0)


class PersonCropFinding(BaseModel):
    is_present: bool
    exposure_score: int = Field(ge=1, le=5, default=1)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    detail: str = ""
    bounding_box: Optional[BoundingBoxFrac] = None


class VisualFinding(BaseModel):
    category: Literal["document", "location"]
    exposure_score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    detail: str
    bounding_box: Optional[BoundingBoxFrac] = None


class VisionScanResult(BaseModel):
    findings: List[VisualFinding]


def _frac_to_pixels(box, width, height, x_offset=0, y_offset=0):
    return {
        "x": x_offset + round(box.x_frac * width),
        "y": y_offset + round(box.y_frac * height),
        "w": round(box.w_frac * width),
        "h": round(box.h_frac * height),
    }


# Guards against a hallucinated box that's implausibly large relative to the
# whole photo — rather than trust it and blur a huge region, the whole
# finding is dropped (see the FALLBACK_MIN_BOX_AREA_FRAC comment below for
# why this can't fall back to a region-less text-only flag instead). Only
# relevant to the no-face whole-photo fallback below; the per-person paths
# use geometric regions (chest band, from pose or from face proportions)
# instead of an LLM-guessed box.
FALLBACK_MAX_BOX_AREA_FRAC = 0.15

# Guards the opposite failure: a box so small it's practically zero-size.
# Neither this nor an oversized box (above) can fall back to a region-less
# "text-only" finding — a "blur" finding with nothing left to anchor it to
# is just a dead entry downstream (a toggle that can never visibly do
# anything), so both cases drop the whole finding instead of keeping it
# region-less.
FALLBACK_MIN_BOX_AREA_FRAC = 0.0005

# Caps how many people get an individual gpt-4o classification call per
# photo, so one large group shot can't rack up unbounded API calls — mirrors
# UNCLEAR_MAX_CHECKS in ocr_scanner.py. Largest/closest faces are checked
# first.
MAX_FACES_CHECKED = 8

# Real body geometry (MediaPipe Pose, run inside a generous per-face torso
# crop — see face_localizer.estimate_torso_crop) is tried before any LLM
# coordinate guessing at all. It brackets the whole chest area
# deterministically from shoulder/hip landmarks, regardless of which side a
# crest is sewn on. Only falls through to the face-proportion heuristic
# below when a pose can't be confidently found (person turned away,
# occluded, or cropped at the frame edge).
#
# gpt-4o is only asked yes/no here, not for a box: testing showed that even
# once the chest band correctly bracketed a real crest — verified by drawing
# the model's own returned box directly on the exact crop it was shown, no
# coordinate math of mine involved — it still consistently missed, off to
# the same side, regardless of how tightly cropped or upscaled the view was.
# That ruled out a bug in this module's coordinate composition; it's a
# genuine gpt-4o grounding limit on a target this small. The chest band
# itself (computed from body geometry, not guessed) is used as the blur
# region instead — larger than the icon alone, but reliably on it rather
# than reliably near it.
CHEST_BAND_PADDING_RATIO = 0.35
CHEST_BAND_UPSCALE = 3


def _is_plausible_box(box, min_area_frac, max_area_frac):
    area = box.w_frac * box.h_frac
    return min_area_frac <= area <= max_area_frac


def _crop_with_padding(img, region, padding_ratio):
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    # Floor keeps a degenerate near-zero-size box (a tiny/rounded w or h)
    # from producing a zero-width crop that fails downstream.
    pad_x, pad_y = max(int(w * padding_ratio), 15), max(int(h * padding_ratio), 15)
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(img.width, x + w + pad_x)
    bottom = min(img.height, y + h + pad_y)
    return img.crop((left, top, right, bottom)), left, top


def _check_crop_for_crest(crop, upscale=1):
    to_send = crop
    if upscale > 1:
        to_send = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)
    buf = io.BytesIO()
    to_send.convert("RGB").save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(PersonCropFinding)
    return structured_llm.invoke([
        {"role": "system", "content": _PERSON_CROP_PROMPT},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]},
    ])


def _scan_whole_image_fallback(image_path, width, height):
    """Used only when no faces are detected at all — same single-call
    whole-photo approach as before this change, still guarded by an area cap."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=os.environ["OPENAI_API_KEY"])
    structured_llm = llm.with_structured_output(VisionScanResult)
    result = structured_llm.invoke([
        {"role": "system", "content": _WHOLE_IMAGE_FALLBACK_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": "Scan this photo."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]},
    ])

    findings = []
    for f in result.findings:
        # A finding this path produces is fundamentally about a specific
        # visual spot in the photo — unlike ocr_scanner's text-based
        # findings, there's no meaningful "flag it, but don't blur anything"
        # state here, so a finding with no plausible box is dropped entirely
        # rather than kept with a null region.
        if not f.bounding_box or not _is_plausible_box(f.bounding_box, FALLBACK_MIN_BOX_AREA_FRAC, FALLBACK_MAX_BOX_AREA_FRAC):
            continue
        findings.append({
            "category": f.category,
            "source_type": "image",
            "exposure_score": f.exposure_score,
            "confidence": f.confidence,
            "model_version": "gpt-4o",
            "detail": f.detail,
            "bounding_region": _frac_to_pixels(f.bounding_box, width, height),
        })
    return findings


def _locate_via_pose(crop):
    """Primary path: brackets the chest area from real body geometry, then
    only asks gpt-4o to classify presence — not to further pinpoint a box,
    per the CHEST_BAND_* comment above. Returns {"region": {x,y,w,h} in
    crop-local pixel coordinates, "exposure_score", "confidence", "detail",
    "model_version"}, or None if no pose or no crest was found."""
    chest_band = compute_chest_band(crop)
    if chest_band is None:
        return None

    chest_crop, chest_x, chest_y = _crop_with_padding(crop, chest_band, CHEST_BAND_PADDING_RATIO)
    result = _check_crop_for_crest(chest_crop, upscale=CHEST_BAND_UPSCALE)
    if not result.is_present:
        return None

    return {
        "region": chest_band, "exposure_score": result.exposure_score,
        "confidence": result.confidence, "detail": result.detail,
        "model_version": "gpt-4o(pose-chest-band)",
    }


def _locate_via_face_heuristic(crop, face_local):
    """Fallback for when a pose can't be confidently found within the torso
    crop (occluded, turned away, cropped at the frame edge). Estimates the
    chest region directly from face proportions instead — cruder than real
    shoulder/hip landmarks since it ignores this specific person's build,
    but still geometry, not an LLM guess. `face_local` is the face box in
    `crop`'s own coordinate space. Returns the same shape as
    _locate_via_pose, or None."""
    region = estimate_chest_band_from_face(face_local)
    region = {
        "x": max(0, region["x"]), "y": max(0, region["y"]),
        "w": min(region["w"], crop.width - max(0, region["x"])),
        "h": min(region["h"], crop.height - max(0, region["y"])),
    }
    if region["w"] <= 0 or region["h"] <= 0:
        return None

    band_crop, _, _ = _crop_with_padding(crop, region, 0.1)
    result = _check_crop_for_crest(band_crop, upscale=2)
    if not result.is_present:
        return None

    return {
        "region": region, "exposure_score": result.exposure_score,
        "confidence": result.confidence, "detail": result.detail,
        "model_version": "gpt-4o(face-heuristic)",
    }


# Caps the working image size for the crop/pose/gpt-4o pipeline below, so
# the full-resolution decoded bitmap isn't held in memory for the whole
# per-face loop. Only applied *after* detect_faces runs on the original
# file — face detection is genuinely resolution-sensitive (a small/distant
# face can fall under face_localizer.MIN_FACE_WIDTH if shrunk first) — so
# this doesn't change who gets scanned, only how much bitmap is carried
# around while scanning them. Downstream of detection, mediapipe resizes
# its input to a fixed small size regardless of crop resolution, and the
# chest-band crop gets upscaled again (CHEST_BAND_UPSCALE) before going to
# gpt-4o, so this cap doesn't cost detection accuracy either.
FACE_SCAN_MAX_DIMENSION = 1600


def scan_image(image_path):
    """Returns a list of detection dicts for identifying documents (school
    uniforms/crests/badges) in an image. Finds people first via Cloud
    Vision's Face Detection (reliable even when bodies overlap in a crowd —
    see face_localizer.py), then checks each person's clothing in
    isolation, so a badge on one person can never get merged into a box
    spanning several. Within each person, real body geometry (pose
    landmarks, run inside a generous per-face torso crop) localizes the
    chest area; if no pose can be found, a cruder face-proportion heuristic
    takes over. Neither path ever asks gpt-4o for a coordinate — only for
    yes/no — since testing showed it can't reliably localize a target this
    small even in an already-tight, correctly-scaled crop."""
    with Image.open(image_path) as img:
        width, height = img.size

    faces = detect_faces(image_path, width, height)[:MAX_FACES_CHECKED]
    if not faces:
        return _scan_whole_image_fallback(image_path, width, height)

    # Everything past this point works in the (possibly) downscaled image's
    # coordinate space; scale is folded back out of the final bounding_region
    # below so reported regions still line up with the original photo.
    scale = min(1.0, FACE_SCAN_MAX_DIMENSION / max(width, height))
    scan_faces = [
        {"x": f["x"] * scale, "y": f["y"] * scale, "w": f["w"] * scale, "h": f["h"] * scale}
        for f in faces
    ]

    findings = []
    with Image.open(image_path) as img:
        if scale < 1.0:
            img = img.resize((round(width * scale), round(height * scale)), Image.LANCZOS)

        for face in scan_faces:
            torso_region = estimate_torso_crop(face, scan_faces, img.width, img.height)
            crop = img.crop((
                torso_region["x"], torso_region["y"],
                torso_region["x"] + torso_region["w"], torso_region["y"] + torso_region["h"],
            ))
            face_local = {
                "x": face["x"] - torso_region["x"], "y": face["y"] - torso_region["y"],
                "w": face["w"], "h": face["h"],
            }

            located = _locate_via_pose(crop)
            if located is None:
                located = _locate_via_face_heuristic(crop, face_local)
            if located is None:
                continue

            region = located["region"]
            findings.append({
                "category": "document",
                "source_type": "image",
                "exposure_score": located["exposure_score"],
                "confidence": located["confidence"],
                "model_version": located["model_version"],
                "detail": located["detail"] or "School uniform crest or badge visible.",
                "bounding_region": {
                    "x": round((torso_region["x"] + region["x"]) / scale),
                    "y": round((torso_region["y"] + region["y"]) / scale),
                    "w": round(region["w"] / scale),
                    "h": round(region["h"] / scale),
                },
            })
    return findings
