"""RawPost -> LeadCreate. Heuristic field extraction, best-effort by design."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from app.domain import SearchCriteria
from app.parsing.contacts import extract_emails, extract_phones
from app.parsing.dates import is_within_window, resolve_post_date
from app.parsing.models import LeadCreate
from app.sources.base import RawPost
from app.utils.urls import normalize_post_url, normalize_profile_url

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 20_000
_LEAD_IN = r"(?:^|\n)\s*[^\w\n]*"   # tolerate emoji / bullets before a label

_ROLE_WORD = r"(?:python|backend|back-end|django|fastapi|flask|full[\s-]?stack|software|data|ml|ai|devops|api)"
_TITLE_RE = re.compile(
    rf"\b((?:(?:senior|sr\.?|lead|junior|jr\.?|associate|principal|staff)\s+)?"
    rf"{_ROLE_WORD}(?:\s*/\s*{_ROLE_WORD})?\s+(?:developer|engineer|programmer|architect))\b",
    re.I,
)
_TITLE_LABEL_RE = re.compile(
    _LEAD_IN + r"(?:role|position|job\s*title|designation|opening|hiring\s+for)\s*[:\-–]\s*([^\n]{3,80})", re.I
)
_COMPANY_LABEL_RE = re.compile(
    _LEAD_IN + r"(?:company(?:\s*name)?|organi[sz]ation|client)\s*[:\-–]\s*([^\n|,;(]{2,60})", re.I
)
_CAP = r"[A-Z][\w&.\-]*"
_COMPANY_AT_RE = re.compile(
    rf"\b(?:hiring|openings?|opportunit(?:y|ies)|vacanc(?:y|ies)|jobs?)\s+(?:at|@|with)\s+({_CAP}(?:\s+{_CAP}){{0,4}})"
)
_COMPANY_IS_RE = re.compile(rf"\b({_CAP}(?:\s+{_CAP}){{0,4}})\s+is\s+(?:hiring|looking|seeking)")
_LOCATION_LABEL_RE = re.compile(_LEAD_IN + r"(?:job\s+)?location\s*[:\-–]\s*([^\n]{2,60})", re.I)

_CITIES = [
    "Pune", "Mumbai", "Bengaluru", "Bangalore", "Hyderabad", "Chennai", "Delhi", "Gurgaon", "Gurugram",
    "Noida", "Kolkata", "Ahmedabad", "Kochi", "Jaipur", "Indore", "Chandigarh", "Remote",
]
_NOT_COMPANIES = {c.lower() for c in _CITIES} | {"india", "we", "our", "the", "python", "us", "hr", "team"}
_STOP_KEYWORD_TOKENS = {"developer", "engineer", "job", "jobs", "hiring"}


def _clean(value: str | None, limit: int = 255) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" \t-–:|,.;")
    return value[:limit] or None

def _format_contact_list(items: list[str], max_chars: int) -> str | None:
    """Safely pack complete items separated by '; ' up to max_chars."""
    if not items:
        return None
    selected = []
    total = 0
    for item in items:
        needed = len(item) if not selected else len(item) + 2  # account for '; '
        if total + needed > max_chars:
            break
        selected.append(item)
        total += needed
    return "; ".join(selected) or None

def extract_job_title(text: str) -> str | None:
    m = _TITLE_LABEL_RE.search(text) or _TITLE_RE.search(text)
    return _clean(m.group(1)) if m else None


def extract_company(text: str) -> str | None:
    for pattern in (_COMPANY_LABEL_RE, _COMPANY_AT_RE, _COMPANY_IS_RE):
        m = pattern.search(text)
        if m:
            company = _clean(m.group(1))
            if company and company.lower() not in _NOT_COMPANIES:
                return company
    return None


def extract_location(text: str, preferred: str | None = None) -> str | None:
    m = _LOCATION_LABEL_RE.search(text)
    if m:
        return _clean(m.group(1))
    candidates = list(_CITIES)
    if preferred:
        candidates = [preferred.split(",")[0].strip()] + candidates
    lowered = text.lower()
    for city in candidates:
        if city and re.search(rf"\b{re.escape(city.lower())}\b", lowered):
            return city.title()
    return None


def matches_keyword(text: str, keyword: str) -> bool:
    tokens = [t for t in re.findall(r"\w+", keyword.lower()) if len(t) >= 3 and t not in _STOP_KEYWORD_TOKENS]
    if not tokens:
        return True
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", lowered) for t in tokens)


def _tidy_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_TEXT_CHARS]


def parse_post(raw: RawPost, criteria: SearchCriteria, now: datetime, *, phone_region: str = "IN") -> LeadCreate | None:
    """Return a lead, or None if the post is irrelevant, out of window or malformed."""
    try:
        post_url = normalize_post_url(raw.post_url)
    except ValueError:
        logger.warning("skipping_post_invalid_url")
        return None

    text = _tidy_text(raw.text or "")
    if not text or not matches_keyword(text, criteria.keyword):
        return None

    post_date = resolve_post_date(post_url, raw.posted_at, raw.posted_label, now)
    if not is_within_window(post_date, criteria.time_filter, now):
        return None

    emails = extract_emails(text)
    phones = extract_phones(text, phone_region)
    return LeadCreate(
        author_name=_clean(raw.author_name),
        profile_url=normalize_profile_url(raw.profile_url),
        company=extract_company(text),
        job_title=extract_job_title(text),
        location=extract_location(text, criteria.location),
        post_url=post_url,
        post_date=post_date,
        email=_format_contact_list(emails, 500),
        phone=_format_contact_list(phones, 250),
        post_text=text,
    )
