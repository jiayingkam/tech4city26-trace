from .db import db
import uuid
from datetime import datetime, timezone

class Detection(db.Model):
    __tablename__ = "detections"

    detection_id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id = db.Column(db.String, nullable=False, index=True) #atomic service should not have foreign keys
    category = db.Column(db.String, nullable=False)              # face|location|document|metadata|contact|financial
    exposure_score = db.Column(db.Integer, nullable=False)       # 1–5
    confidence = db.Column(db.Float, nullable=True)              # 0.0–1.0
    model_version = db.Column(db.String, nullable=True)          # e.g. "vlm-0.3"
    bounding_region = db.Column(db.JSON, nullable=True)          # {"x":120,"y":340,"w":80,"h":30}, null for text/metadata
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "detection_id": self.detection_id,
            "draft_id": self.draft_id,
            "category": self.category,
            "exposure_score": self.exposure_score,
            "confidence": self.confidence,
            "model_version": self.model_version,
            "bounding_region": self.bounding_region,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
