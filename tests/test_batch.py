import json
from datetime import timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.batch import export_leads, load_plan, run_batch
from app.config import Settings
from app.sources.base import RawPost
from app.sources.errors import ChallengeRequiredError, SourceTimeoutError
from tests.conftest import NOW, post_url_for


def make_plan(tmp_path, **overrides):
    data = {
        "keywords": ["Python Developer", "Django Developer"],
        "locations": ["Pune", "Mumbai"],
        "time_filter": "past_week",
        "max_posts": 10,
        "cooldown_min_s": 30,
        "cooldown_max_s": 30,
        "export_dir": str(tmp_path / "exports"),
    }
    data.update(overrides)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data), encoding="utf-8-sig")  # BOM, as Windows Notepad writes
    return load_plan(path, Settings(_env_file=None))


class Factory:
    """One source per run; ``behaviours[n]`` is an exception to raise on the n-th run (default: succeed)."""

    def __init__(self, behaviours=None):
        self.n = 0
        self.behaviours = behaviours or {}

    def __call__(self):
        self.n += 1
        n, behaviour = self.n, self.behaviours.get(self.n)

        class Src:
            name = "fake"

            def fetch_posts(self, criteria):
                if behaviour is not None:
                    raise behaviour
                yield RawPost(
                    post_url=post_url_for(NOW - timedelta(minutes=n)),
                    text=f"Hiring {criteria.keyword} in {criteria.location}. Mail hr{n}@acme.io",
                    author_name="A",
                )

        return Src()


def _run(plan, session_factory, factory):
    slept = []
    result = run_batch(
        plan, session_factory, factory, sleep=slept.append, clock=lambda: NOW, out=lambda _m: None
    )
    return result, slept


def test_runs_every_combination_then_exports(session_factory, tmp_path):
    plan = make_plan(tmp_path)
    result, slept = _run(plan, session_factory, Factory())
    assert [(o.keyword, o.location) for o in result.outcomes] == [
        ("Python Developer", "Pune"), ("Django Developer", "Pune"),
        ("Python Developer", "Mumbai"), ("Django Developer", "Mumbai"),
    ]
    assert all(o.status == "SUCCEEDED" and o.new_leads == 1 and o.emails == 1 for o in result.outcomes)
    assert slept == [30, 30, 30]  # cool-down between runs, not after the last
    path, rows = export_leads(session_factory, plan, result.job_ids, clock=lambda: NOW)
    assert rows == 4 and path.exists()
    assert load_workbook(BytesIO(path.read_bytes()))["Leads"].max_row == 5


def test_challenge_aborts_batch_but_keeps_partial_export(session_factory, tmp_path):
    plan = make_plan(tmp_path)
    result, _ = _run(plan, session_factory, Factory({2: ChallengeRequiredError("captcha")}))
    assert len(result.outcomes) == 2
    assert result.outcomes[1].status == "NEEDS_MANUAL_ACTION"
    assert "login" in result.aborted_reason
    _, rows = export_leads(session_factory, plan, result.job_ids, clock=lambda: NOW)
    assert rows == 1


def test_consecutive_failures_stop_the_batch(session_factory, tmp_path):
    plan = make_plan(tmp_path, stop_after_consecutive_failures=2)
    failing = {n: SourceTimeoutError("slow") for n in range(1, 5)}
    result, _ = _run(plan, session_factory, Factory(failing))
    assert len(result.outcomes) == 2 and "consecutive" in result.aborted_reason


def test_resume_skips_recent_successes(session_factory, tmp_path):
    plan = make_plan(tmp_path, skip_if_succeeded_within_hours=12)
    _run(plan, session_factory, Factory())
    factory = Factory()
    result, slept = _run(plan, session_factory, factory)
    assert factory.n == 0 and slept == []
    assert all(o.status == "SKIPPED" for o in result.outcomes)
    _, rows = export_leads(session_factory, plan, result.job_ids, clock=lambda: NOW)
    assert rows == 4  # earlier batch's leads are still in the "new" export


def test_export_all_and_require_contact(session_factory, tmp_path):
    plan = make_plan(tmp_path, export_scope="all", export_require_contact=True)
    _run(plan, session_factory, Factory())
    _, rows = export_leads(session_factory, plan, [], clock=lambda: NOW)
    assert rows == 4


@pytest.mark.parametrize(
    "bad",
    [
        {"keywords": []},
        {"locations": [" "]},
        {"cooldown_min_s": 5, "cooldown_max_s": 10},
        {"cooldown_min_s": 60, "cooldown_max_s": 40},
        {"time_filter": "yesterday"},
        {"max_posts": 0},
        {"export_scope": "everything"},
        {"keywrods": ["typo"]},
    ],
)
def test_invalid_plans_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        make_plan(tmp_path, **bad)


def test_duplicate_keywords_and_locations_collapse(tmp_path):
    plan = make_plan(tmp_path, keywords=["Python Developer", "python  developer"], locations=["Pune", "pune"])
    assert plan.combos() == [("Python Developer", "Pune")]
