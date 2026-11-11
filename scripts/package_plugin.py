"""Validate and package the private plugin. Credentials are never read or included."""
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "plugins/everyday-meals"
manifest = json.loads((source / "plugin.json").read_text())
mcp = json.loads((source / "mcp.json").read_text())
assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
assert manifest["name"] == source.name
assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest["version"])
interface = manifest["extensions"]["com.openai"]["interface"]
assert 0 < len(interface["shortDescription"]) <= 30
assert interface["category"] == "Productivity"
for key in ("logo", "composerIcon"):
    path = (source / interface[key]).resolve()
    assert path.is_relative_to(source.resolve()) and path.is_file()
    svg = ET.parse(path).getroot()
    assert svg.tag.endswith("svg") and int(svg.attrib["width"]) >= 48 and int(svg.attrib["height"]) >= 48
assert mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
server = mcp["mcpServers"]["meal-diary"]
assert server["type"] == "streamable-http"
assert server["url"] == "https://calorie-tracker-billowing-rain-2129.fly.dev/mcp"
assert server["extensions"]["com.openai"]["auth"] == dict(type="api_key", headerScheme="bearer")
for skill in source.glob("skills/*/SKILL.md"):
    text = skill.read_text()
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---", 2)[1])
    assert front["name"] == skill.parent.name and isinstance(front["description"], str) and front["description"].strip()
files = [p for p in source.rglob("*") if p.is_file()]
assert files and all(not p.is_symlink() for p in files)
assert all(p.name not in (".env", ".app.json") and p.suffix not in (".db", ".jks", ".keystore") for p in files)
destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist/everyday-meals-plugin.zip"
destination.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files): archive.write(path, path.relative_to(source.parent))
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert sorted(archive.namelist()) == sorted(str(p.relative_to(source.parent)) for p in files)
print(json.dumps(dict(archive=str(destination), files=len(files), display_name=interface["displayName"])))
