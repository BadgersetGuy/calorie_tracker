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
    if size not in ("original", "thumbnail", "preview", "list"):
        raise ValueError("Photo size must be original, thumbnail or preview")
    if size == "original":
        return base64.b64decode(encoded)
    digest = hashlib.sha256()
    for offset in range(0, len(encoded), 1024 * 1024): digest.update(encoded[offset:offset + 1024 * 1024].encode("ascii"))
    key = (digest.hexdigest(), size)
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
            edge = 640 if size == "list" else 192
            original.draft("RGB", (edge, edge))
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            image.info.clear()
            while True:
                for quality in (65, 55, 45):
                    output = io.BytesIO()
                    image.save(output, "JPEG", quality=quality, optimize=True)
                    value = output.getvalue()
                    if len(value) <= 48 * 1024: break
                if len(value) <= 48 * 1024: break
                image.thumbnail((max(1, int(image.width * .8)), max(1, int(image.height * .8))), Image.Resampling.LANCZOS)
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > 128:
            _cache.popitem(last=False)
    return value
