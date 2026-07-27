import json
from datetime import datetime, timezone
from .db import db
import uuid
from datetime import datetime, timezone


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


class CaptionObservationCache(db.Model):
    """Caches detect_mosaic_risk's LLM-extracted observations for one caption's text.

    Keyed by a hash of the caption itself (not draft_id) — a resolved post's caption
    never changes, and re-running the caption LLM call on every mosaic rebuild for
    every post in a user's history is the dominant cost of a slow rebuild. Keying by
    text hash (rather than draft) also means identical captions across posts share one
    cache entry, and removes the run-to-run score jitter identical captions used to
    show (the same text now always returns the same cached extraction).
    """
    __tablename__ = "caption_observation_cache"

    fingerprint = db.Column(db.String(64), primary_key=True)
    observations_json = db.Column(db.UnicodeText, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "fingerprint": self.fingerprint,
            "observations": json.loads(self.observations_json),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
