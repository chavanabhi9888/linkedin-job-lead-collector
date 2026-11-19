from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.exporters.common import LEAD_COLUMNS, leads_to_dataframe, summarize

_EXCEL_CELL_LIMIT = 32_000
_LINK_FIELDS = {"profile_url", "post_url"}


def _set(cell, value: Any) -> None:
    """Write a value safely: strip illegal XML chars, cap length, never create formulas."""
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)[:_EXCEL_CELL_LIMIT]
    cell.value = value
    if cell.data_type == "f":  # scraped text starting with "=" must stay text
        cell.data_type = "s"


def build_leads_workbook(leads: Iterable[Any]) -> bytes:
    df = leads_to_dataframe(leads)
    summary = summarize(df)

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for col_idx, (_, header, width) in enumerate(LEAD_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row_idx, record in enumerate(df.to_dict("records"), start=2):
        for col_idx, (attr, _, _) in enumerate(LEAD_COLUMNS, start=1):
            value = record[attr]
            cell = ws.cell(row=row_idx, column=col_idx)
            _set(cell, value)
            if attr in {"post_date", "collected_at"} and value is not None:
                cell.number_format = "yyyy-mm-dd hh:mm"
            if attr in _LINK_FIELDS and isinstance(value, str) and value.startswith(("http://", "https://")):
                cell.hyperlink = value
                cell.font = Font(color="0563C1", underline="single")
            if attr == "post_text":
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            else:
                cell.alignment = Alignment(vertical="top")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(LEAD_COLUMNS))}{max(ws.max_row, 1)}"

    sm = wb.create_sheet("Summary")
    rows = [
        ("Total posts found", summary.total_posts),
        ("Unique leads (distinct contacts)", summary.unique_leads),
        ("Emails (distinct)", summary.emails),
        ("Phone numbers (distinct)", summary.phones),
        ("Generated at (UTC)", summary.generated_at.strftime("%Y-%m-%d %H:%M")),
    ]
    for r, (label, value) in enumerate(rows, start=1):
        sm.cell(row=r, column=1, value=label).font = Font(bold=True)
        sm.cell(row=r, column=2, value=value)
    sm.column_dimensions["A"].width = 36
    sm.column_dimensions["B"].width = 20

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
