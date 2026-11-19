from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook

from app.exporters.common import LEAD_COLUMNS
from app.exporters.excel import build_leads_workbook
from tests.conftest import NOW


def _lead(i, **kw):
    base = dict(
        id=i, author_name="Asha", profile_url="https://www.linkedin.com/in/asha", company="Acme",
        job_title="Python Developer", location="Pune", post_url=f"https://www.linkedin.com/feed/update/urn:li:activity:{i}/",
        post_date=NOW, email="jobs@acme.io", phone="+919876543210", post_text="hello", collected_at=NOW,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _load(data):
    return load_workbook(BytesIO(data))


def test_headers_rows_and_summary():
    wb = _load(build_leads_workbook([_lead(1), _lead(2, email=None, phone=None)]))
    ws = wb["Leads"]
    assert [c.value for c in ws[1]] == [h for _, h, _ in LEAD_COLUMNS]
    assert ws.max_row == 3
    assert ws["I2"].value == "jobs@acme.io" and ws["J2"].value == "+919876543210"
    assert ws["I3"].value is None
    assert ws.freeze_panes == "A2"
    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows()}
    assert summary["Total posts found"] == 2
    assert summary["Unique leads (distinct contacts)"] == 1
    assert summary["Emails (distinct)"] == 1


def test_hyperlinks_only_for_http_urls():
    wb = _load(build_leads_workbook([_lead(1, profile_url="javascript:alert(1)")]))
    ws = wb["Leads"]
    assert ws["G2"].hyperlink is not None
    assert ws["C2"].hyperlink is None


def test_formula_injection_and_illegal_chars_are_neutralised():
    wb = _load(build_leads_workbook([_lead(1, post_text='=HYPERLINK("http://evil","x")\x00ok', author_name="=1+1")]))
    ws = wb["Leads"]
    assert ws["B2"].data_type != "f" and ws["B2"].value == "=1+1"
    assert ws["K2"].data_type != "f" and "\x00" not in ws["K2"].value


def test_empty_workbook():
    wb = _load(build_leads_workbook([]))
    assert wb["Leads"].max_row == 1
    assert wb["Summary"]["B1"].value == 0
