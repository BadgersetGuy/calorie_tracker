"""Photos from REST clients or short-lived GPT Action attachment references."""
import base64
from urllib.parse import urlsplit

import requests
from flask import request
import analysis_engine as engine

MAX_BYTES = 10 * 1024 * 1024

def photo_from_request(data):
    encoded = data.get("image_data")
    file = request.files.get("meal_photo")
    refs = data.get("openaiFileIdRefs") or []
    if sum(bool(x) for x in (encoded, file, refs)) > 1:
        raise ValueError("Send one photo source: base64, multipart meal_photo, or a GPT file reference")
    if encoded:
        return engine.normalize_photo(encoded)
    if file:
        raw = file.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Photo must be under 10 MB")
        return engine.normalize_photo(base64.b64encode(raw).decode())
    if not refs:
        return None
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
        raise ValueError("Attach exactly one meal photo; GPT Action file references must include a download_link")
    link = refs[0].get("download_link", "")
    try:
        url = urlsplit(link)
        valid = (url.scheme == "https" and url.hostname == "files.oaiusercontent.com"
                 and url.port in (None, 443) and not url.username and not url.password and not url.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Only HTTPS GPT attachment links on files.oaiusercontent.com are accepted")
    try:
        # Do not forward the household token, follow redirects or persist the signed URL.
        with requests.get(link, stream=True, allow_redirects=False, timeout=(5, 20)) as response:
            if response.status_code != 200:
                raise ValueError("Photo link expired or could not be downloaded. Reattach the photo and retry.")
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Photo must be under 10 MB")
    except requests.RequestException:
        raise ValueError("Photo attachment could not be downloaded. Reattach it and retry.") from None
    return engine.normalize_photo(base64.b64encode(raw).decode())
