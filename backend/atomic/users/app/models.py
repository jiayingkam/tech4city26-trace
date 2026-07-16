from .db import db
import uuid
from datetime import datetime, timezone


class User(db.Model):
    __tablename__ = "users"

    user_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    retention_mode = db.Column(db.String, nullable=False, default="auto_expire")  # "auto_expire" | "manual"
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "email": self.email,
            "retention_mode": self.retention_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
