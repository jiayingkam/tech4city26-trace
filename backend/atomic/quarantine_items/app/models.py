from .db import db


class QuarantineItem(db.Model):
    __tablename__ = "quarantine_items"

    # yr attributes