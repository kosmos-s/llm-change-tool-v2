import pytest

from llm_change_tool.core.jobs import (
    RunConfig,
    control_job,
    create_job,
    job_info,
    run_job,
    update_budget,
)
from llm_change_tool.core.plans import create_plan
from llm_change_tool.providers.base import ProviderResponse
from llm_change_tool.providers.mock import MockProvider
from llm_change_tool.storage.store import one, rows, transaction


def test_budget_increase_resumes_only_remaining_samples(imported):
    project, _ = imported
    cfg = RunConfig(
        provider="openai",
        input_price=1,
        output_price=1,
        input_token_reserve=1000,
        max_output_tokens=100,
        cost_limit=0.0022,
    )
    job = create_job(project, create_plan(project), cfg)

    class Metered:
        calls = 0

        def predict(self, *args):
            self.calls += 1
            return ProviderResponse(MockProvider().predict(*args).raw, 1000, 100)

    provider = Metered()
    initial = run_job(project, job, provider=provider)
    assert initial["state"] == "PAUSED" and initial["counts"]["COMPLETED"] == 2
    with transaction(project) as con:
        frozen = one(con, "SELECT * FROM llm_runs WHERE id=:id", id=initial["run_id"])
    update_budget(project, job, 0.01, expected_limit=0.0022, reason="나머지 4건 처리")
    with pytest.raises(ValueError, match="변경되었습니다"):
        update_budget(project, job, 0.02, expected_limit=0.0022, reason="stale")
    result = run_job(project, job, provider=provider)
    assert result["state"] == "COMPLETED" and result["counts"]["COMPLETED"] == 6
    assert result["run_id"] == initial["run_id"] and provider.calls == 6
    assert result["cost_limit"] == 0.01
    with transaction(project) as con:
        assert one(con, "SELECT * FROM llm_runs WHERE id=:id", id=initial["run_id"]) == frozen
        assert len(rows(con, "SELECT * FROM attempts")) == 6
        assert len(rows(con, "SELECT * FROM job_budget_events")) == 1


def test_cancelled_job_reopens_without_losing_completed_results(imported):
    project, _ = imported
    plan = create_plan(project)
    cfg = RunConfig()
    job = create_job(project, plan, cfg)
    result = run_job(project, job, progress=lambda _: control_job(project, job, "cancel"))
    assert result["state"] == "CANCELLED" and result["counts"]["COMPLETED"] == 1
    with pytest.raises(ValueError, match="취소 작업 다시 열기"):
        create_job(project, plan, cfg)
    control_job(project, job, "reopen")
    assert job_info(project, job)["state"] == "PAUSED"
    assert run_job(project, job)["counts"]["COMPLETED"] == 6
    with transaction(project) as con:
        assert len(rows(con, "SELECT * FROM attempts")) == 6
        assert len(rows(con, "SELECT * FROM job_control_events")) == 1
    with pytest.raises(ValueError, match="취소된"):
        control_job(project, job, "reopen")


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), 1001, True])
def test_invalid_budget_rejected(imported, value):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig())
    with pytest.raises(ValueError):
        update_budget(project, job, value, expected_limit=5, reason="test")
