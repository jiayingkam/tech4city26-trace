from .db import db
import uuid
from datetime import datetime, timezone

class ContentDrafts(db.Model):
    __tablename__ = "content_drafts"

    draft_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = db.Column(db.String(36), nullable=False, index=True)   # atomic service should not have foreign keys
    content_type = db.Column(db.String, nullable=False)           # "text" | "image" | "video"
    source_app = db.Column(db.String, nullable=True)              # e.g. "instagram", "tiktok"
    storage_path = db.Column(db.String, nullable=True)            # path/key to the raw file, null for text-only drafts
    text_content = db.Column(db.UnicodeText, nullable=True)       # caption/body text; UnicodeText → NVARCHAR(MAX) on SQL Server (supports emoji)
    captured_at = db.Column(db.DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(timezone.utc))
    # Video Intelligence runs as an async job that can far outlive a single
    # HTTP request, so its progress has to survive here rather than in any
    # one scan_video process's memory. null (not video, or not started yet)
    # | "running" | "done" | "failed" — scan_video is the only writer.
    scan_status = db.Column(db.String, nullable=True)
    scan_operation = db.Column(db.String, nullable=True)          # Video Intelligence operation name, while scan_status == "running"

    def to_dict(self):
        return {
            "draft_id": self.draft_id,
            "owner_id": self.owner_id,
            "content_type": self.content_type,
            "source_app": self.source_app,
            "storage_path": self.storage_path,
            "text_content": self.text_content,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "scan_status": self.scan_status,
            "scan_operation": self.scan_operation,
        }