"""No network: image estimates, retry accounting, and serialized workers."""

import json

import pytest
from PIL import Image

from llm_change_tool.core.costs import image_tokens, request_cost_reserve, request_input_reserve
from llm_change_tool.core.jobs import RunConfig, create_job, job_info, run_job
from llm_change_tool.core.locking import worker_lock
from llm_change_tool.core.plans import create_plan
from llm_change_tool.providers.base import ProviderFailure, ProviderResponse
from llm_change_tool.storage.store import rows, transaction


def paid(**kwargs):
    return RunConfig(provider="openai", input_price=0.15, output_price=0.6, **kwargs)


@pytest.mark.parametrize(
    "size,detail,expected",
    [
        ((2048, 2048), "high", 25501),
        ((2048, 1024), "high", 36835),
        ((64, 64), "high", 8500),
        ((2048, 2048), "low", 2833),
        ((2048, 2048), "auto", 25501),
    ],
)
def test_documented_mini_tile_rules(size, detail, expected):
    assert image_tokens("gpt-4o-mini", size, detail) == expected


def test_model_detail_prompt_schema_output_and_manual_floor():
    images = [Image.new("RGB", (2048, 1024))] * 2
    config = paid()
    inputs = request_input_reserve(images, "guide", config)
    assert inputs > 2 * 36835
    assert request_input_reserve(images, "가이드" * 10000, config) > inputs
    assert request_input_reserve(images, "guide", paid(image_detail="low")) < inputs
    assert image_tokens("gpt-4o", (2048, 1024)) < image_tokens("gpt-4o-mini", (2048, 1024))
    assert request_cost_reserve(
        images, "guide", paid(max_output_tokens=4000)
    ) > request_cost_reserve(images, "guide", config)
    assert request_input_reserve(images, "guide", paid(input_token_reserve=200000)) == 200000
    assert image_tokens("gpt-4o-mini", (64, 64), override=100000) == 100000
    with pytest.raises(ValueError, match="unverified"):
        image_tokens("unknown-model", (2048, 2048))
    assert image_tokens("unknown-model", (2048, 2048), override=80000) == 80000
    for prices in ({"input_price": 0, "output_price": 1}, {"input_price": 1, "output_price": 0}):
        with pytest.raises(ValueError):
            RunConfig(provider="openai", **prices)


def test_budget_blocks_large_request_before_provider(imported, monkeypatch):
    project, _ = imported
    images = [Image.new("RGB", (2048, 2048))] * 2
    monkeypatch.setattr("llm_change_tool.core.jobs.sample_images", lambda *a: images)
    config = paid(cost_limit=0.005)
    assert config.reserve() < config.cost_limit < request_cost_reserve(images, "guide", config)

    class Never:
        def predict(self, *args):
            pytest.fail("An over-budget request must not reach the provider")

    job = create_job(project, create_plan(project), config)
    result = run_job(project, job, provider=Never())
    assert result["state"] == "PAUSED"
    assert result["counts"] == {"PENDING": 6}
    with transaction(project, readonly=True) as con:
        assert not rows(con, "SELECT * FROM attempts")


def test_unknown_image_rules_pause_without_call_or_unknown_charge(imported):
    project, _ = imported
    calls = []

    class Never:
        def predict(self, *args):
            calls.append(True)

    job = create_job(project, create_plan(project), paid(model="unverified-model"))
    result = run_job(project, job, provider=Never())
    assert result["state"] == "PAUSED" and not calls
    assert result["usage"]["reserved"] == result["usage"]["cost"] == 0
    assert result["failures"][0]["error"] == "unverified_cost_estimate"


def test_retry_reserves_again_and_parallel_worker_cannot_double_spend(imported, monkeypatch):
    project, _ = imported
    images = [Image.new("RGB", (2048, 2048))] * 2
    monkeypatch.setattr("llm_change_tool.core.jobs.sample_images", lambda *a: images)
    monkeypatch.setattr("llm_change_tool.core.jobs.time.sleep", lambda *a: None)
    config = paid(cost_limit=0.015)
    job = create_job(project, create_plan(project), config, prompt="guide")
    calls = []

    class Timeout:
        def predict(self, *args):
            calls.append(True)
            # The live worker holds the project lock throughout the request.
            with pytest.raises(ValueError, match="worker is active"), worker_lock(project):
                pass
            with pytest.raises(ValueError, match="worker is active"):
                run_job(project, job, provider=self)
            raise ProviderFailure("connection_or_timeout", True)

    result = run_job(project, job, provider=Timeout())
    assert len(calls) == 1 and result["state"] == "PAUSED"
    assert result["usage"]["reserved"] == pytest.approx(
        request_cost_reserve(images, "guide", config)
    )
    assert result["counts"] == {"PENDING": 6}
    # Allow two requests; each unknown outcome must retain its own reservation.
    from llm_change_tool.core.jobs import update_budget

    update_budget(project, job, 0.025, expected_limit=0.015, reason="offline retry test")
    result = run_job(project, job, provider=Timeout())
    assert len(calls) == 2 and result["state"] == "PAUSED"
    assert result["usage"]["reserved"] == pytest.approx(
        2 * request_cost_reserve(images, "guide", config)
    )


@pytest.mark.parametrize("malformed", [False, True])
def test_known_usage_replaces_reservation_and_overrun_pauses(imported, malformed):
    project, _ = imported
    calls = []
    from llm_change_tool.core.labels import KEYS

    class Expensive:
        def predict(self, images, prompt, config):
            calls.append(True)
            return ProviderResponse(
                "{}"
                if malformed
                else json.dumps(
                    dict(
                        labels=dict.fromkeys(KEYS, 0),
                        confidence=0.9,
                        reason="offline",
                        review_required=False,
                    )
                ),
                1000000,
                100,
            )

    job = create_job(project, create_plan(project), paid())
    result = run_job(project, job, provider=Expensive())
    assert result["state"] == "PAUSED" and len(calls) == 1
    assert result["usage"]["reserved"] == 0
    assert job_info(project, job)["usage"]["cost"] == pytest.approx(0.15006)


def test_v6_job_can_set_audited_estimate_resume_and_restore(tmp_path, monkeypatch):
    from conftest import synthetic
    from test_handoff_regressions import Matching

    from llm_change_tool.core import projects
    from llm_change_tool.core.datasets import import_dataset
    from llm_change_tool.core.jobs import update_image_reservation
    from llm_change_tool.core.projects import backup_project, open_project, restore_project
    from llm_change_tool.storage import database
    from llm_change_tool.storage.store import one

    with monkeypatch.context() as patch:
        patch.setattr(database, "SCHEMA_VERSION", 6)
        patch.setattr(projects, "SCHEMA_VERSION", 6)
        project = projects.create_project(tmp_path / "v6", "Legacy")
        import_dataset(project, synthetic(tmp_path / "dataset"))
        job = create_job(project, create_plan(project), paid(model="unverified-model"))
        with transaction(project, readonly=True) as con:
            frozen = one(con, "SELECT * FROM llm_runs")
    project = open_project(project.root)
    backups = list((project.root / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with database.connect(backups[0], readonly=True) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6
    result = run_job(project, job, provider=Matching())
    assert result["state"] == "PAUSED"
    result = update_image_reservation(
        project, job, 80000, expected_tokens=None, reason="Explicit offline estimate"
    )
    assert result["image_token_override"] == 80000 and result["counts"] == {"PENDING": 6}
    with pytest.raises(ValueError, match="changed"):
        update_image_reservation(project, job, 90000, expected_tokens=None, reason="stale")
    with worker_lock(project), pytest.raises(ValueError, match="worker is active"):
        update_image_reservation(project, job, 90000, expected_tokens=80000, reason="busy")
    assert run_job(open_project(project.root), job, provider=Matching())["state"] == "COMPLETED"
    restored = restore_project(backup_project(project), tmp_path / "restored")
    assert job_info(restored, job)["image_token_override"] == 80000
    with transaction(restored, readonly=True) as con:
        assert one(con, "SELECT * FROM llm_runs") == frozen
        assert len(rows(con, "SELECT * FROM job_reservation_events")) == 1
