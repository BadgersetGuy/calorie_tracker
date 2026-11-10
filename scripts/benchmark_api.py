"""Read-only comparison. Logs status, latency and byte counts, never diary contents."""
import json
import os
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode

origin = os.environ["MEAL_API_URL"].rstrip("/")
if not origin.startswith("https://"): raise RuntimeError("Use HTTPS")
headers = {"Authorization": "Bearer " + os.environ["MOBILE_API_TOKEN"], "X-Meal-Client": "android"}

def fetch(path, label=None, decode=False):
    start = time.monotonic()
    with urlopen(Request(origin + path, headers=headers), timeout=60) as response:
        length = int(response.headers.get("Content-Length", "0"))
        data = response.read(32 * 1024 * 1024)
        if label:
            print(json.dumps(dict(operation=label, status=response.status, elapsed_ms=round((time.monotonic()-start)*1000),
                response_bytes=length or len(data))))
    return json.loads(data) if decode else data

profiles = fetch("/api/v2/profiles", decode=True)
if profiles:
    query = urlencode(dict(user_id=profiles[0]["id"], limit=3))
    compact = fetch("/api/v2/history?" + query + "&view=summary", "history_summary", True)
    fetch("/api/v2/history?" + query, "history_legacy_inline_photos")
    photo = next((m for m in compact["meals"] if m.get("has_photo")), None)
    if photo:
        path = "/api/v2/meals/" + str(photo["id"]) + "/photo"
        fetch(path + "?size=thumbnail", "photo_thumbnail")
        fetch(path + "?size=preview", "photo_preview")
        fetch(path, "photo_original")
