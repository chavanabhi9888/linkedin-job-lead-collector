"""E-mail and phone extraction from *publicly visible* post text.

We only report what is literally written in the post. We never guess, derive
or enrich contact details (no "firstname.lastname@" patterns, no lookups).
"""
from __future__ import annotations

import re
import unicodedata

import phonenumbers

# ------------------------------------------------------------------ e-mail
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]{1,64}@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}"
    r"(?![A-Za-z0-9-])"
)
_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
# Only bracketed obfuscations ("name [at] corp (dot) com"); plain words are too ambiguous.
_AT_RE = re.compile(r"\s*[\[\(\{<]\s*at\s*[\]\)\}>]\s*", re.I)
_DOT_RE = re.compile(r"\s*[\[\(\{<]\s*dot\s*[\]\)\}>]\s*", re.I)

_PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "test.com", "domain.com",
    "email.com", "yourcompany.com", "company.com", "mail.com.example",
}
_FILE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico", "pdf", "css", "js"}
_NOREPLY_RE = re.compile(r"^(?:no[-_.]?reply|do[-_.]?not[-_.]?reply)$", re.I)


def _normalize(text: str) -> str:
    return _ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", text or ""))


def validate_email(candidate: str) -> str | None:
    """Return the canonical (lower-case) address, or None if it fails validation."""
    email = candidate.strip().strip(".,;:<>()[]\"'").lower()
    if len(email) > 254 or email.count("@") != 1 or ".." in email:
        return None
    local, domain = email.split("@")
    if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
        return None
    if domain in _PLACEHOLDER_DOMAINS or _NOREPLY_RE.match(local):
        return None
    tld = domain.rsplit(".", 1)[-1]
    if not tld.isalpha() or tld in _FILE_EXTENSIONS:
        return None
    return email


def extract_emails(text: str) -> list[str]:
    normalized = _DOT_RE.sub(".", _AT_RE.sub("@", _normalize(text)))
    found: list[str] = []
    for match in EMAIL_RE.finditer(normalized):
        email = validate_email(match.group(0))
        if email and email not in found:
            found.append(email)
    return found


# ------------------------------------------------------------------ phone
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
# A number counts as "shared for contact" only with an explicit "+" prefix or a
# nearby contact cue. This avoids picking up IDs, salaries and reference numbers.
_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"call|whats\s?app|contact|reach|phone|mobile|mob|ph|tel|dm|text|number|no|"
    r"share|send|ping|connect|apply|resume|cv|drop|wp|wa"
    r")\b|[\U0001F4DE\U0001F4F1\u260E\u2706]",
    re.I,
)
_CTX_BEFORE, _CTX_AFTER = 40, 15


def extract_phones(text: str, region: str = "IN") -> list[str]:
    """Return valid phone numbers in E.164 format, in order of appearance."""
    cleaned = _EMAIL_STRIP.sub(" ", _URL_RE.sub(" ", _normalize(text)))
    found: list[str] = []
    matcher = phonenumbers.PhoneNumberMatcher(cleaned, region, leniency=phonenumbers.Leniency.VALID)
    for m in matcher:
        has_plus = m.raw_string.lstrip().startswith("+")
        before = cleaned[max(0, m.start - _CTX_BEFORE): m.start]
        after = cleaned[m.end: m.end + _CTX_AFTER]
        if not (has_plus or _CONTEXT_RE.search(before) or _CONTEXT_RE.search(after)):
            continue
        e164 = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164)
        if e164 not in found:
            found.append(e164)
    return found


# Emails are removed before phone matching so digits inside an address are not read as a phone.
_EMAIL_STRIP = re.compile(EMAIL_RE.pattern)
