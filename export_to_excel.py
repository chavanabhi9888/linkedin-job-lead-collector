"""Export all leads to an Excel file. Usage: python export_to_excel.py [output_path]

Default output directory comes from EXPORT_DIR (env / .env), falling back to ./exports.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.db.repositories import LeadFilter, LeadRepository
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.exporters.excel import build_leads_workbook

settings = get_settings()
engine = create_db_engine(settings.database_url)
factory = create_session_factory(engine)

if len(sys.argv) > 1:
    out_file = Path(sys.argv[1])
else:
    export_dir = Path(os.getenv("EXPORT_DIR", "exports"))
    out_file = export_dir / f"leads_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
out_file.parent.mkdir(parents=True, exist_ok=True)

with session_scope(factory) as session:
    leads = LeadRepository(session).all(LeadFilter(), limit=1000)
    out_file.write_bytes(build_leads_workbook(leads))
    print(f"Saved {len(leads)} leads to {out_file.resolve()}")
