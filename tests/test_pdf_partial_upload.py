import ast
import time
from datetime import datetime
from pathlib import Path


def _load_functions(*names):
    source = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "INGESTION_TEST_KB_PREFIXES": {
            "FILE_PDF": "documents/ingestion-test/kb-source/file-pdf/",
            "FILE_TXT": "documents/ingestion-test/kb-source/file-txt/",
            "FILE_MARKDOWN": "documents/ingestion-test/kb-source/file-markdown/",
            "FILE_VISION_MARKDOWN": "documents/ingestion-test/kb-source/file-vision-markdown/",
        },
        "PDF_COMPARISON_BUCKET": "chat-bot-poc-plus",
        "os": __import__("os"), "json": __import__("json"),
        "time": time, "datetime": datetime,
        "INGESTION_SYNC_SUCCESS_STATUSES": {"COMPLETE"},
        "INGESTION_SYNC_FAILURE_STATUSES": {"FAILED", "STOPPED"},
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


class FakeS3:
    def __init__(self, fail_key=""):
        self.fail_key = fail_key
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["Key"] == self.fail_key:
            raise RuntimeError("simulated failure")


def _artifacts(namespace, format_name, original="sample.pdf"):
    return namespace["build_pdf_comparison_s3_artifacts"](
        format_name, original, b"body" if format_name == "FILE_PDF" else "body",
        {"metadataAttributes": {"datasource_id": "DS_TEST"}}, "DS_TEST"
    )


def test_partial_upload_writes_only_selected_body_and_metadata():
    ns = _load_functions(
        "pdf_comparison_source_file_name", "build_pdf_comparison_s3_artifacts",
        "upload_selected_pdf_artifacts_to_s3"
    )
    fake = FakeS3()
    ns["create_aws_client"] = lambda service: fake
    artifacts = _artifacts(ns, "FILE_PDF") + _artifacts(ns, "FILE_MARKDOWN")
    rows = ns["upload_selected_pdf_artifacts_to_s3"](artifacts, ["FILE_MARKDOWN"])
    assert [call["Key"] for call in fake.calls] == [
        "documents/ingestion-test/kb-source/file-markdown/sample.md",
        "documents/ingestion-test/kb-source/file-markdown/sample.md.metadata.json",
    ]
    assert rows[0]["総合結果"] == "成功"


def test_metadata_failure_is_format_failure_and_other_format_continues():
    ns = _load_functions(
        "pdf_comparison_source_file_name", "build_pdf_comparison_s3_artifacts",
        "upload_selected_pdf_artifacts_to_s3"
    )
    failed_key = "documents/ingestion-test/kb-source/file-markdown/sample.md.metadata.json"
    fake = FakeS3(failed_key)
    ns["create_aws_client"] = lambda service: fake
    artifacts = _artifacts(ns, "FILE_MARKDOWN") + _artifacts(ns, "FILE_TXT")
    rows = ns["upload_selected_pdf_artifacts_to_s3"](
        artifacts, ["FILE_MARKDOWN", "FILE_TXT"]
    )
    by_format = {row["生成形式"]: row for row in rows}
    assert by_format["FILE_MARKDOWN"]["本体アップロード結果"] == "成功"
    assert by_format["FILE_MARKDOWN"]["metadataアップロード結果"] == "失敗"
    assert by_format["FILE_MARKDOWN"]["総合結果"] == "失敗"
    assert by_format["FILE_TXT"]["総合結果"] == "成功"
    assert len(fake.calls) == 4


def test_all_four_formats_write_eight_objects():
    ns = _load_functions(
        "pdf_comparison_source_file_name", "build_pdf_comparison_s3_artifacts",
        "upload_selected_pdf_artifacts_to_s3"
    )
    fake = FakeS3()
    ns["create_aws_client"] = lambda service: fake
    formats = ["FILE_PDF", "FILE_TXT", "FILE_MARKDOWN", "FILE_VISION_MARKDOWN"]
    artifacts = sum((_artifacts(ns, name) for name in formats), [])
    rows = ns["upload_selected_pdf_artifacts_to_s3"](artifacts, formats)
    assert len(fake.calls) == 8
    assert all(row["総合結果"] == "成功" for row in rows)


def test_pdf_only_and_any_two_formats_are_supported():
    ns = _load_functions(
        "pdf_comparison_source_file_name", "build_pdf_comparison_s3_artifacts",
        "upload_selected_pdf_artifacts_to_s3"
    )
    fake = FakeS3()
    ns["create_aws_client"] = lambda service: fake
    formats = ["FILE_PDF", "FILE_TXT", "FILE_MARKDOWN"]
    artifacts = sum((_artifacts(ns, name) for name in formats), [])
    pdf_rows = ns["upload_selected_pdf_artifacts_to_s3"](artifacts, ["FILE_PDF"])
    assert len(pdf_rows) == 1 and pdf_rows[0]["生成形式"] == "FILE_PDF"
    assert len(fake.calls) == 2
    fake.calls.clear()
    two_rows = ns["upload_selected_pdf_artifacts_to_s3"](
        artifacts, ["FILE_TXT", "FILE_MARKDOWN"]
    )
    assert {row["生成形式"] for row in two_rows} == {"FILE_TXT", "FILE_MARKDOWN"}
    assert len(fake.calls) == 4


def test_sync_starts_only_selected_format():
    ns = _load_functions("run_ingestion_sync")

    class FakeAgent:
        def __init__(self):
            self.started = []

        def start_ingestion_job(self, **kwargs):
            self.started.append(kwargs)
            return {"ingestionJob": {"ingestionJobId": "JOB", "status": "STARTING"}}

        def get_ingestion_job(self, **kwargs):
            return {"ingestionJob": {"status": "COMPLETE"}}

    fake = FakeAgent()
    ns["create_aws_client"] = lambda service: fake
    rows = ns["run_ingestion_sync"]({
        "FILE_MARKDOWN": {"knowledge_base_id": "KB_MD", "data_source_id": "DS_MD"}
    }, 60)
    assert fake.started == [{"knowledgeBaseId": "KB_MD", "dataSourceId": "DS_MD"}]
    assert rows[0]["形式"] == "FILE_MARKDOWN"
    assert rows[0]["ステータス"] == "COMPLETE"
