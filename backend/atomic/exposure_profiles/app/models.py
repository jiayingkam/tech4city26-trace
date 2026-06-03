from .db import db


class ExposureProfile(db.Model):
    __tablename__ = "exposure_profiles"
    
    # yr attributes