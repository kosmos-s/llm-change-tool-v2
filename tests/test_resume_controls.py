import pytest
from PIL import Image

from llm_change_tool.core.costs import request_cost_reserve, request_input_reserve
from llm_change_tool.core.jobs import (
    RunConfig,
    control_job,
    create_job,
    job_info,
    run_job,
    update_budget,
)
from llm_change_tool.core.labels import prompt_text
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
    )
    per_item = request_cost_reserve([Image.new("RGB", (64, 64))] * 2, prompt_text(), cfg)
    cfg.cost_limit = 2 * per_item
    job = create_job(project, create_plan(project), cfg)

    class Metered:
        calls = 0

        def predict(self, *args):
            self.calls += 1
            images, prompt, config = args
            return ProviderResponse(
                MockProvider().predict(*args).raw,
                request_input_reserve(images, prompt, config),
                config.max_output_tokens,
            )

    provider = Metered()
    initial = run_job(project, job, provider=provider)
    assert initial["state"] == "PAUSED" and initial["counts"]["COMPLETED"] == 2
    with transaction(project) as con:
        frozen = one(con, "SELECT * FROM llm_runs WHERE id=:id", id=initial["run_id"])
    update_budget(
        project, job, 10 * per_item, expected_limit=cfg.cost_limit, reason="나머지 4건 처리"
    )
    with pytest.raises(ValueError, match="변경되었습니다"):
        update_budget(project, job, 20 * per_item, expected_limit=cfg.cost_limit, reason="stale")
    result = run_job(project, job, provider=provider)
    assert result["state"] == "COMPLETED" and result["counts"]["COMPLETED"] == 6
    assert result["run_id"] == initial["run_id"] and provider.calls == 6
    assert result["cost_limit"] == 10 * per_item
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
