from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

# (attribute, header, excel column width)
LEAD_COLUMNS: list[tuple[str, str, int]] = [
    ("id", "ID", 8),
    ("author_name", "Author Name", 26),
    ("profile_url", "Profile URL", 40),
    ("company", "Company", 26),
    ("job_title", "Job Title", 28),
    ("location", "Location", 18),
    ("post_url", "Post URL", 44),
    ("post_date", "Post Date (UTC)", 20),
    ("email", "Email", 32),
    ("phone", "Phone", 20),
    ("post_text", "Post Text", 80),
    ("collected_at", "Collected At (UTC)", 20),
]
_DATETIME_FIELDS = {"post_date", "collected_at"}


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def leads_to_records(leads: Iterable[Any]) -> list[dict[str, Any]]:
    records = []
    for lead in leads:
        row = {}
        for attr, _, _ in LEAD_COLUMNS:
            value = getattr(lead, attr)
            row[attr] = _to_naive_utc(value) if attr in _DATETIME_FIELDS else value
        records.append(row)
    return records


def leads_to_dataframe(leads: Iterable[Any]) -> pd.DataFrame:
    return pd.DataFrame(leads_to_records(leads), columns=[c[0] for c in LEAD_COLUMNS], dtype=object)


@dataclass(frozen=True)
class LeadSummary:
    total_posts: int
    unique_leads: int   # distinct contact identities (first e-mail, else first phone)
    emails: int         # distinct e-mail addresses
    phones: int         # distinct phone numbers
    generated_at: datetime


def _split(value: Any) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def summarize(df: pd.DataFrame) -> LeadSummary:
    emails: set[str] = set()
    phones: set[str] = set()
    identities: set[str] = set()
    for email_cell, phone_cell in zip(df["email"], df["phone"]):
        row_emails, row_phones = _split(email_cell), _split(phone_cell)
        emails.update(row_emails)
        phones.update(row_phones)
        if row_emails:
            identities.add(row_emails[0].lower())
        elif row_phones:
            identities.add(row_phones[0])
    return LeadSummary(
        total_posts=len(df),
        unique_leads=len(identities),
        emails=len(emails),
        phones=len(phones),
        generated_at=datetime.now(timezone.utc),
    )
