from .db import db


class User(db.Model):
    __tablename__ = "users"

    # yr attributes