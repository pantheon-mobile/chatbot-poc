import ast
import io
import json
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


def _load(*names):
    source = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants = {
        "EVALUATION_HISTORY_PREFIX", "EVALUATION_HISTORY_SCHEMA_VERSION",
        "MANUAL_JUDGMENT_SCORES", "EVALUATION_HISTORY_REQUIRED_FILES"
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
        or isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constants for target in node.targets
        )
    ]
    namespace = {
        "pd": pd, "io": io, "json": json, "uuid": uuid, "datetime": datetime,
        "Optional": Optional,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


class Body:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class Paginator:
    def __init__(self, keys):
        self.keys = keys

    def paginate(self, **kwargs):
        return [{"Contents": [{"Key": key} for key in self.keys]}]


class FakeS3:
    def __init__(self, objects=None, fail_key=""):
        self.objects = dict(objects or {})
        self.fail_key = fail_key
        self.put_calls = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        if kwargs["Key"] == self.fail_key:
            raise RuntimeError("simulated failure")
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        if kwargs["Key"] not in self.objects:
            raise KeyError(kwargs["Key"])
        return {"Body": Body(self.objects[kwargs["Key"]])}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return Paginator(list(self.objects))


def _evaluation():
    comparison = pd.DataFrame([
        {"question_id": "Q1", "question": "q1", "ingestion_format": "FILE_PDF",
         "answer_judgment": "CORRECT", "answer_score": 1.0,
         "top_retrieval_score": 0.8, "retrieval_elapsed_ms": 10,
         "generation_elapsed_ms": 20, "total_elapsed_ms": 30, "unknown_column": "keep"}
    ])
    summary = pd.DataFrame([
        {"ingestion_format": "FILE_PDF", "question_count": 1, "correct_count": 1,
         "partial_count": 0, "incorrect_count": 0, "evaluation_error_count": 0,
         "accuracy": 1.0, "weighted_accuracy": 1.0, "average_top_score": 0.8,
         "average_retrieval_ms": 10, "average_generation_ms": 20, "average_total_ms": 30}
    ])
    return {
        "comparison": comparison, "detail": pd.DataFrame([{"rank": 1}]),
        "accuracy_summary": summary, "category_summary": pd.DataFrame(),
        "difficulty_summary": pd.DataFrame()
    }


def test_experiment_id_is_unique():
    ns = _load("generate_evaluation_experiment_id")
    ids = {ns["generate_evaluation_experiment_id"](datetime(2026, 8, 25, 15, 30, 12)) for _ in range(20)}
    assert len(ids) == 20
    assert all(value.startswith("20260825_153012_") and len(value.rsplit("_", 1)[1]) == 8 for value in ids)


def test_metadata_schema_and_bom_unknown_column_preservation():
    ns = _load("build_evaluation_history_metadata", "dataframe_csv_bom")
    evaluation = _evaluation()
    metadata = ns["build_evaluation_history_metadata"](
        "ID", {"experiment_name": "name"}, evaluation,
        {"FILE_PDF": {"knowledge_base_id": "KB", "data_source_id": "DS"}},
        "answer-model", "eval-model", 4000, 5
    )
    assert metadata["schema_version"] == "1.0"
    assert metadata["temperature"] == 0
    assert metadata["knowledge_bases"] == {"FILE_PDF": "KB"}
    csv_body = ns["dataframe_csv_bom"](evaluation["comparison"])
    assert csv_body.startswith(b"\xef\xbb\xbf")
    assert "unknown_column" in csv_body.decode("utf-8-sig")


def test_save_all_files_and_partial_failure_status():
    ns = _load("save_evaluation_history")
    files = {"results/a.csv": (b"a", "text/csv"), "results/b.csv": (b"b", "text/csv")}
    fake = FakeS3()
    rows = ns["save_evaluation_history"]("bucket", "ID", {"status": "COMPLETE"}, files, fake)
    assert all(row["結果"] == "成功" for row in rows)
    saved_metadata = json.loads(fake.objects["evaluation-history/ID/metadata.json"])
    assert saved_metadata["status"] == "COMPLETE"
    failing = FakeS3(fail_key="evaluation-history/ID/results/b.csv")
    rows = ns["save_evaluation_history"]("bucket", "ID", {}, files, failing)
    assert any(row["結果"] == "失敗" for row in rows)
    assert json.loads(failing.objects["evaluation-history/ID/metadata.json"])["status"] == "INCOMPLETE"


def test_broken_history_does_not_hide_valid_history_and_sort_is_newest_first():
    ns = _load("list_evaluation_histories")
    required = ns["EVALUATION_HISTORY_REQUIRED_FILES"]
    objects = {}
    for experiment_id, executed_at in [("OLD", "2026-08-24T10:00:00"), ("NEW", "2026-08-25T10:00:00")]:
        for relative in required:
            key = f"evaluation-history/{experiment_id}/{relative}"
            objects[key] = (
                json.dumps({"experiment_id": experiment_id, "executed_at": executed_at,
                            "status": "COMPLETE"}).encode() if relative == "metadata.json" else b"x"
            )
    objects["evaluation-history/BROKEN/metadata.json"] = b"{broken"
    histories = ns["list_evaluation_histories"]("bucket", FakeS3(objects))
    assert histories[0]["experiment_id"] == "NEW"
    assert {item["experiment_id"] for item in histories} == {"OLD", "NEW", "BROKEN"}
    assert next(item for item in histories if item["experiment_id"] == "BROKEN")["status"] == "INCOMPLETE"


def test_format_and_question_differences_include_improvement_worsening_and_question_id():
    ns = _load("build_history_format_difference", "build_history_question_difference")
    base_summary = pd.DataFrame([{"ingestion_format": "FILE_PDF", "accuracy": 0.5, "weighted_accuracy": 0.5}])
    target_summary = pd.DataFrame([{"ingestion_format": "FILE_PDF", "accuracy": 1.0, "weighted_accuracy": 1.0}])
    difference = ns["build_history_format_difference"](base_summary, target_summary)
    assert difference.iloc[0]["accuracy_difference"] == 0.5
    base = pd.DataFrame([
        {"question_id": "Q1", "question": "old wording", "ingestion_format": "FILE_PDF", "answer_judgment": "INCORRECT"},
        {"question_id": "Q2", "question": "q2", "ingestion_format": "FILE_PDF", "answer_judgment": "CORRECT"},
    ])
    target = pd.DataFrame([
        {"question_id": "Q1", "question": "new wording", "ingestion_format": "FILE_PDF", "answer_judgment": "CORRECT"},
        {"question_id": "Q2", "question": "q2", "ingestion_format": "FILE_PDF", "answer_judgment": "INCORRECT"},
    ])
    changes = ns["build_history_question_difference"](base, target).set_index("question_id")
    assert changes.loc["Q1", "change"] == "改善"
    assert changes.loc["Q2", "change"] == "悪化"


def test_question_text_fallback_partial_weight_and_manual_effective_priority():
    ns = _load("build_history_question_difference", "apply_effective_manual_review",
               "recommend_ingestion_formats")
    base = pd.DataFrame([{"question": "same", "ingestion_format": "FILE_TXT", "answer_judgment": "PARTIAL"}])
    target = pd.DataFrame([{"question": "same", "ingestion_format": "FILE_TXT", "answer_judgment": "CORRECT"}])
    assert ns["build_history_question_difference"](base, target).iloc[0]["change"] == "改善"
    reviewed = ns["apply_effective_manual_review"](pd.DataFrame([{
        "answer_judgment": "INCORRECT", "answer_score": 0,
        "manual_answer_judgment": "PARTIAL"
    }]))
    assert reviewed.iloc[0]["effective_answer_judgment"] == "PARTIAL"
    assert reviewed.iloc[0]["effective_answer_score"] == 0.5
    recommendation = ns["recommend_ingestion_formats"](pd.DataFrame([
        {"ingestion_format": "A", "evaluation_error_count": 0, "incorrect_count": 0,
         "weighted_accuracy": 0.5, "accuracy": 0.0, "average_total_ms": 10},
        {"ingestion_format": "B", "evaluation_error_count": 0, "incorrect_count": 0,
         "weighted_accuracy": 1.0, "accuracy": 1.0, "average_total_ms": 20},
    ]))
    assert recommendation["formats"] == ["B"]


def test_effective_manual_review_with_all_rows_unreviewed():
    apply_review = _load("apply_effective_manual_review")["apply_effective_manual_review"]
    frame = pd.DataFrame([
        {"auto_answer_judgment": "CORRECT", "auto_answer_score": 1.0,
         "manual_answer_judgment": "未確認"},
        {"auto_answer_judgment": "INCORRECT", "auto_answer_score": 0.0,
         "manual_answer_judgment": "未確認"},
    ])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = apply_review(frame)

    assert result["effective_answer_judgment"].tolist() == ["CORRECT", "INCORRECT"]
    assert result["effective_answer_score"].tolist() == [1.0, 0.0]
    assert result["effective_answer_score"].dtype == float


def test_effective_manual_review_without_manual_judgment_column():
    apply_review = _load("apply_effective_manual_review")["apply_effective_manual_review"]
    frame = pd.DataFrame([
        {"auto_answer_judgment": "CORRECT", "auto_answer_score": 1},
        {"auto_answer_judgment": "PARTIAL", "auto_answer_score": 0.5},
    ])

    result = apply_review(frame)

    assert result["manual_answer_judgment"].tolist() == ["未確認", "未確認"]
    assert result["effective_answer_judgment"].tolist() == ["CORRECT", "PARTIAL"]
    assert result["effective_answer_score"].tolist() == [1.0, 0.5]


def test_effective_manual_review_overrides_only_reviewed_row():
    apply_review = _load("apply_effective_manual_review")["apply_effective_manual_review"]
    frame = pd.DataFrame([
        {"auto_answer_judgment": "INCORRECT", "auto_answer_score": 0,
         "manual_answer_judgment": "PARTIAL"},
        {"auto_answer_judgment": "CORRECT", "auto_answer_score": 1,
         "manual_answer_judgment": "未確認"},
    ])

    result = apply_review(frame)

    assert result["effective_answer_judgment"].tolist() == ["PARTIAL", "CORRECT"]
    assert result["effective_answer_score"].tolist() == [0.5, 1.0]
    assert result["manual_answer_score"].iloc[0] == 0.5
    assert pd.isna(result["manual_answer_score"].iloc[1])


def test_effective_manual_review_accepts_empty_dataframe():
    apply_review = _load("apply_effective_manual_review")["apply_effective_manual_review"]

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = apply_review(pd.DataFrame())

    assert result.empty
    assert result["effective_answer_score"].dtype == float


def test_effective_manual_review_normalizes_mixed_auto_scores():
    apply_review = _load("apply_effective_manual_review")["apply_effective_manual_review"]
    frame = pd.DataFrame([
        {"auto_answer_judgment": "CORRECT", "auto_answer_score": "1"},
        {"auto_answer_judgment": "INCORRECT", "auto_answer_score": ""},
        {"auto_answer_judgment": "INCORRECT", "auto_answer_score": None},
    ])

    result = apply_review(frame)

    assert result["effective_answer_score"].iloc[0] == 1.0
    assert result["effective_answer_score"].iloc[1:].isna().all()
    assert result["effective_answer_score"].dtype == float
