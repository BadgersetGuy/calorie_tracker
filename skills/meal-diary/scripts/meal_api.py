#!/usr/bin/env python3
"""Small REST skill client. Secrets stay in environment variables."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler, HTTPSHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    parser.add_argument("path")
    parser.add_argument("--data", help="JSON request file, or - for standard input")
    parser.add_argument("--photo", help="Real meal photo to encode and attach")
    parser.add_argument("--output", help="Write response bytes to a local file")
    args = parser.parse_args()
    base = os.environ.get("MEAL_API_URL", "").rstrip("/")
    token = os.environ.get("MEAL_API_TOKEN", "")
    url = urlsplit(base)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.path or url.query or url.fragment or not token:
        parser.error("Configure an HTTPS origin in MEAL_API_URL and the household MEAL_API_TOKEN")
    if not args.path.startswith("/api/v2/") or ".." in args.path:
        parser.error("Use a relative /api/v2/ path")
    payload = None
    if args.data:
        payload = json.loads(sys.stdin.read() if args.data == "-" else Path(args.data).read_text())
    if args.photo:
        payload = payload or {}
        raw = Path(args.photo).read_bytes()
        if len(raw) > 10 * 1024 * 1024: parser.error("Photo must be under 10 MB")
        payload["image_data"] = base64.b64encode(raw).decode()
    request = Request(base + args.path, data=json.dumps(payload).encode() if payload is not None else None,
        method=args.method, headers={"Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json"})
    opener = build_opener(ProxyHandler(), HTTPSHandler(), NoRedirect())
    try:
        with opener.open(request, timeout=120) as response:
            raw = response.read()
            if args.output: Path(args.output).write_bytes(raw)
            else: print(raw.decode())
    except HTTPError as error:
        print(json.dumps(dict(status=error.code, response=error.read().decode())), file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__": main()
