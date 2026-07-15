from google.cloud import vision

from .cloud_vision_client import get_vision_client

# Cloud Vision's Face Detection is used instead of Object Localization's
# "Person" boxes to find and separate individuals: Object Localization was
# observed merging closely-overlapping people in a crowd into one box (see
# vision_scanner.py's PERSON_ASPECT_RATIO_MAX history), which then either
# got rejected outright or produced a badly oversized guess. Faces stay
# visually distinct even when bodies overlap, so counting/locating people
# by face is far more reliable in a group photo.
MIN_FACE_WIDTH = 60  # filters out small background-crowd faces, not the
                      # foreground subjects a shared photo is actually of


def detect_faces(image_path, width, height):
    """Returns face bounding boxes in real pixel coordinates, largest
    (closest/most prominent) first."""
    with open(image_path, "rb") as f:
        content = f.read()
    response = get_vision_client().face_detection(image=vision.Image(content=content))
    if response.error.message:
        raise RuntimeError(f"Cloud Vision error: {response.error.message}")

    faces = []
    for face in response.face_annotations:
        xs = [v.x for v in face.bounding_poly.vertices]
        ys = [v.y for v in face.bounding_poly.vertices]
        x, y = min(xs), min(ys)
        w, h = max(xs) - x, max(ys) - y
        if w < MIN_FACE_WIDTH:
            continue
        faces.append({"x": round(x), "y": round(y), "w": round(w), "h": round(h)})

    faces.sort(key=lambda f: f["w"] * f["h"], reverse=True)
    return faces


# Multiplied against face width/height to build a generous torso crop for
# pose estimation to work within — wide/tall enough to reliably include
# this person's actual shoulders and hips regardless of pose/camera angle.
# A fixed multiplier alone isn't enough to avoid pulling a neighbor's
# shoulders into the same crop, though: how close two people stand varies
# per photo, and testing on a tightly-packed group showed a fixed cap either
# missed a genuine shoulder or, wide enough not to, regularly caught a
# neighbor too — which made pose converge on the same (more prominent)
# person for two different faces, silently losing the other. So the ideal
# width below is additionally clipped to the midpoint to the nearest other
# detected face on each side, whatever that actually is in this photo.
TORSO_CROP_HALF_WIDTH_FACE_MULT = 2.0
TORSO_CROP_TOP_FACE_MULT = 0.3
TORSO_CROP_BOTTOM_FACE_MULT = 6.0


def estimate_torso_crop(face, all_faces, image_width, image_height):
    """Returns a generous crop region (real pixel coords) around one
    detected face, sized to comfortably contain that person's torso for
    pose estimation — see TORSO_CROP_* above. `all_faces` (every face found
    in the photo, including this one) is used to clip the crop so it never
    crosses into a neighboring person's side."""
    cx = face["x"] + face["w"] / 2
    left = cx - face["w"] * TORSO_CROP_HALF_WIDTH_FACE_MULT
    right = cx + face["w"] * TORSO_CROP_HALF_WIDTH_FACE_MULT

    for other in all_faces:
        if other is face:
            continue
        other_cx = other["x"] + other["w"] / 2
        midpoint = (cx + other_cx) / 2
        if other_cx < cx:
            left = max(left, midpoint)
        elif other_cx > cx:
            right = min(right, midpoint)

    left = max(0, left)
    right = min(image_width, right)
    top = max(0, face["y"] - face["h"] * TORSO_CROP_TOP_FACE_MULT)
    bottom = min(image_height, face["y"] + face["h"] * TORSO_CROP_BOTTOM_FACE_MULT)
    return {"x": round(left), "y": round(top), "w": round(right - left), "h": round(bottom - top)}


# Used only as a last resort, when pose can't be found even within the
# generous torso crop above (a person turned away, heavily occluded, cut off
# at the frame edge, or — as seen in testing with several people standing
# close together — a torso crop wide enough to catch a neighbor's shoulders
# too, which can make pose fail on both). This is used as the actual blur
# region, not just a search window, so it's deliberately tighter than the
# torso crop above: generous enough that testing confirmed it lands on a
# real crest's position, but small enough that a bad trigger on a large,
# close-up face doesn't reach a neighboring face.
CHEST_HALF_WIDTH_FACE_MULT = 0.5
CHEST_TOP_OFFSET_FACE_MULT = 0.85
CHEST_HEIGHT_FACE_MULT = 0.65


def estimate_chest_band_from_face(face):
    """Returns a chest-region estimate in the same coordinate space as
    `face` (real pixel coords if `face` is in real coords, crop-local if
    `face` is crop-local), derived purely from typical head-to-shoulder
    body proportions — no pose, no LLM guess."""
    cx = face["x"] + face["w"] / 2
    x = cx - face["w"] * CHEST_HALF_WIDTH_FACE_MULT
    y = face["y"] + face["h"] * CHEST_TOP_OFFSET_FACE_MULT
    w = face["w"] * CHEST_HALF_WIDTH_FACE_MULT * 2
    h = face["h"] * CHEST_HEIGHT_FACE_MULT
    return {"x": round(x), "y": round(y), "w": round(w), "h": round(h)}
