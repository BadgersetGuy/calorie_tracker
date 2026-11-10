"""Runs on the existing Fly Machine. Output is captured privately by the deploy runner."""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid

def database_path(root):
    uri = os.getenv("DATABASE_URL", "sqlite:////data/meals.db")
    if not uri.startswith("sqlite:///"):
        raise RuntimeError("Deployment helper expects the existing SQLite database")
    path = Path(uri[len("sqlite:///"):]).resolve()
    root = Path(root).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RuntimeError("Existing database is not a file on the expected data volume")
    return path

def inspect_database(path):
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=30) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")
        counts = {name: connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0] for name in ("user", "meal")}
        required = {"user": {"id", "username", "target_calories", "target_protein", "target_carbs", "target_fat"},
                    "meal": {"id", "user_id", "date", "weight", "calories", "protein", "carbs", "fat", "image_data", "psoriasis_score"}}
        for table, names in required.items():
            actual = {row[1] for row in connection.execute('PRAGMA table_info("' + table + '")')}
            if names - actual:
                raise RuntimeError("Existing schema needs the explicit additive upgrade before deployment")
    return counts

def backup(root="/data"):
    path = database_path(root)
    folder = Path(root) / "backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    size = path.stat().st_size
    if shutil.disk_usage(root).free < size + 64 * 1024 * 1024:
        raise RuntimeError("Not enough free space for a verified local database backup")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    target = folder / ("before-android-" + stamp + ".db")
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=30) as source:
        with sqlite3.connect(target) as destination:
            source.backup(destination, pages=128, sleep=.05)
    os.chmod(target, 0o600)
    counts = inspect_database(target)
    checksum = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): checksum.update(chunk)
    result = dict(backup_path=str(target), sha256=checksum.hexdigest(), counts=counts,
                  source_path=str(path), integrity="ok")
    manifest = target.with_suffix(".json")
    manifest.write_text(json.dumps(result)); os.chmod(manifest, 0o600)
    return result

def choose_model():
    key = os.getenv("OPENAI_API_KEY")
    if not key: raise RuntimeError("Existing app has no OpenAI credential")
    from PIL import Image
    buffer = io.BytesIO(); Image.new("RGB", (32, 32), "green").save(buffer, "JPEG")
    image = base64.b64encode(buffer.getvalue()).decode()
    candidates = ["gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra", "gpt-5.2", "gpt-5.1"]
    for model in candidates:
        payload = dict(model=model, store=False, max_output_tokens=128,
            input=[dict(role="user", content=[dict(type="input_text", text="Deployment access check. Reply OK."),
                dict(type="input_image", image_url="data:image/jpeg;base64," + image)])])
        req = Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=100) as response:
                if response.status == 200: return dict(model=model, vision_access=True)
        except HTTPError as error:
            if error.code in (401, 429):
                raise RuntimeError("Provider credential/quota needs attention before rollout") from None
            if error.code not in (400, 403, 404): raise RuntimeError("Provider access check failed") from None
    raise RuntimeError("None of the configured upgraded vision models is accessible")

def verify(manifest, port, root="/data"):
    path = database_path(root)
    saved = json.loads(Path(manifest).read_text())
    counts = inspect_database(path)
    if str(path) != saved["source_path"] or any(counts[name] < saved["counts"][name] for name in counts):
        raise RuntimeError("Database path or existing record counts changed unexpectedly")
    token = os.getenv("MOBILE_API_TOKEN")
    if not token: raise RuntimeError("Household authentication is not configured")
    req = Request("http://127.0.0.1:" + str(port) + "/api/v2/profiles", headers={"Authorization": "Bearer " + token})
    with urlopen(req, timeout=15) as response:
        profiles = json.loads(response.read())
        if response.status != 200 or len(profiles) != counts["user"]:
            raise RuntimeError("Authenticated profile check failed")
    return dict(integrity="ok", records_preserved=True, authenticated_profiles=True)

if __name__ == "__main__":
    try:
        action = sys.argv[1]
        if action == "backup": result = backup()
        elif action == "model": result = choose_model()
        elif action == "verify": result = verify(sys.argv[2], int(sys.argv[3]))
        else: raise RuntimeError("Unknown guard action")
    except Exception as error:
        # RuntimeError messages above are fixed text, never provider responses or data.
        result = {"guard_error": str(error) if type(error) is RuntimeError else type(error).__name__}
    print(json.dumps(result))
