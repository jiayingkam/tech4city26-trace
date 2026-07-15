import mediapipe as mp
import numpy as np

_mp_pose = mp.solutions.pose

# Below this, a landmark is likely occluded/guessed rather than actually
# seen — using it to compute geometry would just relocate the guessing
# problem instead of fixing it.
MIN_LANDMARK_VISIBILITY = 0.5

# How far down from the shoulder line to extend the chest band, as a
# fraction of the shoulder-to-hip distance. Breast pockets sit in the upper
# third to upper half of the torso, not down near the waist.
CHEST_BAND_DEPTH_RATIO = 0.4


def compute_chest_band(crop):
    """Returns {"x","y","w","h"} in crop-local pixel coordinates bracketing
    the whole upper-chest area (spanning both shoulders, from the collar
    down partway to the hips) for the one person in `crop`, or None if a
    pose couldn't be confidently found (occluded, turned away, or the crop
    contains more than one overlapping person and the skeleton fit is
    unreliable).

    A school crest sits somewhere in this band regardless of which side of
    the chest it's sewn on, so this doesn't try to guess left vs. right —
    it only needs to bracket the general area reliably, which real body
    geometry does far better than asking a vision model to eyeball a
    coordinate directly."""
    arr = np.array(crop.convert("RGB"))
    with _mp_pose.Pose(static_image_mode=True, model_complexity=2) as pose:
        result = pose.process(arr)

    if not result.pose_landmarks:
        return None

    lm = result.pose_landmarks.landmark
    points = {
        name: lm[getattr(_mp_pose.PoseLandmark, name)]
        for name in ("LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP")
    }
    if any(p.visibility < MIN_LANDMARK_VISIBILITY for p in points.values()):
        return None

    width, height = crop.width, crop.height
    shoulder_xs = [points["LEFT_SHOULDER"].x * width, points["RIGHT_SHOULDER"].x * width]
    shoulder_ys = [points["LEFT_SHOULDER"].y * height, points["RIGHT_SHOULDER"].y * height]
    hip_ys = [points["LEFT_HIP"].y * height, points["RIGHT_HIP"].y * height]

    left, right = min(shoulder_xs), max(shoulder_xs)
    top = min(shoulder_ys)
    torso_depth = (sum(hip_ys) / 2) - (sum(shoulder_ys) / 2)
    bottom = top + torso_depth * CHEST_BAND_DEPTH_RATIO

    if right <= left or bottom <= top:
        return None

    return {
        "x": round(left),
        "y": round(top),
        "w": round(right - left),
        "h": round(bottom - top),
    }
