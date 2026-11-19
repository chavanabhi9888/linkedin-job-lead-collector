import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sources.json_file import JsonFileSource


class ImmediateExecutor:
    def submit(self, fn, *args):
        fn(*args)

    def shutdown(self, wait=True, **kwargs):
        pass


@pytest.fixture()
def client(session_factory, sample_json):
    settings = Settings(_env_file=None, database_url="sqlite+pysqlite://", api_key="secret", log_json=False)
    app = create_app(
        settings,
        session_factory=session_factory,
        source_factory=lambda: JsonFileSource(sample_json),
        executor=ImmediateExecutor(),
    )
    with TestClient(app, headers={"X-API-Key": "secret"}) as c:
        yield c


def test_health_is_public(client):
    r = client.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok"}


def test_api_key_required(client):
    assert client.get("/leads", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/leads", headers={"X-API-Key": ""}).status_code == 401


def test_run_job_then_query_and_export(client):
    r = client.post("/jobs/run", json={"time_filter": "past_week", "max_posts": 10})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "SUCCEEDED" and job["new_leads"] == 1 and job["emails_found"] == 1

    leads = client.get("/leads", params={"has_email": True}).json()
    assert leads["total"] == 1
    item = leads["items"][0]
    assert item["email"] == "jobs@acme.io" and item["phone"] == "+919876543210"
    assert item["profile_url"] == "https://www.linkedin.com/in/asha-rao"
    assert item["job_title"] == "Python Developer" and item["location"] == "Pune"

    xlsx = client.get("/leads/export/excel")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert "attachment" in xlsx.headers["content-disposition"]
    pdf = client.get("/leads/export/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_unknown_job_and_validation(client):
    assert client.get("/jobs/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.post("/jobs/run", json={"max_posts": 0}).status_code == 422
    assert client.post("/jobs/run", json={"time_filter": "yesterday"}).status_code == 422
