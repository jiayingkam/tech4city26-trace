import os
import time
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
import requests

bp = Blueprint("collect_reddit_comments", __name__)

# yr functions here

# In professional setups, a Load Balancer and/or caller pings this /health URL every few seconds.
# If your code gets stuck in an infinite loop while scraping Reddit,
# it will stop responding to /health.
@bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200