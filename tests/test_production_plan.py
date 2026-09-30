import shutil
from collections import Counter

import pytest
from conftest import synthetic

from llm_change_tool.core.datasets import import_dataset
from llm_change_tool.core.jobs import RunConfig, create_job
from llm_change_tool.core.plans import create_plan, validate_plan
from llm_change_tool.core.projects import create_project
from llm_change_tool.storage.store import execute, transaction


def test_production_fixes_exactly_3000_ids(tmp_path):
    root = synthetic(tmp_path / "data", 3003)
    # The production population contains both the regular dataset and the
    # company-provided error candidates. Move alternating samples so every
    # split contains both sources without duplicating any logical sample.
    for index, json_path in enumerate(sorted(root.rglob("*.json"))):
        if index % 2:
            continue
        split = next(part for part in json_path.parts if part in ("train", "val", "test"))
        destination = root / "dataset" / split / "general"
        destination.mkdir(parents=True, exist_ok=True)
        image_path = json_path.with_suffix(".jpg")
        shutil.move(json_path, destination / json_path.name)
        shutil.move(image_path, destination / image_path.name)
    # Unique synthetic provenance even where the tiny rendered image repeats.
    for path in root.rglob("*.jpg"):
        with path.open("ab") as stream:
            stream.write(b"synthetic-id:" + path.stem.encode())
    project = create_project(tmp_path / "project", "Production plan test")
    assert import_dataset(project, root)["errors"] == []
    plan_id = create_plan(project, "production")
    with transaction(project) as con:
        _, members = validate_plan(con, plan_id)
    assert len({sample["id"] for sample in members}) == 3000
    assert Counter(sample["split"] for sample in members) == dict(train=1000, val=1000, test=1000)
    assert {sample["source"] for sample in members} == {"dataset", "errors"}
    source_counts = Counter(sample["source"] for sample in members)
    assert abs(source_counts["dataset"] - source_counts["errors"]) <= 1
    for split in ("train", "val", "test"):
        split_sources = Counter(sample["source"] for sample in members if sample["split"] == split)
        assert set(split_sources) == {"dataset", "errors"}
        assert abs(split_sources["dataset"] - split_sources["errors"]) <= 1
    assert create_plan(project, "production") == plan_id
    with pytest.raises(ValueError, match="actual OpenAI"):
        create_job(project, plan_id, RunConfig())
    with transaction(project) as con:
        execute(con, "DELETE FROM work_plan_items WHERE sample_id=:id", id=members[0]["id"])
        with pytest.raises(ValueError, match="invalid work plan"):
            validate_plan(con, plan_id)
