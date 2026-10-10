import json

import pytest
from PIL import Image, ImageDraw

from llm_change_tool.core.datasets import import_dataset
from llm_change_tool.core.labels import FIELDS
from llm_change_tool.core.projects import create_project


def synthetic(root, count=6):
    for i in range(count):
        folder = root / "errors" / ("train", "val", "test")[i % 3] / "artifact_fn_00"
        folder.mkdir(parents=True, exist_ok=True)
        doc = {
            "reason": "synthetic only",
            "reason_ko": "합성 테스트",
            "unknown_metadata": {"keep": i},
            "artifact_detail": {},
        }
        for f in FIELDS:
            target = doc
            for key in f["path"][:-1]:
                target = target.setdefault(key, {})
            target[f["path"][-1]] = "x"
        (folder / f"{i:04d}_combined.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
        im = Image.new("RGB", (128, 64), (i * 30 % 255, 70, 90))
        ImageDraw.Draw(im).rectangle((10 + i, 10, 30 + i, 30), fill=(200, 200, 200))
        # Keep exact decoded image identity distinct in large fixtures.
        draw = ImageDraw.Draw(im)
        for bit in range(16):
            draw.rectangle(
                (bit * 8, 48, bit * 8 + 7, 63), fill="white" if i & (1 << bit) else "black"
            )
        im.save(folder / f"{i:04d}_combined.jpg", quality=95)
    return root


@pytest.fixture
def imported(tmp_path):
    project = create_project(tmp_path / "project", "합성 검수")
    root = synthetic(tmp_path / "dataset")
    report = import_dataset(project, root)
    assert report["errors"] == []
    return project, root
