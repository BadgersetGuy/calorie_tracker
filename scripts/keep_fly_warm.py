"""Change only the existing Machine's idle policy; retain its image and data volume."""
import time
if __package__:
    from .deploy_fly import run, machines, primary
else:
    from deploy_fly import run, machines, primary


def same_image(before, after):
    left = before.get("image_ref", {}).get("digest")
    right = after.get("image_ref", {}).get("digest")
    if left and right: return left == right
    return before["config"]["image"] == after["config"]["image"]

def main():
    before, volume = primary(machines())
    image = before["config"]["image"]
    run(["machine", "update", before["id"], "--image", image, "--autostop=off", "--autostart", "--yes"])
    after, current_volume = primary(machines())
    print("Data volume preserved: " + str(current_volume == volume), flush=True)
    print("Image content preserved: " + str(same_image(before, after)), flush=True)
    if current_volume != volume or not same_image(before, after):
        raise RuntimeError("The existing image and volume must be preserved")
    if after["state"] != "started": run(["machine", "start", after["id"]])
    for _ in range(30):
        after, _ = primary(machines())
        if after["state"] == "started": break
        time.sleep(2)
    else: raise RuntimeError("The single Machine did not start")
    services = after["config"].get("services", [])
    if not services or any(s.get("autostop") not in ("off", False, None, "") for s in services):
        raise RuntimeError("Always-warm service policy was not confirmed")
    print("Always-warm policy verified: one running Machine, idle stop disabled, original image and data volume retained")

if __name__ == "__main__": main()
