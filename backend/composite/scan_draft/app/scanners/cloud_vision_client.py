import os
from google.api_core.client_options import ClientOptions
from google.cloud import vision

_vision_client = None


def get_vision_client():
    """Lazily built and cached — CLOUD_VISION_KEY is a plain API key (not a
    service-account JSON), so auth is passed via client_options rather than
    the usual GOOGLE_APPLICATION_CREDENTIALS file, matching how every other
    API key in this codebase already lives in .env. Shared by ocr_scanner.py
    (text detection) and vision_scanner.py (person localization) so the
    client is only built once per process."""
    global _vision_client
    if _vision_client is None:
        _vision_client = vision.ImageAnnotatorClient(
            client_options=ClientOptions(api_key=os.environ["CLOUD_VISION_KEY"])
        )
    return _vision_client
