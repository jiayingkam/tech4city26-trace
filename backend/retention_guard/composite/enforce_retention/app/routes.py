import os
from flask import Blueprint, jsonify, request

import requests
from trace_auth import forwarded_auth_headers

from .retention_engine import ReflectedSource, ClassificationError

bp = Blueprint("enforce_retention", __name__)

# Same rationale as manage_history's DOWNSTREAM_TIMEOUT_S — comfortably
# exceeds the atomic services' own wait_for_db retry budget (12 * 5s here,
# since retention_guard_db is a plain local/hosted Postgres, not Azure SQL
# serverless, so no long auto-pause resume to wait out).
DOWNSTREAM_TIMEOUT_S = 60

BUSINESS_ADMINS_SERVICE_URL = os.environ.get("BUSINESS_ADMINS_SERVICE_URL", "http://business_admins:5101")
DATA_SOURCES_SERVICE_URL = os.environ.get("DATA_SOURCES_SERVICE_URL", "http://data_sources:5102")
RETENTION_POLICIES_SERVICE_URL = os.environ.get("RETENTION_POLICIES_SERVICE_URL", "http://retention_policies:5103")
AUDIT_LOG_SERVICE_URL = os.environ.get("AUDIT_LOG_SERVICE_URL", "http://audit_log:5104")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")

_INTERNAL_HEADERS = {"X-Internal-Key": INTERNAL_API_KEY}


class DownstreamError(Exception):
    """Raised when a call to another retention_guard service fails or
    returns something unexpected — caught once at the route boundary rather
    than checked after every requests call."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _get_policy(policy_id, auth_headers):
    resp = requests.get(
        f"{RETENTION_POLICIES_SERVICE_URL}/policies/{policy_id}", headers=auth_headers, timeout=DOWNSTREAM_TIMEOUT_S
    )
    if resp.status_code == 404:
        raise DownstreamError("policy not found", 404)
    if resp.status_code != 200:
        raise DownstreamError("failed to fetch policy")
    return resp.json()


def _get_data_source(data_source_id, auth_headers):
    resp = requests.get(
        f"{DATA_SOURCES_SERVICE_URL}/data-sources/{data_source_id}", headers=auth_headers, timeout=DOWNSTREAM_TIMEOUT_S
    )
    if resp.status_code == 404:
        raise DownstreamError("data source not found", 404)
    if resp.status_code != 200:
        raise DownstreamError("failed to fetch data source")
    return resp.json()


def _get_classified_columns(data_source_id, table_name, auth_headers):
    resp = requests.get(
        f"{DATA_SOURCES_SERVICE_URL}/data-sources/{data_source_id}/classified-columns",
        params={"table_name": table_name},
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise DownstreamError("failed to fetch classified columns")
    return resp.json()


def _get_connection_string(data_source_id):
    # Internal-only route — enforce_retention never holds the encryption
    # key itself, only ever a decrypted DSN fetched just-in-time (see plan's
    # Encryption section).
    resp = requests.get(
        f"{DATA_SOURCES_SERVICE_URL}/internal/data-sources/{data_source_id}/connection",
        headers=_INTERNAL_HEADERS,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise DownstreamError("failed to fetch data source connection")
    return resp.json()


def _create_scan_run(policy, mode, auth_headers):
    resp = requests.post(
        f"{AUDIT_LOG_SERVICE_URL}/scan-runs",
        json={"policy_id": policy["policy_id"], "data_source_id": policy["data_source_id"], "mode": mode},
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 201:
        raise DownstreamError("failed to create scan run")
    return resp.json()


def _finish_scan_run(scan_run_id, auth_headers, *, status, rows_scanned=None, rows_matched=None, error_detail=None):
    body = {"status": status, "finished": True}
    if rows_scanned is not None:
        body["rows_scanned"] = rows_scanned
    if rows_matched is not None:
        body["rows_matched"] = rows_matched
    if error_detail is not None:
        body["error_detail"] = error_detail
    resp = requests.patch(
        f"{AUDIT_LOG_SERVICE_URL}/scan-runs/{scan_run_id}", json=body, headers=auth_headers, timeout=DOWNSTREAM_TIMEOUT_S
    )
    # Callers use this to report the finished state back to their own
    # caller — returning the pre-finish scan_run instead would show
    # "running"/0 rows even though the underlying record (and, on enforce,
    # the external source) was actually updated correctly.
    return resp.json() if resp.status_code == 200 else None


def _already_applied_subjects(policy_id, auth_headers):
    resp = requests.get(
        f"{AUDIT_LOG_SERVICE_URL}/actions",
        params={"policy_id": policy_id, "status": "applied"},
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise DownstreamError("failed to check existing actions")
    return {a["subject_id_value"] for a in resp.json()}


def _create_actions(scan_run_id, policy, subject_id_values, auth_headers):
    if not subject_id_values:
        return []
    resp = requests.post(
        f"{AUDIT_LOG_SERVICE_URL}/actions",
        json={"actions": [
            {
                "scan_run_id": scan_run_id,
                "policy_id": policy["policy_id"],
                "subject_id_value": sid,
                "action_type": policy["action"],
            }
            for sid in subject_id_values
        ]},
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 201:
        raise DownstreamError("failed to record retention actions")
    return resp.json()


def _approved_actions(policy_id, auth_headers):
    resp = requests.get(
        f"{AUDIT_LOG_SERVICE_URL}/actions",
        params={"policy_id": policy_id, "status": "approved"},
        headers=auth_headers,
        timeout=DOWNSTREAM_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise DownstreamError("failed to fetch approved actions")
    return resp.json()


def _update_action(action_id, auth_headers, *, status, detail=None, applied=False):
    body = {"status": status, "applied": applied}
    if detail is not None:
        body["detail"] = detail
    requests.patch(
        f"{AUDIT_LOG_SERVICE_URL}/actions/{action_id}", json=body, headers=auth_headers, timeout=DOWNSTREAM_TIMEOUT_S
    )


def _build_reflected_source(policy, auth_headers):
    """Shared setup for both scan and enforce: fetch the source's decrypted
    DSN and this policy's table's classified columns, then reflect+whitelist
    (see retention_engine.ReflectedSource — this is where a stale/missing
    classification becomes a ClassificationError instead of a silent skip)."""
    _get_data_source(policy["data_source_id"], auth_headers)  # ownership check, defense in depth
    connection = _get_connection_string(policy["data_source_id"])
    classified_columns = _get_classified_columns(policy["data_source_id"], policy["table_name"], auth_headers)
    return ReflectedSource(connection["connection_string"], policy["table_name"], classified_columns)


def _run_dry_run_scan(policy, auth_headers):
    """The dry-run scan, shared by the caller-facing /policies/<id>/scan
    route and the scheduled sweep. Returns the scan_run dict."""
    scan_run = _create_scan_run(policy, "dry_run", auth_headers)
    try:
        source = _build_reflected_source(policy, auth_headers)
        matches = source.find_matches(policy["inactive_days"])
        already_applied = _already_applied_subjects(policy["policy_id"], auth_headers)
        # Idempotency: a subject already anonymised/deleted by a previous
        # enforce doesn't get re-proposed every scan (see plan).
        new_matches = [sid for sid in matches if sid not in already_applied]
        _create_actions(scan_run["scan_run_id"], policy, new_matches, auth_headers)
        finished = _finish_scan_run(
            scan_run["scan_run_id"], auth_headers,
            status="completed", rows_scanned=len(matches), rows_matched=len(new_matches),
        )
    except ClassificationError as exc:
        _finish_scan_run(scan_run["scan_run_id"], auth_headers, status="failed", error_detail=str(exc))
        raise DownstreamError(str(exc), 422) from exc
    except Exception as exc:  # noqa: BLE001 - always record the failure before re-raising
        _finish_scan_run(scan_run["scan_run_id"], auth_headers, status="failed", error_detail=str(exc))
        raise
    return finished or scan_run


@bp.route("/policies/<policy_id>/scan", methods=["POST"])
def scan_policy(policy_id):
    """Run a dry-run scan for a policy.
    Connects to the policy's data source, finds rows whose activity_timestamp is older than inactive_days, and records each as a proposed RetentionAction. Makes no changes to the external source.
    ---
    tags:
      - Scanning
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: policy_id
        type: string
        required: true
    responses:
      200:
        description: The completed scan run.
        schema:
          type: object
          properties:
            scan_run_id:
              type: string
            status:
              type: string
            rows_scanned:
              type: integer
            rows_matched:
              type: integer
      404:
        description: No such policy, or it isn't owned by the caller.
      422:
        description: The policy's table/columns don't match the live source's schema (see error).
      502:
        description: A downstream retention_guard service call failed.
    """
    auth_headers = forwarded_auth_headers(request)
    try:
        policy = _get_policy(policy_id, auth_headers)
        scan_run = _run_dry_run_scan(policy, auth_headers)
    except DownstreamError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    return jsonify(scan_run), 200


@bp.route("/policies/<policy_id>/enforce", methods=["POST"])
def enforce_policy(policy_id):
    """Enforce a policy against its approved actions.
    Acts strictly on RetentionAction rows currently in status "approved" for this policy — never re-evaluates the original inactive_days condition, so the approved set and the applied set are always identical (see plan). Approve actions first via PATCH on the audit_log service's /actions/<id>.
    ---
    tags:
      - Scanning
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: policy_id
        type: string
        required: true
    responses:
      200:
        description: The completed enforce run.
        schema:
          type: object
          properties:
            scan_run_id:
              type: string
            status:
              type: string
            rows_matched:
              type: integer
      400:
        description: No approved actions to enforce.
      404:
        description: No such policy, or it isn't owned by the caller.
      422:
        description: The policy's table/columns don't match the live source's schema (see error).
      502:
        description: A downstream retention_guard service call failed.
    """
    auth_headers = forwarded_auth_headers(request)
    try:
        policy = _get_policy(policy_id, auth_headers)
        approved = _approved_actions(policy_id, auth_headers)
        if not approved:
            return jsonify({"error": "no approved actions to enforce"}), 400

        scan_run = _create_scan_run(policy, "enforce", auth_headers)
        subject_ids = [a["subject_id_value"] for a in approved]
        try:
            source = _build_reflected_source(policy, auth_headers)
            if policy["action"] == "anonymise":
                rowcount = source.anonymise(subject_ids)
            elif policy["action"] == "delete":
                rowcount = source.delete_rows(subject_ids)
            else:  # "flag" — review-only, no external mutation
                rowcount = len(subject_ids)

            for action in approved:
                _update_action(action["action_id"], auth_headers, status="applied", applied=True,
                                detail=f"{policy['action']} applied by scan_run {scan_run['scan_run_id']}")
            finished = _finish_scan_run(
                scan_run["scan_run_id"], auth_headers,
                status="completed", rows_scanned=len(subject_ids), rows_matched=rowcount,
            )
        except ClassificationError as exc:
            for action in approved:
                _update_action(action["action_id"], auth_headers, status="failed", detail=str(exc))
            _finish_scan_run(scan_run["scan_run_id"], auth_headers, status="failed", error_detail=str(exc))
            raise DownstreamError(str(exc), 422) from exc
        except Exception as exc:  # noqa: BLE001
            for action in approved:
                _update_action(action["action_id"], auth_headers, status="failed", detail=str(exc))
            _finish_scan_run(scan_run["scan_run_id"], auth_headers, status="failed", error_detail=str(exc))
            raise
    except DownstreamError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    return jsonify(finished or scan_run), 200


# ── Scheduling ───────────────────────────────────────────────────────────

@bp.route("/internal/run-scheduled-scans", methods=["POST"])
def run_scheduled_scans():
    """Run dry-run scans for every policy currently due.
    Internal-only. Meant to be hit by an external scheduler (Google Cloud Scheduler in production) rather than an in-process timer — see the plan's Scheduling section, following manage_history's own documented preference for the same reason. For each due policy: claims it via retention_policies' compare-and-swap /internal/policies/<id>/claim (so a second concurrent caller/instance skips it), impersonates its owning admin via business_admins, and runs a dry-run scan. Never auto-enforces — anonymise/delete always needs a human approval step first.
    ---
    tags:
      - Internal
    security:
      - InternalApiKey: []
    responses:
      200:
        description: Which policies were scanned vs. skipped this run.
        schema:
          type: object
          properties:
            scanned_policy_ids:
              type: array
              items:
                type: string
            skipped_policy_ids:
              type: array
              items:
                type: string
      401:
        description: Missing or invalid X-Internal-Key header.
      502:
        description: Failed to fetch the list of due policies.
    """
    resp = requests.get(
        f"{RETENTION_POLICIES_SERVICE_URL}/internal/policies/due", headers=_INTERNAL_HEADERS, timeout=DOWNSTREAM_TIMEOUT_S
    )
    if resp.status_code != 200:
        return jsonify({"error": "failed to fetch due policies"}), 502

    scanned, skipped = [], []
    for policy in resp.json():
        claim_resp = requests.patch(
            f"{RETENTION_POLICIES_SERVICE_URL}/internal/policies/{policy['policy_id']}/claim",
            headers=_INTERNAL_HEADERS,
            timeout=DOWNSTREAM_TIMEOUT_S,
        )
        if claim_resp.status_code != 200 or not claim_resp.json().get("claimed"):
            skipped.append(policy["policy_id"])
            continue

        impersonate_resp = requests.post(
            f"{BUSINESS_ADMINS_SERVICE_URL}/internal/impersonate",
            json={"admin_id": policy["owner_id"]},
            headers=_INTERNAL_HEADERS,
            timeout=DOWNSTREAM_TIMEOUT_S,
        )
        if impersonate_resp.status_code != 200:
            skipped.append(policy["policy_id"])
            continue
        auth_headers = {"Authorization": f"Bearer {impersonate_resp.json()['token']}"}

        try:
            _run_dry_run_scan(policy, auth_headers)
            scanned.append(policy["policy_id"])
        except (DownstreamError, requests.RequestException):
            skipped.append(policy["policy_id"])

    return jsonify({"scanned_policy_ids": scanned, "skipped_policy_ids": skipped}), 200


@bp.get("/health")
def health():
    """Liveness check.
    Unauthenticated — polled frequently by the container orchestrator, so it must respond even while dependencies are unreachable.
    ---
    tags:
      - Health
    responses:
      200:
        description: The service process is alive.
    """
    return jsonify({"status": "ok"}), 200
