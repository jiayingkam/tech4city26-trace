from google.cloud import videointelligence

_video_client = None


def get_video_client():
    """Lazily built and cached. Unlike Cloud Vision (see
    scan_draft/cloud_vision_client.py), Video Intelligence's videos:annotate
    method flatly rejects plain API-key auth — confirmed against the real
    API: it returns 401 UNAUTHENTICATED ("missing required authentication
    credential") even with a valid, correctly-attached key, for both the
    gRPC and REST endpoints. CLOUD_VIDEO_INTELLIGENCE_KEY (in .env) can't be
    used here as a result. This uses Application Default Credentials
    instead — the same GCP service-account JSON already mounted for
    remediate_content/upload_post's GCS access (see docker-compose.yml's
    GOOGLE_APPLICATION_CREDENTIALS + secret/ volume mount), which does have
    permission to call Video Intelligence."""
    global _video_client
    if _video_client is None:
        _video_client = videointelligence.VideoIntelligenceServiceClient()
    return _video_client
