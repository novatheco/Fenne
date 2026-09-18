import re

DURATION_RE = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> int | None:
    """Parses strings like '1h30m', '2d', '45m' into a number of seconds."""
    text = text.strip().lower()
    matches = DURATION_RE.findall(text)
    if not matches:
        return None
    total = 0
    for amount, unit in matches:
        total += int(amount) * UNIT_SECONDS[unit]
    return total if total > 0 else None


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d, seconds = divmod(seconds, 86400)
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if not parts:
        parts.append(f"{s}s")
    return " ".join(parts)
