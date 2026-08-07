from .db import db
import uuid
from datetime import datetime, timezone


class RetentionPolicy(db.Model):
    """A retention rule: {data_source, table, inactive_days threshold, action}.

    inactive_days is a typed integer threshold, not a free-text condition —
    the engine always builds exactly one comparison
    (activity_col < now() - inactive_days) against a column that's already
    passed the ClassifiedColumn whitelist. See the plan's connector design
    note: this removes the need to parse or sandbox an expression language
    at all, which is the single biggest simplification in the whole feature.
    """
    __tablename__ = "retention_policies"

    VALID_ACTIONS = ("anonymise", "delete", "flag")

    policy_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = db.Column(db.String(36), nullable=False, index=True)  # BusinessAdmin.admin_id, no FK
    data_source_id = db.Column(db.String(36), nullable=False, index=True)
    table_name = db.Column(db.String(255), nullable=False)
    inactive_days = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(16), nullable=False, default="anonymise")
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    # null schedule_interval_minutes = manual-only, never picked up by the
    # scheduled sweep. next_scan_due_at starts null, meaning "due immediately"
    # the first time the sweep looks at it.
    schedule_interval_minutes = db.Column(db.Integer, nullable=True)
    next_scan_due_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_scan_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "policy_id": self.policy_id,
            "owner_id": self.owner_id,
            "data_source_id": self.data_source_id,
            "table_name": self.table_name,
            "inactive_days": self.inactive_days,
            "action": self.action,
            "enabled": self.enabled,
            "schedule_interval_minutes": self.schedule_interval_minutes,
            "next_scan_due_at": self.next_scan_due_at.isoformat() if self.next_scan_due_at else None,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
