"""Explicit, dry-run-first maintenance for old stored photos; no nutrition changes."""
from sqlalchemy import select, update
from analysis_engine import normalize_stored_photo

def compress_existing_photos(db, apply=False):
    result = dict(dry_run=not apply, checked=0, candidates=0, updated=0, skipped_invalid=0,
                  conflicts=0, stored_bytes_before=0, candidate_bytes_saved=0)
    # Core updates deliberately avoid generating fictitious nutritional edit events.
    with db.engine.begin() as connection:
        for name, field in (("meal", "image_data"), ("mobile_analysis_draft", "photo")):
            table = db.metadata.tables[name]
            for row in connection.execute(select(table.c.id, table.c[field]).where(table.c[field].is_not(None))):
                identifier, original = row
                if not original: continue
                result["checked"] += 1
                result["stored_bytes_before"] += len(original.encode())
                try:
                    compressed = normalize_stored_photo(original)
                except ValueError:
                    result["skipped_invalid"] += 1
                    continue
                saved = len(original.encode()) - len(compressed.encode())
                if saved <= 0: continue
                result["candidates"] += 1
                result["candidate_bytes_saved"] += saved
                if apply:
                    changed = connection.execute(update(table).where(table.c.id == identifier,
                        table.c[field] == original).values({field: compressed}))
                    if changed.rowcount == 1: result["updated"] += 1
                    else: result["conflicts"] += 1
    return result
