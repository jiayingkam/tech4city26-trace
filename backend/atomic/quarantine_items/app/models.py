from .db import db
import uuid
from datetime import datetime, timezone

class QuarantineItem(db.Model):
    __tablename__ = "quarantine_items"

    quarantine_id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id = db.Column(db.String, db.ForeignKey("content_drafts.draft_id"), nullable=False, index=True)
    reason = db.Column(db.String, nullable=False)                    # plain-language: "Visible house number + GPS location"
    cooldown_expiry = db.Column(db.DateTime(timezone=True), nullable=False)
    state = db.Column(db.String, nullable=False, default="held")     # "held" | "accepted" | "edited" | "deleted"
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "quarantine_id": self.quarantine_id,
            "draft_id": self.draft_id,
            "reason": self.reason,
            "cooldown_expiry": self.cooldown_expiry.isoformat() if self.cooldown_expiry else None,
            "state": self.state,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }