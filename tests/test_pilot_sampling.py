import json

import pytest

from llm_change_tool.core.model_catalog import OPENAI_MODELS, model_spec
from llm_change_tool.core.plans import create_plan, preview_plan, validate_plan
from llm_change_tool.core.sampling import balanced_pilot_sample
from llm_change_tool.storage.store import one, transaction


def test_pilot_plan_uses_requested_reproducible_sample_count(imported):
    project, _ = imported
    plan = create_plan(project, "pilot", "stable-seed", sample_count=3)
    assert create_plan(project, "pilot", "stable-seed", sample_count=3) == plan
    with transaction(project) as con:
        _, members = validate_plan(con, plan)
        report = json.loads(
            one(con, "SELECT payload FROM plan_selections WHERE plan_id=:id", id=plan)["payload"]
        )
    assert len(members) == 3
    assert report["requested_count"] == report["selected_count"] == 3
    assert report["algorithm"] == "balanced-source-split-error-label-v1"


def test_pilot_preview_clamps_to_available_samples(imported):
    project, _ = imported
    report = preview_plan(project, "pilot", sample_count=50)
    assert report["candidate_count"] == report["selected_count"] == 6
    assert report["requested_count"] == 50
    with pytest.raises(ValueError, match="1 이상의 정수"):
        create_plan(project, "pilot", sample_count=0)


def test_pilot_balancing_includes_source_and_split():
    samples = []
    for source in ("dataset", "errors"):
        for split in ("train", "val", "test"):
            for number in range(2):
                samples.append(
                    {
                        "id": f"{source}-{split}-{number}",
                        "source": source,
                        "split": split,
                        "error_type": "artifact_fn_00",
                        "original_labels": '{"Artifact": 0}',
                    }
                )
    selected = balanced_pilot_sample(samples, 6, "seed")
    assert {sample["source"] for sample in selected} == {"dataset", "errors"}
    assert {sample["split"] for sample in selected} == {"train", "val", "test"}


def test_openai_model_catalog_has_pinned_automatic_prices():
    assert [spec.model for spec in OPENAI_MODELS] == [
        "gpt-4o-mini",
        "gpt-6-luna",
        "gpt-6.1-sol",
    ]
    assert model_spec("gpt-4o-mini").input_price == 0.15
    with pytest.raises(ValueError, match="지원 모델"):
        model_spec("gpt-5.6-terra")
