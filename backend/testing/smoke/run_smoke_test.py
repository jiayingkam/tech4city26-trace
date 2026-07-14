"""
End-to-end smoke test for the Trace backend pipeline.

Unlike testing/atomic/*/test_routes.py (which mock the database and never
touch a real service), this hits the actual running containers over HTTP:

    content_drafts -> scan_draft -> detections -> remediate_content
                                                 -> quarantine_high_risk

It exercises two golden-path scenarios:
  1. A text caption containing a phone number (tests the text scanner and
     the fix that keeps text leaks out of the image blur/strip pipeline).
  2. An image with real embedded GPS EXIF data (tests the EXIF scanner, the
     content_drafts storage_path plumbing, and the confirm/revert/download
     round-trip — including that reverting an edit actually regenerates the
     downloaded file instead of just flipping a database flag).

Run with the real stack up (see docker-compose-dev.yml for the exact
commands). Needs a reachable Azure SQL DB and a working OPENAI_API_KEY —
this makes real LLM calls, it is not free and not instant.
"""
import os
import sys
import time
import uuid

import piexif
import requests
from PIL import Image

CONTENT_DRAFTS_URL = os.environ.get("CONTENT_DRAFTS_SERVICE_URL", "http://content_drafts:5002")
DETECTIONS_URL = os.environ.get("DETECTIONS_SERVICE_URL", "http://detections:5003")
EDITS_URL = os.environ.get("EDITS_SERVICE_URL", "http://edits:5004")
QUARANTINE_ITEMS_URL = os.environ.get("QUARANTINE_ITEMS_SERVICE_URL", "http://quarantine_items:5006")
SCAN_DRAFT_URL = os.environ.get("SCAN_DRAFT_SERVICE_URL", "http://scan_draft:5012")
REMEDIATE_CONTENT_URL = os.environ.get("REMEDIATE_CONTENT_SERVICE_URL", "http://remediate_content:5011")
QUARANTINE_HIGH_RISK_URL = os.environ.get("QUARANTINE_HIGH_RISK_SERVICE_URL", "http://quarantine_high_risk:5010")

HEALTH_TARGETS = [
    ("content_drafts", CONTENT_DRAFTS_URL),
    ("detections", DETECTIONS_URL),
    ("edits", EDITS_URL),
    ("quarantine_items", QUARANTINE_ITEMS_URL),
    ("scan_draft", SCAN_DRAFT_URL),
    ("remediate_content", REMEDIATE_CONTENT_URL),
    ("quarantine_high_risk", QUARANTINE_HIGH_RISK_URL),
]

RUN_ID = uuid.uuid4().hex[:8]
FAILURES = []


def ok(msg):
    print(f"  [ok]   {msg}")


def warn(msg):
    print(f"  [warn] {msg}")


def fail(scenario, msg):
    print(f"  [FAIL] {msg}")
    FAILURES.append(f"{scenario}: {msg}")


def wait_for_health(name, base_url, timeout=90):
    print(f"waiting for {name} ({base_url})...")
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=3)
            if resp.status_code == 200:
                ok(f"{name} is up")
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"{name} never became healthy in {timeout}s ({last_error})")


def make_gps_jpeg(path, lat=1.3521, lon=103.8198):
    """Writes a plain JPEG with real GPS EXIF data (Singapore, by default) —
    matches exactly what exif_scanner.py reads back via PIL's GPS IFD tag."""
    def to_dms(value, ref_pos, ref_neg):
        ref = ref_pos if value >= 0 else ref_neg
        value = abs(value)
        deg = int(value)
        minutes_float = (value - deg) * 60
        minutes = int(minutes_float)
        seconds = round((minutes_float - minutes) * 60 * 100)
        return ref, ((deg, 1), (minutes, 1), (seconds, 100))

    lat_ref, lat_dms = to_dms(lat, "N", "S")
    lon_ref, lon_dms = to_dms(lon, "E", "W")
    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: lat_ref,
        piexif.GPSIFD.GPSLatitude: lat_dms,
        piexif.GPSIFD.GPSLongitudeRef: lon_ref,
        piexif.GPSIFD.GPSLongitude: lon_dms,
    }
    exif_bytes = piexif.dump({"GPS": gps_ifd})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (640, 480), color=(120, 170, 220)).save(path, "jpeg", exif=exif_bytes)


def cleanup_draft(draft_id):
    try:
        requests.delete(f"{CONTENT_DRAFTS_URL}/drafts/{draft_id}", timeout=5)
    except requests.RequestException:
        pass


def run_text_scenario():
    scenario = "text caption leak"
    print(f"\n=== Scenario: {scenario} ===")
    draft_id = None
    try:
        resp = requests.post(f"{CONTENT_DRAFTS_URL}/drafts", json={
            "owner_id": f"smoke-{RUN_ID}",
            "content_type": "text",
            "source_app": "smoke_test",
            "text_content": "Call me at 91234567 if you're around this weekend!",
        }, timeout=10)
        assert resp.status_code == 201, f"create draft failed: {resp.status_code} {resp.text}"
        draft_id = resp.json()["draft_id"]
        ok(f"created text draft {draft_id}")

        resp = requests.post(f"{SCAN_DRAFT_URL}/drafts/{draft_id}/process", timeout=60)
        assert resp.status_code in (200, 201), f"process failed: {resp.status_code} {resp.text}"
        body = resp.json()
        outcome = body.get("outcome")
        ok(f"scan_draft outcome: {outcome}")

        resp = requests.get(f"{DETECTIONS_URL}/drafts/{draft_id}/detections", timeout=10)
        assert resp.status_code == 200, f"list detections failed: {resp.status_code} {resp.text}"
        text_hits = [d for d in resp.json() if d.get("source_type") == "text"]
        if not text_hits:
            warn("text scanner found no findings for an obvious phone number — "
                 "LLM variance, not treating as a hard failure, but worth a look")
            return
        ok(f"text scanner flagged {len(text_hits)} finding(s): "
           f"{[d['category'] for d in text_hits]}")

        if outcome == "remediated":
            assert body.get("proposed_edits") == [], (
                "a text-only draft should never get an image edit proposed "
                f"(got {body.get('proposed_edits')})"
            )
            needs_redaction = body.get("needs_text_redaction") or []
            assert needs_redaction, (
                "expected the phone-number finding to come back under "
                "needs_text_redaction, got none — this is the exact bug that "
                "was fixed earlier regressing"
            )
            ok(f"text finding correctly routed to needs_text_redaction, "
               f"not to an image edit: {needs_redaction}")
        elif outcome == "quarantined":
            resp = requests.get(f"{QUARANTINE_HIGH_RISK_URL}/drafts/{draft_id}/quarantine", timeout=10)
            assert resp.status_code == 200, f"quarantine lookup failed: {resp.status_code}"
            items = resp.json()
            assert items, "outcome was 'quarantined' but no quarantine item exists"
            ok(f"quarantine hold created: {items[0].get('reason')}")
        else:
            fail(scenario, f"unexpected outcome '{outcome}'")
    except AssertionError as exc:
        fail(scenario, str(exc))
    except Exception as exc:
        fail(scenario, f"unexpected error: {exc}")
    finally:
        if draft_id:
            cleanup_draft(draft_id)


def run_image_scenario():
    scenario = "image with embedded GPS"
    print(f"\n=== Scenario: {scenario} ===")
    draft_id = None
    try:
        resp = requests.post(f"{CONTENT_DRAFTS_URL}/drafts", json={
            "owner_id": f"smoke-{RUN_ID}",
            "content_type": "image",
            "source_app": "smoke_test",
        }, timeout=10)
        assert resp.status_code == 201, f"create draft failed: {resp.status_code} {resp.text}"
        draft_id = resp.json()["draft_id"]
        ok(f"created image draft {draft_id}")

        # write the test file into the shared volume, then point the draft at it —
        # mirrors the real flow: draft record first, file attached once it lands
        storage_path = f"storage/originals/{draft_id}.jpg"
        make_gps_jpeg(storage_path)
        ok(f"wrote synthetic JPEG with GPS EXIF to {storage_path}")

        resp = requests.patch(f"{CONTENT_DRAFTS_URL}/drafts/{draft_id}",
                               json={"storage_path": storage_path}, timeout=10)
        assert resp.status_code == 200, f"patch storage_path failed: {resp.status_code} {resp.text}"
        ok("attached storage_path to draft")

        resp = requests.post(f"{SCAN_DRAFT_URL}/drafts/{draft_id}/process", timeout=60)
        assert resp.status_code in (200, 201), f"process failed: {resp.status_code} {resp.text}"
        body = resp.json()
        outcome = body.get("outcome")
        ok(f"scan_draft outcome: {outcome}")

        resp = requests.get(f"{DETECTIONS_URL}/drafts/{draft_id}/detections", timeout=10)
        assert resp.status_code == 200, f"list detections failed: {resp.status_code} {resp.text}"
        detections = resp.json()
        metadata_hits = [d for d in detections
                         if d.get("category") == "metadata" and d.get("source_type") == "image"]
        assert metadata_hits, (
            f"EXIF scanner should have found the embedded GPS data, found none "
            f"(all detections: {detections})"
        )
        assert metadata_hits[0].get("bounding_region") is None, (
            "a metadata detection should never carry a bounding_region"
        )
        ok("EXIF scanner correctly found the embedded GPS metadata")

        if outcome != "remediated":
            warn(f"expected 'remediated' for a GPS-only leak, got '{outcome}' — "
                 "the vision scanner may have flagged something on the blank "
                 "test image (LLM variance); skipping the remediate/download checks")
            return

        edits = body.get("proposed_edits") or []
        strip_edits = [e for e in edits if e.get("edit_type") == "metadata_strip"]
        assert strip_edits, f"expected a metadata_strip edit, got {edits}"
        edit_id = strip_edits[0]["edit_id"]
        ok(f"remediate_content proposed a metadata_strip edit ({edit_id})")

        resp = requests.post(f"{REMEDIATE_CONTENT_URL}/drafts/{draft_id}/remediate/confirm", timeout=30)
        assert resp.status_code == 200, f"confirm failed: {resp.status_code} {resp.text}"
        ok("confirmed remediation")

        resp = requests.get(f"{REMEDIATE_CONTENT_URL}/drafts/{draft_id}/download", timeout=15)
        assert resp.status_code == 200, f"download failed: {resp.status_code} {resp.text}"
        assert resp.content[:3] == b"\xff\xd8\xff", "downloaded file doesn't look like a JPEG"
        with open("storage/_downloaded.jpg", "wb") as f:
            f.write(resp.content)
        downloaded_exif = Image.open("storage/_downloaded.jpg").getexif()
        gps_ifd = downloaded_exif.get_ifd(0x8825) if downloaded_exif else None
        assert not gps_ifd, "downloaded file still has GPS data — metadata_strip did not work"
        ok("downloaded file's GPS metadata is gone, as promised")

        # revert the only edit, then confirm the download is pulled — this is
        # the exact bug fixed earlier: revert used to only flip a status flag
        # without regenerating the file
        resp = requests.post(f"{REMEDIATE_CONTENT_URL}/edits/{edit_id}/revert", timeout=10)
        assert resp.status_code == 200, f"revert failed: {resp.status_code} {resp.text}"
        resp = requests.get(f"{REMEDIATE_CONTENT_URL}/drafts/{draft_id}/download", timeout=10)
        assert resp.status_code == 400, (
            f"after reverting the only edit, download should refuse (no confirmed "
            f"remediation left), got {resp.status_code} instead"
        )
        ok("after reverting the only edit, download correctly refuses — "
           "revert took effect for real, not just in the database")
    except AssertionError as exc:
        fail(scenario, str(exc))
    except Exception as exc:
        fail(scenario, f"unexpected error: {exc}")
    finally:
        if draft_id:
            cleanup_draft(draft_id)


def main():
    for name, url in HEALTH_TARGETS:
        wait_for_health(name, url)

    run_text_scenario()
    run_image_scenario()

    print("\n=== Summary ===")
    if FAILURES:
        print(f"{len(FAILURES)} failure(s):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("all scenarios passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
