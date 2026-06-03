from .db import db


class Detection(db.Model):
    __tablename__ = "detections"

    # yr attributes