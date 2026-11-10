"""Bounded in-memory display previews; original stored photos remain unchanged."""
import base64
from collections import OrderedDict
import hashlib
import io
import threading

from PIL import Image, ImageOps
import analysis_engine

_cache = OrderedDict()
_lock = threading.Lock()

def photo_bytes(encoded, size="original"):
    if size not in ("original", "thumbnail", "preview"):
        raise ValueError("Photo size must be original, thumbnail or preview")
    if size == "original":
        return base64.b64decode(encoded)
    key = (hashlib.sha256(encoded.encode("ascii")).hexdigest(), size)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    if size == "preview":
        value = base64.b64decode(analysis_engine.normalize_stored_photo(encoded))
    else:
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as original:
            if original.width * original.height > 60_000_000:
                raise ValueError("Photo resolution is too large")
            original.draft("RGB", (192, 192))
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((192, 192), Image.Resampling.LANCZOS)
            image.info.clear()
            output = io.BytesIO()
            image.save(output, "JPEG", quality=65, optimize=True)
            value = output.getvalue()
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > 128:
            _cache.popitem(last=False)
    return value
