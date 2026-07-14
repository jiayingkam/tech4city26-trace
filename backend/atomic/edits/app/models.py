from .db import db
import uuid
from datetime import datetime, timezone

class Edit(db.Model):
    __tablename__ = "edits"

    edit_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id = db.Column(db.String(36), nullable=False, index=True)      # atomic service should not have foreign keys
    edit_type = db.Column(db.String, nullable=False)                 # "blur" | "metadata_strip"
    region_affected = db.Column(db.JSON, nullable=True)              # [{"x":120,"y":340,"w":80,"h":30}], null for strips
    status = db.Column(db.String, nullable=False, default="pending") # "pending" | "applied" | "reverted"
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "edit_id": self.edit_id,
            "draft_id": self.draft_id,
            "edit_type": self.edit_type,
            "region_affected": self.region_affected,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
