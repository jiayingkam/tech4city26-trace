from PIL import Image
from PIL.ExifTags import GPSTAGS

GPS_IFD_TAG = 0x8825


def _to_degrees(value):
    d, m, s = value
    return d + (m / 60.0) + (s / 3600.0)


def extract_gps(image_path):
    """Returns {"latitude": float, "longitude": float} or None if no GPS tag is present."""
    img = Image.open(image_path)
    exif = img.getexif()
    if not exif:
        return None
    gps_ifd = exif.get_ifd(GPS_IFD_TAG)
    if not gps_ifd:
        return None
    gps = {GPSTAGS.get(tag, tag): value for tag, value in gps_ifd.items()}
    lat, lat_ref = gps.get("GPSLatitude"), gps.get("GPSLatitudeRef")
    lon, lon_ref = gps.get("GPSLongitude"), gps.get("GPSLongitudeRef")
    if not (lat and lon):
        return None
    latitude = _to_degrees(lat) * (-1 if lat_ref == "S" else 1)
    longitude = _to_degrees(lon) * (-1 if lon_ref == "W" else 1)
    return {"latitude": latitude, "longitude": longitude}


def scan_metadata(image_path):
    """Zero or one detection for embedded GPS/EXIF data. No bounding_region — nothing to blur, only strip."""
    gps = extract_gps(image_path)
    if gps is None:
        return []
    return [{
        "category": "metadata",
        "source_type": "image",
        "exposure_score": 2,  # location is baked into the file but not yet visually confirmed in-frame
        "confidence": 0.95,
        "model_version": "exif-parser-1.0",
        "detail": "This photo has hidden GPS location data saved inside the file.",
        "bounding_region": None,
    }]
