from .db import db
import uuid
from datetime import datetime, timezone

class Detection(db.Model):
    __tablename__ = "detections"

    detection_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id = db.Column(db.String(36), nullable=False, index=True) #atomic service should not have foreign keys
    owner_id = db.Column(db.String(36), nullable=False, index=True) # denormalized from content_drafts at creation time — lets this service check ownership locally instead of calling back to content_drafts on every request
    resolution = db.Column(db.String, nullable=True)             # null (pending) | "accepted" | "rejected"
    category = db.Column(db.String, nullable=False)              # face|location|document|metadata|contact|financial
    source_type = db.Column(db.String(10), nullable=False)       # "text" | "image" | "video" — which scanner found this
    exposure_score = db.Column(db.Integer, nullable=False)       # 1–5
    confidence = db.Column(db.Float, nullable=True)              # 0.0–1.0
    model_version = db.Column(db.String, nullable=True)          # e.g. "vlm-0.3"
    detail = db.Column(db.String(255), nullable=True)            # one-line plain-language explanation
    bounding_region = db.Column(db.JSON, nullable=True)          # {"x":120,"y":340,"w":80,"h":30}, null for text/metadata
    time_range = db.Column(db.JSON, nullable=True)               # {"start":3.2,"end":7.8} seconds, video findings only — null otherwise
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "detection_id": self.detection_id,
            "draft_id": self.draft_id,
            "owner_id": self.owner_id,
            "resolution": self.resolution,
            "category": self.category,
            "source_type": self.source_type,
            "exposure_score": self.exposure_score,
            "confidence": self.confidence,
            "model_version": self.model_version,
            "detail": self.detail,
            "bounding_region": self.bounding_region,
            "time_range": self.time_range,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
