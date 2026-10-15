"""Offline evaluation of actual model predictions against a fixed human reference."""

import argparse
import json
from pathlib import Path

from llm_change_tool.core.evaluation import export_comparison_report
from llm_change_tool.core.metrics import import_model_predictions
from llm_change_tool.core.projects import open_project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--retrained", type=Path, required=True)
    parser.add_argument("--baseline-name", default="Baseline")
    parser.add_argument("--retrained-name", default="Retrained")
    args = parser.parse_args(argv)
    project = open_project(args.project)
    baseline = import_model_predictions(project, args.baseline, args.baseline_name)
    retrained = import_model_predictions(project, args.retrained, args.retrained_name)
    report = export_comparison_report(
        project, baseline["evaluation_id"], retrained["evaluation_id"]
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "path",
                    "manual_audit_path",
                    "delta_f1",
                    "delta_percentage_points",
                    "final_test_eligible",
                    "manual_review_status",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
