"""Deploy the existing single-volume app without exporting data or credentials."""
import base64
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import tomllib
from urllib.request import urlopen
import tomli_w

APP = "calorie-tracker-billowing-rain-2129"
ORIGIN = "https://" + APP + ".fly.dev"
ROOT = Path(__file__).resolve().parents[1]

def run(args, *, stdin=None, timeout=1800):
    result = subprocess.run(["flyctl", *args, "--app", APP], input=stdin, text=True,
        capture_output=True, timeout=timeout, cwd=ROOT)
    if result.returncode:
        # Never dump a full config, remote output or HTTP request into public CI logs.
        error = result.stderr
        for name in ("FLY_API_TOKEN", "MOBILE_API_TOKEN"):
            if os.getenv(name): error = error.replace(os.environ[name], "[redacted]")
        raise RuntimeError("Fly command failed: " + " ".join(args[:2]) + "; " + error[-1200:])
    return result.stdout

def machines():
    return json.loads(run(["machine", "list", "--json"]))

def primary(items):
    if len(items) != 1:
        raise RuntimeError("Expected one existing Machine; refusing an unreviewed multi-Machine SQLite deployment")
    machine = items[0]
    mounts = machine.get("config", {}).get("mounts", [])
    selected = [m for m in mounts if m.get("path") == "/data" and m.get("volume")]
    if len(selected) != 1:
        raise RuntimeError("Expected the existing /data volume; refusing to deploy without it")
    return machine, selected[0]["volume"]

def remote(machine_id, *args):
    source = (ROOT / "scripts/fly_sqlite_guard.py").read_bytes()
    expression = "exec(__import__('base64').b64decode('" + base64.b64encode(source).decode() + "'))"
    command = shlex.join(["python", "-c", expression, *args])
    response = json.loads(run(["machine", "exec", machine_id, command, "--timeout", "600", "--json"], timeout=660))
    if response.get("exit_code", 0) != 0:
        raise RuntimeError("Remote database/provider check failed; private remote output was not published")
    result = json.loads(response["stdout"])
    if result.get("guard_error"):
        raise RuntimeError("Remote guard: " + result["guard_error"])
    return result

def configuration(original, sha, model):
    config = copy.deepcopy(original)
    if config.get("app") != APP: raise RuntimeError("Saved Fly configuration targets a different app")
    ports = {int(s["internal_port"]) for s in config.get("services", []) if "internal_port" in s}
    if "http_service" in config: ports.add(int(config["http_service"]["internal_port"]))
    if len(ports) != 1: raise RuntimeError("Expected one application HTTP port")
    port = ports.pop()
    mounts = config.get("mounts", [])
    if isinstance(mounts, dict): mounts = [mounts]
    if not any(m.get("destination") == "/data" and m.get("source") for m in mounts):
        raise RuntimeError("Saved configuration does not preserve the data mount")
    groups = list(config.get("processes", {})) or ["app"]
    if len(groups) != 1: raise RuntimeError("Multiple process groups need a reviewed deployment plan")
    config["processes"] = {groups[0]: f"gunicorn --bind 0.0.0.0:{port} --workers 2 --timeout 150 app:app"}
    config["env"] = dict(config.get("env", {}), PORT=str(port), RELEASE_COMMIT=sha,
        HOUSEHOLD_TIMEZONE=config.get("env", {}).get("HOUSEHOLD_TIMEZONE", "Europe/Bucharest"),
        MEAL_ANALYSIS_MODEL=model, PUBLIC_API_URL=ORIGIN)
    config["build"] = {"dockerfile": "Dockerfile"}
    config.setdefault("deploy", {}).pop("release_command", None)
    return config, port

def main():
    if not os.getenv("FLY_API_TOKEN"): raise RuntimeError("FLY_API_TOKEN is required")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    machine, volume = primary(machines())
    if machine["state"] != "started":
        run(["machine", "start", machine["id"]])
        for _ in range(30):
            machine, _ = primary(machines())
            if machine["state"] == "started": break
            time.sleep(2)
        else: raise RuntimeError("Existing Machine did not start")
    print("Existing Machine and persistent data mount verified", flush=True)
    model = remote(machine["id"], "model")["model"]
    print("Provider vision access verified for " + model, flush=True)
    backup = remote(machine["id"], "backup")
    if backup.get("integrity") != "ok": raise RuntimeError("Backup integrity was not confirmed")
    print("Private SQLite backup confirmed and verified on the Fly volume", flush=True)
    run(["volumes", "snapshots", "create", volume])
    print("Additional Fly volume snapshot requested", flush=True)
    with tempfile.TemporaryDirectory(prefix="fly-deploy-") as folder:
        folder = Path(folder)
        old = folder / "previous.toml"
        old.write_text('app = "' + APP + '"\n')
        old.chmod(0o600)
        run(["config", "save", "--config", str(old), "--yes"])
        original = tomllib.loads(old.read_text())
        config, port = configuration(original, sha, model)
        updated = folder / "updated.toml"
        updated.write_text(tomli_w.dumps(config)); updated.chmod(0o600)
        names = {s.get("Name", s.get("name")) for s in json.loads(run(["secrets", "list", "--json"]))}
        if "MOBILE_API_TOKEN" not in names:
            token = os.getenv("MOBILE_API_TOKEN") or os.environ["FLY_API_TOKEN"]
            # Owner explicitly requested reuse of the deployment token for initial login.
            run(["secrets", "import", "--stage"], stdin="MOBILE_API_TOKEN=" + token.strip() + "\n")
        previous_image = machine["config"]["image"]
        try:
            print("Building and deploying the reviewed backend; a brief restart is expected", flush=True)
            run(["deploy", "--config", str(updated), "--dockerfile", str(ROOT / "Dockerfile"),
                "--local-only", "--ha=false", "--strategy", "immediate", "--wait-timeout", "300", "--yes"], timeout=1500)
            after, after_volume = primary(machines())
            if after_volume != volume: raise RuntimeError("Data volume identity changed")
            for _ in range(30):
                try:
                    with urlopen(ORIGIN + "/health", timeout=15) as response:
                        health = json.loads(response.read())
                    if health.get("release") == sha and health.get("status") == "ok": break
                except Exception: pass
                time.sleep(2)
            else: raise RuntimeError("Public health did not confirm the deployed revision")
            verification = remote(after["id"], "verify", backup["backup_path"].rsplit(".", 1)[0] + ".json", str(port))
            if not verification.get("records_preserved"): raise RuntimeError("Record preservation was not confirmed")
        except Exception:
            print("Deployment verification failed; restoring the previous application image without restoring/overwriting data", flush=True)
            run(["deploy", "--config", str(old), "--image", previous_image,
                "--ha=false", "--strategy", "immediate", "--wait-timeout", "300", "--yes"], timeout=600)
            raise
    print("Deployment verified: health, original data volume, database integrity, preserved records and authenticated profiles", flush=True)

if __name__ == "__main__": main()
