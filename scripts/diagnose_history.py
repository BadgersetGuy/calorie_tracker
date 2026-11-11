"""Read-only production diagnostics; emit no credentials or diary contents."""
import json
import os
import subprocess
import shlex
import sys
from datetime import datetime, timedelta, timezone
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

APP = "calorie-tracker-billowing-rain-2129"
ORIGIN = "https://" + APP + ".fly.dev"
TOKEN = os.environ["MOBILE_API_TOKEN"].strip()

def fly(args, as_json=True):
    command = ["flyctl", *args, "--app", APP]
    if as_json: command.append("--json")
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    if result.returncode: raise RuntimeError("Fly metadata read failed")
    return json.loads(result.stdout) if as_json else result.stdout

def oom_count(value):
    if isinstance(value, dict):
        return sum(int(v is True) if k.lower() in ("oom_killed", "oomkilled") else oom_count(v) for k, v in value.items())
    if isinstance(value, list): return sum(oom_count(v) for v in value)
    return 0

if os.getenv("METADATA_ONLY") == "true":
    releases = fly(["releases", "--image"])
    print(json.dumps(dict(check="releases", releases=releases)))

for machine in fly(["machine", "list"]):
    status = fly(["machine", "status", machine["id"]], as_json=False).lower()
    print(json.dumps(dict(check="machine", state=machine["state"], release=machine.get("config", {}).get("env", {}).get("RELEASE_COMMIT"),
        memory_mb=machine.get("config", {}).get("guest", {}).get("memory_mb"),
        recent_oom_event="oom_killed" in status and "true" in status or "out of memory" in status)))

    if machine["state"] != "started": continue
    # Numeric storage metadata only; never publish backup paths or manifests.
    source = """import json, pathlib, shutil
root = pathlib.Path('/data')
space = shutil.disk_usage(root)
files = list((root / 'backups').glob('*'))
processes = {}
for proc in pathlib.Path('/proc').glob('[0-9]*'):
    try:
        args = (proc / 'cmdline').read_bytes().split(bytes([0]))
        kind = (proc / 'comm').read_text().strip()
        if args and any(arg in (b'backup', b'model', b'verify') for arg in args):
            kind = 'deployment_guard'
        status = (proc / 'status').read_text().splitlines()
        rss = next((int(line.split()[1]) for line in status if line.startswith('VmRSS:')), 0)
        entry = processes.setdefault(kind, dict(count=0, rss_kib=0))
        entry['count'] += 1; entry['rss_kib'] += rss
    except (OSError, ValueError): pass
print(json.dumps(dict(total_bytes=space.total, free_bytes=space.free,
    database_bytes=(root / 'meals.db').stat().st_size,
    backup_bytes=sum(p.stat().st_size for p in files if p.is_file()),
    backup_files=sum(p.suffix in ('.db', '.gz') for p in files), processes=processes)))
"""
    storage = fly(["machine", "exec", machine["id"], shlex.join(["python", "-c", source])])
    if storage.get("exit_code", 0): raise RuntimeError("Storage metadata check failed")
    print(json.dumps(dict(check="storage", **json.loads(storage["stdout"]))))

if os.getenv("METADATA_ONLY") == "true": sys.exit(0)

def get(path, label, decode=False):
    started = time.monotonic()
    try:
        with urlopen(Request(ORIGIN + path, headers={"Authorization": "Bearer " + TOKEN, "X-Meal-Client": "android"}), timeout=60) as response:
            data = response.read(8 * 1024 * 1024)
            code = response.status
    except HTTPError as error:
        code, data = error.code, b""
    except Exception as error:
        print(json.dumps(dict(check=label, failure=type(error).__name__)))
        if os.getenv("CHECK_FULL_HISTORY") == "true":
            raise RuntimeError("History verification request failed") from None
        return None
    print(json.dumps(dict(check=label, status=code, elapsed_ms=round((time.monotonic()-started)*1000), response_bytes=len(data))))
    if os.getenv("CHECK_FULL_HISTORY") == "true" and code != 200:
        raise RuntimeError("History verification did not return success")
    return json.loads(data) if decode and code == 200 else None

profiles = get("/api/v2/profiles", "profiles", True) or []
for profile in profiles:
    prefix = "/api/v2/history?user_id=" + str(profile["id"])
    get(prefix + "&view=summary&limit=30", "history_summary_page")
    get(prefix + "&limit=3", "history_legacy_small_page")
    if os.getenv("CHECK_FULL_HISTORY") == "true":
        get(prefix + "&limit=30", "history_legacy_full_page")
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=29)
        report = get("/api/v2/summaries?user_id=" + str(profile["id"]) + "&start=" + str(start) + "&end=" + str(end), "trend_report_30_days", True)
        if (not report or len(report.get("days", [])) != 30
                or not {"dietary_pattern", "legacy_psoriasis"}.issubset(report.get("score_averages", {}))
                or any(not {"dietary_pattern", "legacy_psoriasis", "totals", "discipline", "body_weights"}.issubset(day) for day in report["days"])):
            raise RuntimeError("Weighted score reporting contract was not confirmed")


# Classify recent worker failures without disclosing raw application logs.
try:
    log = subprocess.run(["flyctl", "logs", "--app", APP, "--no-tail", "--json"], capture_output=True, text=True, timeout=30)
    messages = log.stdout.lower()
    print(json.dumps(dict(check="worker_log_flags", available=log.returncode == 0, oom="out of memory" in messages or "oom-kill" in messages,
        sigkill="sigkill" in messages, worker_timeout="worker timeout" in messages)))
except subprocess.TimeoutExpired:
    print(json.dumps(dict(check="worker_log_flags", available=False)))
