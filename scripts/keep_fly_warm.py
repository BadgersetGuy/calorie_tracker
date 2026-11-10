"""Change only the existing Machine's idle policy; retain its image and data volume."""
import time
from deploy_fly import run, machines, primary

before, volume = primary(machines())
image = before["config"]["image"]
run(["machine", "update", before["id"], "--autostop", "off", "--autostart", "--yes"])
after, current_volume = primary(machines())
if current_volume != volume or after["config"]["image"] != image:
    raise RuntimeError("The existing image and volume must be preserved")
if after["state"] != "started": run(["machine", "start", after["id"]])
for _ in range(30):
    after, _ = primary(machines())
    if after["state"] == "started": break
    time.sleep(2)
else: raise RuntimeError("The single Machine did not start")
services = after["config"].get("services", [])
if not services or any(s.get("autostop") not in ("off", False) for s in services):
    raise RuntimeError("Always-warm service policy was not confirmed")
print("Always-warm policy verified: one running Machine, idle stop disabled, original image and data volume retained")
