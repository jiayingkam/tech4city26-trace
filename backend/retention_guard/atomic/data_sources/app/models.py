from .db import db
import uuid
from datetime import datetime, timezone


class DataSource(db.Model):
    """A business's registered external database — retention_guard connects to
    this live to scan/enforce, it never copies the business's rows into its
    own metadata DB (see plan Context: "their data never touches our servers").

    connection_string_encrypted is Fernet ciphertext (see shared/trace_crypto)
    and is deliberately never included in to_dict(), same reasoning as
    business_admins.BusinessAdmin.to_dict() omitting password_hash. The only
    code path that ever produces the plaintext DSN is the internal
    /internal/data-sources/<id>/connection route below."""
    __tablename__ = "data_sources"

    data_source_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = db.Column(db.String(36), nullable=False, index=True)  # BusinessAdmin.admin_id, no cross-service FK
    name = db.Column(db.String(255), nullable=False)
    db_type = db.Column(db.String(32), nullable=False, default="postgresql")  # MVP: postgresql only
    connection_string_encrypted = db.Column(db.UnicodeText, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "data_source_id": self.data_source_id,
            "owner_id": self.owner_id,
            "name": self.name,
            "db_type": self.db_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ClassifiedColumn(db.Model):
    """Tags one column of one table on a DataSource with the role it plays in
    the retention engine's query builder (see composite/enforce_retention):
    "pii" columns get nulled on anonymise, "subject_id" identifies a row for
    the audit log, "activity_timestamp" is what inactive_days is measured
    against. Deliberately a flat 3-way enum, not a free-form tag — the engine
    only ever needs to know exactly these three things (see the plan's
    connector design note on why this keeps the query builder a fixed,
    auditable shape instead of an arbitrary-condition interpreter)."""
    __tablename__ = "classified_columns"

    VALID_ROLES = ("pii", "subject_id", "activity_timestamp")

    classified_column_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    data_source_id = db.Column(db.String(36), nullable=False, index=True)
    table_name = db.Column(db.String(255), nullable=False)
    column_name = db.Column(db.String(255), nullable=False)
    column_role = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "classified_column_id": self.classified_column_id,
            "data_source_id": self.data_source_id,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "column_role": self.column_role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
