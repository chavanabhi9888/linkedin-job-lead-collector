from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.exporters.common import leads_to_dataframe, summarize

_POST_TEXT_LIMIT = 500


def _txt(value: Any, limit: int | None = None) -> str:
    """Escape for reportlab markup. Built-in fonts are Latin-1 only, so drop other glyphs (emoji etc.)."""
    if value is None or value == "":
        return "-"
    text = str(value)
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "..."
    text = text.encode("latin-1", "ignore").decode("latin-1")
    return escape(text).replace("\n", "<br/>")


def _link(url: Any) -> str:
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        safe = escape(url, {'"': "&quot;"})
        return f'<a href="{safe}" color="blue">{_txt(url)}</a>'
    return _txt(url)


def build_leads_pdf(leads: Iterable[Any], *, max_leads: int = 500) -> bytes:
    df = leads_to_dataframe(leads)
    summary = summarize(df)
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=8, leading=10)
    label = ParagraphStyle("label", parent=cell, fontName="Helvetica-Bold")

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title="LinkedIn Job Lead Report",
    )
    story: list = [
        Paragraph("LinkedIn Job Lead Report", styles["Title"]),
        Paragraph(f"Generated {summary.generated_at:%Y-%m-%d %H:%M} UTC", styles["Normal"]),
        Spacer(1, 0.5 * cm),
    ]
    summary_table = Table(
        [
            ["Total posts found", summary.total_posts],
            ["Unique leads (distinct contacts)", summary.unique_leads],
            ["Emails (distinct)", summary.emails],
            ["Phone numbers (distinct)", summary.phones],
        ],
        colWidths=[8 * cm, 4 * cm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ]
        )
    )
    story += [summary_table, Spacer(1, 0.6 * cm), Paragraph("Lead details", styles["Heading2"])]

    records = df.to_dict("records")
    for rec in records[:max_leads]:
        rows = [
            ("Author", _txt(rec["author_name"])),
            ("Profile", _link(rec["profile_url"])),
            ("Company", _txt(rec["company"])),
            ("Job title", _txt(rec["job_title"])),
            ("Location", _txt(rec["location"])),
            ("Post date (UTC)", _txt(rec["post_date"].strftime("%Y-%m-%d %H:%M") if rec["post_date"] else None)),
            ("Email", _txt(rec["email"])),
            ("Phone", _txt(rec["phone"])),
            ("Post URL", _link(rec["post_url"])),
            ("Post text", _txt(rec["post_text"], _POST_TEXT_LIMIT)),
        ]
        table = Table(
            [[Paragraph(k, label), Paragraph(v, cell)] for k, v in rows], colWidths=[3 * cm, 14 * cm]
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ]
            )
        )
        story += [KeepTogether([table]), Spacer(1, 0.35 * cm)]
    if len(records) > max_leads:
        story.append(Paragraph(f"Showing the first {max_leads} of {len(records)} leads. Use the Excel export for all.", cell))
    if not records:
        story.append(Paragraph("No leads match the selected filters.", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()
