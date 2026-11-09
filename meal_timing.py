"""Personal meal-time goal; no medical interpretation or model-generated values."""
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION = "discipline-18h-1.0"

def zone(name=None):
    name = name or os.getenv("HOUSEHOLD_TIMEZONE", "Europe/Bucharest")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError("Choose a valid timezone") from None

def local_time(utc_date, name=None):
    return utc_date.replace(tzinfo=timezone.utc).astimezone(zone(name))

def confirmed_time(timestamp, name=None):
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Eating time must include a timezone offset") from None
    local = parsed.astimezone(zone(name))
    if local.utcoffset() != parsed.utcoffset():
        raise ValueError("Eating time offset does not match the selected timezone")
    return local

def score(local, inferred=False):
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    late = max(0, seconds - 18 * 3600)
    return dict(value=max(0, 10 - math.ceil(late / 1800)), version=VERSION,
        label="Discipline", cutoff="18:00", local_eaten_at=local.isoformat(),
        timezone=str(local.tzinfo), inferred=inferred,
        explanation="Your personal timing goal: 10 through 18:00, then minus one point per started "
                    "30-minute interval, minimum 0. This is separate from food quality and medical risk."
                    + (" Older meal: time inferred from its saved timestamp in the household timezone." if inferred else ""))
