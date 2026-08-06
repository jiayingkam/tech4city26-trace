from .db import db
import uuid
from datetime import datetime, timezone


class BusinessAdmin(db.Model):
    """A business's own account for the retention_guard product — deliberately
    separate from TRACE's own `users` table (see the plan's Decisions Locked
    In): a business admin registering their company's database for retention
    scanning is not the same account type as a parent protecting their kid's
    social posts, even though both reuse the same trace_auth JWT plumbing."""
    __tablename__ = "business_admins"

    admin_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    business_name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "admin_id": self.admin_id,
            "email": self.email,
            "business_name": self.business_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
