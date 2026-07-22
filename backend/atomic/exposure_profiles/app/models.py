import json
from datetime import datetime, timezone
from .db import db


class ExposureProfile(db.Model):
    """A materialized snapshot of a user's cumulative privacy footprint.

    This is a cache of what detect_mosaic_risk computes live — trajectory,
    score, type breakdown, saves, behaviour, and the stranger-profile. The
    whole computed blob is stored as JSON (UnicodeText -> NVARCHAR(MAX), so it
    survives emoji in captions) rather than exploded into typed columns, since
    the shape still evolves and this atomic service stays trivial.
    """
    __tablename__ = "exposure_profiles"

    user_id = db.Column(db.String(36), primary_key=True)
    profile_json = db.Column(db.UnicodeText, nullable=True)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "profile": json.loads(self.profile_json) if self.profile_json else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
