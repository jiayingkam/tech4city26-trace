from os import environ
from google.cloud import storage
from google.api_core.exceptions import NotFound

_client = None


def _bucket():
    """Lazily initialized so importing this module doesn't require credentials
    to already be reachable at process startup.

    Single source of truth for how services persist files that need to
    survive past a single request/instance — copied into each service's
    container at build time (see each Dockerfile's
    `COPY shared/trace_storage trace_storage/`), same as trace_auth/trace_cors.
    Local disk isn't safe for this: Cloud Run can route two requests for the
    same draft to two different container instances, each with its own
    filesystem, so "write it here, read it back later" only works against
    something all instances can see."""
    global _client
    if _client is None:
        _client = storage.Client()
    return _client.bucket(environ["GCS_BUCKET"])


def upload_bytes(blob_name, data, content_type=None):
    _bucket().blob(blob_name).upload_from_string(data, content_type=content_type)


def download_bytes(blob_name):
    """Returns None instead of raising when the blob doesn't exist, matching
    the os.path.exists() checks this replaces."""
    try:
        return _bucket().blob(blob_name).download_as_bytes()
    except NotFound:
        return None


def delete_blob(blob_name):
    """Missing/already-gone is treated as success, matching the
    os.path.exists()-guarded os.remove() calls this replaces."""
    try:
        _bucket().blob(blob_name).delete()
    except NotFound:
        pass


def gcs_uri(blob_name):
    """Returns the gs:// URI for a blob, without downloading it — used by
    scan_video to hand Cloud Video Intelligence a reference it reads
    directly from GCS, instead of shipping the (potentially large) video's
    bytes through this service first."""
    return f"gs://{environ['GCS_BUCKET']}/{blob_name}"
