"""Runs on the existing Fly Machine. Output is captured privately by the deploy runner."""
import base64
from datetime import datetime, timezone
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
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

def file_digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): checksum.update(chunk)
    return checksum.hexdigest()

def logical_digest(path):
    """Hash a locked SQLite snapshot with bounded memory, excluding backup counters."""
    checksum = hashlib.sha256()
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=30) as connection:
        connection.execute("BEGIN")
        connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        if connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
            # A WAL snapshot may contain pages not yet in the main database file.
            for statement in connection.iterdump():
                checksum.update(statement.encode("utf-8")); checksum.update(b"\n")
        else:
            with Path(path).open("rb") as stream:
                header = bytearray(stream.read(1024 * 1024))
                # Backup updates change/schema/version-valid counters. Actual schema
                # definitions and all row pages remain part of the digest.
                header[24:28] = b"\0" * 4
                header[40:44] = b"\0" * 4
                header[92:96] = b"\0" * 4
                checksum.update(header)
                for chunk in iter(lambda: stream.read(1024 * 1024), b""): checksum.update(chunk)
    return checksum.hexdigest()

def schema_digest(path):
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=30) as connection:
        rows = connection.execute("SELECT name, type, sql FROM sqlite_master ORDER BY name").fetchall()
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()

def gzip_digest(path):
    checksum = hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): checksum.update(chunk)
    return checksum.hexdigest()

def gzip_copy(source, target):
    with open(source, "rb") as incoming, gzip.open(target, "wb", compresslevel=3) as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    os.chmod(target, 0o600)

def write_manifest(path, data):
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(data)); temporary.chmod(0o600)
    os.replace(temporary, path)

def compress_old_backup(manifest, folder, scratch, root):
    saved = json.loads(manifest.read_text())
    original = Path(saved["backup_path"])
    if (saved.get("compression") or original.resolve().parent != folder.resolve()
            or not original.is_file() or file_digest(original) != saved["sha256"]): return
    compressed = scratch / (original.name + ".gz")
    gzip_copy(original, compressed)
    if gzip_digest(compressed) != saved["sha256"]:
        raise RuntimeError("Compressed backup verification failed")
    target = folder / compressed.name
    if shutil.disk_usage(root).free + original.stat().st_size < compressed.stat().st_size + 64 * 1024 * 1024:
        raise RuntimeError("Not enough volume space to retain the compressed backup")
    removed = False
    try:
        # A verified copy is retained in scratch and other restore points stay on the
        # volume. Recover the original if the final copy cannot be completed.
        original.unlink(); removed = True
        shutil.copyfile(compressed, target); target.chmod(0o600)
        if file_digest(target) != file_digest(compressed):
            raise RuntimeError("Stored compressed backup verification failed")
        saved.update(backup_path=str(target), compression="gzip", archive_sha256=file_digest(target))
        write_manifest(manifest, saved)
    except Exception:
        target.unlink(missing_ok=True)
        if removed:
            with gzip.open(compressed, "rb") as incoming, original.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            original.chmod(0o600)
        raise
    finally:
        compressed.unlink(missing_ok=True)

def consolidate_identical_backups(folder):
    """Share verified identical backup bytes; retain every dated manifest."""
    groups = {}
    manifests = sorted(folder.glob("before-android-*.json"))
    for manifest in manifests:
        try:
            saved = json.loads(manifest.read_text())
            path = Path(saved["backup_path"])
            if path.resolve().parent != folder.resolve() or not path.is_file(): continue
            groups.setdefault((saved["source_path"], saved["sha256"]), []).append((manifest, saved, path))
        except (OSError, ValueError, KeyError): continue
    for (_, checksum), entries in groups.items():
        archives = [entry for entry in entries if entry[1].get("compression") == "gzip"]
        if not archives: continue
        canonical_manifest, canonical, target = archives[0]
        try:
            archive_hash = file_digest(target)
            if archive_hash != canonical.get("archive_sha256") or gzip_digest(target) != checksum: continue
        except (OSError, EOFError): continue
        for manifest, saved, duplicate in entries:
            if duplicate == target: continue
            try:
                actual = gzip_digest(duplicate) if saved.get("compression") == "gzip" else file_digest(duplicate)
                if actual != checksum: continue
                saved.update(backup_path=str(target), compression="gzip", archive_sha256=archive_hash)
                write_manifest(manifest, saved)
            except (OSError, EOFError): continue
        # Unlink only verified duplicates whose dated manifests now all use the
        # canonical archive. A crash before unlink merely leaves an extra copy.
        referenced = set()
        unreadable = False
        for manifest in manifests:
            try: referenced.add(Path(json.loads(manifest.read_text())["backup_path"]))
            except (OSError, ValueError, KeyError): unreadable = True
        if unreadable: continue
        for _, saved, duplicate in entries:
            if duplicate == target or duplicate in referenced or not duplicate.is_file(): continue
            actual = gzip_digest(duplicate) if duplicate.suffix == ".gz" else file_digest(duplicate)
            if actual == checksum: duplicate.unlink()

def backup(root="/data"):
    path = database_path(root)
    folder = Path(root) / "backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    inspect_database(path)
    current_schema = schema_digest(path)
    # Retries before rollout may already have a byte-verified, identical logical copy.
    # SQLite's backup API changes header counters, so compare all schema/data as well.
    source_digest = None
    for manifest in sorted(folder.glob("before-android-*.json"), reverse=True)[:3]:
        try:
            saved = json.loads(manifest.read_text())
            previous = Path(saved["backup_path"])
            if (saved["source_path"] != str(path) or saved.get("integrity") != "ok"
                    or previous.resolve().parent != folder.resolve() or not previous.is_file()):
                continue
            if saved.get("compression") == "gzip":
                if saved.get("schema_digest") != current_schema or not saved.get("logical_digest"):
                    continue
                if file_digest(previous) != saved["archive_sha256"]: continue
                if source_digest is None: source_digest = logical_digest(path)
                if source_digest == saved["logical_digest"]: return saved
                continue
            if schema_digest(previous) != current_schema or file_digest(previous) != saved["sha256"]: continue
            if source_digest is None: source_digest = logical_digest(path)
            if logical_digest(previous) == source_digest:
                inspect_database(previous)
                return saved
        except (OSError, ValueError, KeyError, sqlite3.Error):
            continue
    consolidate_identical_backups(folder)
    size = path.stat().st_size
    if shutil.disk_usage(root).free < size + 64 * 1024 * 1024:
        return compressed_backup(path, folder, root, size)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    target = folder / ("before-android-" + stamp + ".db")
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=30) as source:
        with sqlite3.connect(target) as destination:
            source.backup(destination, pages=128, sleep=.05)
    os.chmod(target, 0o600)
    counts = inspect_database(target)
    result = dict(backup_path=str(target), sha256=file_digest(target), counts=counts,
                  source_path=str(path), integrity="ok", schema_digest=schema_digest(target))
    manifest = target.with_suffix(".json")
    manifest.write_text(json.dumps(result)); os.chmod(manifest, 0o600)
    return result

def compressed_backup(path, folder, root, size):
    if shutil.disk_usage(tempfile.gettempdir()).free < size * 3 + 64 * 1024 * 1024:
        raise RuntimeError("Not enough private staging space for a verified backup")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    name = "before-android-" + stamp
    with tempfile.TemporaryDirectory(prefix="meal-backup-") as temporary:
        scratch = Path(temporary)
        staged = scratch / (name + ".db")
        with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=30) as source, sqlite3.connect(staged) as destination:
            source.backup(destination, pages=128, sleep=.05)
        staged.chmod(0o600)
        counts = inspect_database(staged)
        checksum = file_digest(staged)
        digest = logical_digest(staged)
        archive = scratch / (name + ".db.gz")
        gzip_copy(staged, archive)
        if gzip_digest(archive) != checksum: raise RuntimeError("Fresh compressed backup failed verification")
        required = archive.stat().st_size + 64 * 1024 * 1024
        if shutil.disk_usage(root).free < required:
            for manifest in sorted(folder.glob("before-android-*.json")):
                compress_old_backup(manifest, folder, scratch, root)
                if shutil.disk_usage(root).free >= required: break
        if shutil.disk_usage(root).free < required:
            raise RuntimeError("Volume remains too full after lossless backup compression")
        target = folder / archive.name
        shutil.copyfile(archive, target); target.chmod(0o600)
        archive_hash = file_digest(archive)
        if file_digest(target) != archive_hash: raise RuntimeError("Stored backup failed verification")
        manifest = folder / (name + ".json")
        result = dict(backup_path=str(target), manifest_path=str(manifest), source_path=str(path),
            sha256=checksum, compression="gzip", archive_sha256=archive_hash, logical_digest=digest,
            schema_digest=schema_digest(staged), counts=counts, integrity="ok")
        write_manifest(manifest, result)
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
                try:
                    code = json.loads(error.read()).get("error", {}).get("code")
                except (ValueError, AttributeError):
                    code = None
                allowed = {"invalid_api_key", "insufficient_quota", "rate_limit_exceeded", "billing_hard_limit_reached"}
                reason = code if code in allowed else "credential_or_quota"
                raise RuntimeError("Provider HTTP " + str(error.code) + ": " + reason) from None
            if error.code not in (400, 403, 404): raise RuntimeError("Provider access check failed") from None
    raise RuntimeError("None of the configured upgraded vision models is accessible")

def verify(manifest, port, root="/data"):
    path = database_path(root)
    saved = json.loads(Path(manifest).read_text())
    counts = inspect_database(path)
    if str(path) != saved["source_path"] or any(counts[name] < saved["counts"][name] for name in counts):
        raise RuntimeError("Database path or existing record counts changed unexpectedly")
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as connection:
        plan = connection.execute("EXPLAIN QUERY PLAN SELECT id FROM meal WHERE user_id=? ORDER BY date DESC, id DESC LIMIT 3", (0,)).fetchall()
        if not any("ix_meal_user_date_id" in row[-1] for row in plan):
            raise RuntimeError("Indexed meal history query plan was not confirmed")
    token = os.getenv("MOBILE_API_TOKEN")
    if not token: raise RuntimeError("Household authentication is not configured")
    req = Request("http://127.0.0.1:" + str(port) + "/api/v2/profiles", headers={"Authorization": "Bearer " + token})
    with urlopen(req, timeout=15) as response:
        profiles = json.loads(response.read())
        if response.status != 200 or len(profiles) != counts["user"]:
            raise RuntimeError("Authenticated profile check failed")
    sys.path.insert(0, "/app")
    import analysis_engine
    analysis = analysis_engine.analyze(dict(text="A 250 ml cappuccino, made with whole cow milk and espresso, no sugar. Use a reasonable density estimate; it was not weighed.",
        weight=None, previous=None, conversation=[]), None)
    if analysis.get("status") not in ("ready", "clarify"):
        raise RuntimeError("Structured meal analysis smoke check failed")
    return dict(integrity="ok", records_preserved=True, authenticated_profiles=True, structured_analysis=True)

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
