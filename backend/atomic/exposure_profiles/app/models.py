from .db import db
import uuid
from datetime import datetime, timezone


class ExposureProfile(db.Model):
    __tablename__ = "exposure_profiles"

    profile_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = db.Column(db.String(36), nullable=False, index=True)
    window_start = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    window_end = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    total_flags = db.Column(db.Integer, nullable=False, default=0)
    face_flags = db.Column(db.Integer, nullable=False, default=0)
    location_flags = db.Column(db.Integer, nullable=False, default=0)
    document_flags = db.Column(db.Integer, nullable=False, default=0)
    metadata_flags = db.Column(db.Integer, nullable=False, default=0)
    contact_flags = db.Column(db.Integer, nullable=False, default=0)
    financial_flags = db.Column(db.Integer, nullable=False, default=0)
    privacy_health_score = db.Column(db.Float, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "profile_id": self.profile_id,
            "owner_id": self.owner_id,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "total_flags": self.total_flags,
            "category_breakdown": {
                "face": self.face_flags,
                "location": self.location_flags,
                "document": self.document_flags,
                "metadata": self.metadata_flags,
                "contact": self.contact_flags,
                "financial": self.financial_flags,
            },
            "privacy_health_score": self.privacy_health_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
