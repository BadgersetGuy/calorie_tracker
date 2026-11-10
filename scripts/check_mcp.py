"""Verify interoperability with the official MCP client without writing diary data."""
import argparse
import asyncio
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]

async def check(origin, token):
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=45) as http:
        async with streamable_http_client(origin.rstrip("/") + "/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=45) as session:
                init = await session.initialize()
                discovered = await session.list_tools()
                if len(discovered.tools) != 30: raise RuntimeError("Unexpected diary tool count")
                response = await session.call_tool("mobile_profiles", {})
                payload = json.loads(response.content[0].text)
                if response.is_error or payload.get("status") != 200:
                    raise RuntimeError("Authenticated profile discovery failed")
                print(json.dumps(dict(mcp_protocol=init.protocol_version, tools=len(discovered.tools), authenticated_profiles=True)))

@contextmanager
def local_server(python):
    with tempfile.TemporaryDirectory(prefix="mcp-check-") as folder:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        token = secrets.token_urlsafe(32)
        env = dict(os.environ, DATABASE_URL="sqlite:///" + folder + "/check.db", MOBILE_API_TOKEN=token)
        with open(Path(folder) / "server.log", "w") as log:
            process = subprocess.Popen([python, "-m", "gunicorn", "--bind", f"127.0.0.1:{port}", "--workers", "1", "app:app"],
                cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                origin = f"http://127.0.0.1:{port}"
                for _ in range(60):
                    try:
                        with urlopen(origin + "/health", timeout=1): break
                    except Exception:
                        if process.poll() is not None: raise RuntimeError("Local test server did not start")
                        time.sleep(.1)
                else: raise RuntimeError("Local server startup timed out")
                yield origin, token
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--server-python", default=sys.executable)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.local:
        with local_server(args.server_python) as (origin, token): asyncio.run(check(origin, token))
    else:
        origin = os.environ["MEAL_API_URL"]
        if not origin.startswith("https://"): raise RuntimeError("Remote MCP verification requires HTTPS")
        asyncio.run(check(origin, os.environ["MOBILE_API_TOKEN"]))
