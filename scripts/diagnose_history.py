"""Read-only production diagnostics; emit no credentials or diary contents."""
import json
import os
import subprocess
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

for machine in fly(["machine", "list"]):
    status = fly(["machine", "status", machine["id"]], as_json=False).lower()
    print(json.dumps(dict(check="machine", state=machine["state"],
        memory_mb=machine.get("config", {}).get("guest", {}).get("memory_mb"),
        recent_oom_event="oom_killed" in status and "true" in status or "out of memory" in status)))

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
        return None
    print(json.dumps(dict(check=label, status=code, elapsed_ms=round((time.monotonic()-started)*1000), response_bytes=len(data))))
    return json.loads(data) if decode and code == 200 else None

profiles = get("/api/v2/profiles", "profiles", True) or []
for profile in profiles:
    prefix = "/api/v2/history?user_id=" + str(profile["id"])
    get(prefix + "&view=summary&limit=30", "history_summary_page")
    get(prefix + "&limit=3", "history_legacy_small_page")
    if os.getenv("CHECK_FULL_HISTORY") == "true":
        get(prefix + "&limit=30", "history_legacy_full_page")

# Classify recent worker failures without disclosing raw application logs.
try:
    log = subprocess.run(["flyctl", "logs", "--app", APP, "--no-tail", "--json"], capture_output=True, text=True, timeout=30)
    messages = log.stdout.lower()
    print(json.dumps(dict(check="worker_log_flags", available=log.returncode == 0, oom="out of memory" in messages or "oom-kill" in messages,
        sigkill="sigkill" in messages, worker_timeout="worker timeout" in messages)))
except subprocess.TimeoutExpired:
    print(json.dumps(dict(check="worker_log_flags", available=False)))
