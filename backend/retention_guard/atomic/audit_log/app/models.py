from .db import db
import uuid
from datetime import datetime, timezone


class ScanRun(db.Model):
    """One row per dry-run/enforce pass — the compliance-evidence header record:
    which policy, when, how many rows scanned/matched, and whether it
    succeeded. owner_id is denormalized here (not just reachable via
    policy_id) so this service's own ownership checks don't need to call out
    to retention_policies — same "no cross-service FK, no cross-atomic calls"
    convention as the rest of this repo."""
    __tablename__ = "scan_runs"

    VALID_MODES = ("dry_run", "enforce")
    VALID_STATUSES = ("running", "completed", "failed")

    scan_run_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = db.Column(db.String(36), nullable=False, index=True)
    policy_id = db.Column(db.String(36), nullable=False, index=True)
    data_source_id = db.Column(db.String(36), nullable=False, index=True)
    mode = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="running")
    rows_scanned = db.Column(db.Integer, nullable=False, default=0)
    rows_matched = db.Column(db.Integer, nullable=False, default=0)
    error_detail = db.Column(db.UnicodeText, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "scan_run_id": self.scan_run_id,
            "owner_id": self.owner_id,
            "policy_id": self.policy_id,
            "data_source_id": self.data_source_id,
            "mode": self.mode,
            "status": self.status,
            "rows_scanned": self.rows_scanned,
            "rows_matched": self.rows_matched,
            "error_detail": self.error_detail,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class RetentionAction(db.Model):
    """One row per matched subject — the compliance-evidence line item: which
    policy proposed/approved/applied what action against which subject, and
    when. This is per-subject rather than just a count on ScanRun so that
    enforcement can act on (and later prove) an exact, operator-approved set
    of rows — see the plan's connector design note on why enforce acts on
    this approved snapshot rather than re-querying the source."""
    __tablename__ = "retention_actions"

    VALID_ACTION_TYPES = ("anonymise", "delete", "flag")
    VALID_STATUSES = ("proposed", "approved", "applied", "failed")

    action_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = db.Column(db.String(36), nullable=False, index=True)
    scan_run_id = db.Column(db.String(36), nullable=False, index=True)
    policy_id = db.Column(db.String(36), nullable=False, index=True)
    subject_id_value = db.Column(db.String(255), nullable=False, index=True)
    action_type = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="proposed")
    detail = db.Column(db.UnicodeText, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    applied_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "action_id": self.action_id,
            "owner_id": self.owner_id,
            "scan_run_id": self.scan_run_id,
            "policy_id": self.policy_id,
            "subject_id_value": self.subject_id_value,
            "action_type": self.action_type,
            "status": self.status,
            "detail": self.detail,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
        }
