"""Export without touching a production database or requiring runtime secrets."""
import os
from pathlib import Path
import sys
import tempfile
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as directory:
    os.environ["DATABASE_URL"] = "sqlite:///" + directory + "/contract.db"
    from app import app
    from api_contract import build_openapi
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/openapi.json")
    destination.write_text(json.dumps(build_openapi(app), indent=2) + "\n")
    print(destination)
