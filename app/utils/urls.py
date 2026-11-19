"""URL normalisation. The normalised post URL is the deduplication key."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

_URN_RE = re.compile(r"urn:li:(activity|ugcPost|share):(\d{10,25})")
_HOST_RE = re.compile(r"[A-Za-z0-9.-]+(?::\d{1,5})?")
_SLUG_RE = re.compile(r"-(activity|ugcPost|share)-(\d{10,25})(?:-|/|\?|#|$)")


def extract_post_ref(url: str) -> tuple[str, int] | None:
    """Return (kind, numeric id) if the URL carries a LinkedIn post URN."""
    for pattern in (_URN_RE, _SLUG_RE):
        m = pattern.search(url or "")
        if m:
            return m.group(1), int(m.group(2))
    return None


def normalize_post_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("empty post URL")
    ref = extract_post_ref(url)
    if ref:
        kind, post_id = ref
        return f"https://www.linkedin.com/feed/update/urn:li:{kind}:{post_id}/"
    parts = urlsplit(url if "://" in url else f"https://{url}")
    if parts.scheme not in ("http", "https") or not _HOST_RE.fullmatch(parts.netloc):
        raise ValueError(f"unsupported post URL: {url[:80]!r}")
    return f"https://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def normalize_profile_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"https://{parts.netloc.lower()}{parts.path.rstrip('/')}"
