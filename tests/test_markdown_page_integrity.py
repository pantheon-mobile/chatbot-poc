import ast
import io
import json
import os
import re
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Optional


def _load(*names):
    source = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in names)
        or (isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in {
                "STRICT_PAGE_MARKER", "ESCAPED_PAGE_MARKER", "CODE_FENCE",
                "TEXT_MARKDOWN_PROMPT"
            } for target in node.targets))
    ]
    namespace = {
        "re": re, "Counter": Counter, "Optional": Optional, "time": time,
        "os": os, "json": json,
        "INGESTION_TEST_KB_PREFIXES": {
            "FILE_PDF": "documents/ingestion-test/kb-source/file-pdf/",
            "FILE_TXT": "documents/ingestion-test/kb-source/file-txt/",
            "FILE_MARKDOWN": "documents/ingestion-test/kb-source/file-markdown/",
            "FILE_VISION_MARKDOWN": "documents/ingestion-test/kb-source/file-vision-markdown/",
        },
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


def _pages(count=3):
    return [{"page_number": number, "text": f"input {number}"} for number in range(1, count + 1)]


def test_marker_normalization_is_scoped_and_skips_code_fences():
    ns = _load("normalize_markdown_page_markers")
    source = (
        "  \\\\<!-- page 1 -->\n本文\\_保持\n"
        "```markdown\n\\<!-- page 2 -->\n```\n"
        "\\<!-- page 2 -->\n本文2\n"
    )
    normalized, count = ns["normalize_markdown_page_markers"](source)
    assert normalized.startswith("<!-- page 1 -->")
    assert "本文\\_保持" in normalized
    assert "```markdown\n\\<!-- page 2 -->\n```" in normalized
    assert normalized.endswith("<!-- page 2 -->\n本文2\n")
    assert count == 2


def test_strict_validation_accepts_complete_sixteen_pages():
    ns = _load("_strict_page_marker_matches", "analyze_markdown_page_coverage",
               "validate_markdown_page_coverage")
    markdown = "\n".join(f"<!-- page {number} -->\nbody {number}" for number in range(1, 17))
    metrics = ns["validate_markdown_page_coverage"](markdown, _pages(16))
    assert metrics["page_marker_count"] == 16
    assert metrics["last_page_number"] == 16
    assert metrics["last_page_has_content"] is True


def test_validation_detects_missing_duplicate_order_unexpected_and_empty_last():
    ns = _load("_strict_page_marker_matches", "analyze_markdown_page_coverage")
    analyze = ns["analyze_markdown_page_coverage"]
    missing = analyze("<!-- page 1 -->\na\n<!-- page 3 -->\nc", _pages())
    assert missing["missing_page_numbers"] == [2]
    duplicate = analyze("<!-- page 1 -->\na\n<!-- page 2 -->\nb\n<!-- page 2 -->\nb2\n<!-- page 3 -->\nc", _pages())
    assert duplicate["duplicate_page_numbers"] == [2]
    order = analyze("<!-- page 2 -->\nb\n<!-- page 1 -->\na\n<!-- page 3 -->\nc", _pages())
    assert order["page_marker_order_valid"] is False
    unexpected = analyze("<!-- page 1 -->\na\n<!-- page 2 -->\nb\n<!-- page 3 -->\nc\n<!-- page 4 -->\nd", _pages())
    assert unexpected["unexpected_page_numbers"] == [4]
    empty_last = analyze("<!-- page 1 -->\na\n<!-- page 2 -->\nb\n<!-- page 3 -->", _pages())
    assert empty_last["last_page_has_content"] is False


def test_invalid_marker_variants_are_not_counted():
    ns = _load("_strict_page_marker_matches", "analyze_markdown_page_coverage")
    markdown = "\n".join([
        "\\<!-- page 1 -->", "x<!-- page 1 -->", "<!-- page 1 -->suffix",
        "<!-- page 01 -->", "<!-- Page 1 -->", "<!-- page one -->"
    ])
    metrics = ns["analyze_markdown_page_coverage"](markdown, _pages(1))
    assert metrics["page_marker_count"] == 0


def test_page_preview_tail_zip_and_s3_use_same_text():
    ns = _load(
        "_strict_page_marker_matches", "split_markdown_by_page",
        "pdf_comparison_source_file_name", "build_pdf_comparison_s3_artifacts"
    )
    markdown = "<!-- page 1 -->\nstart\n<!-- page 2 -->\n奨学金理解度チェック"
    page_map = ns["split_markdown_by_page"](markdown)
    assert page_map[2].endswith("奨学金理解度チェック")
    assert "<!-- page 2 -->" in markdown[-5000:]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("sample.md", markdown)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        assert archive.read("sample.md").decode("utf-8") == markdown
    artifacts = ns["build_pdf_comparison_s3_artifacts"](
        "FILE_MARKDOWN", "sample.pdf", markdown,
        {"metadataAttributes": {"datasource_id": "DS"}}, "DS"
    )
    body = next(item for item in artifacts if item["artifact_type"] == "body")["body"]
    assert body.decode("utf-8") == markdown


def test_incomplete_markdown_is_blocked_and_jasso_terms_are_preserved():
    ns = _load("markdown_s3_upload_allowed")
    allowed, reasons = ns["markdown_s3_upload_allowed"]({
        "page_markers_complete": False, "missing_page_numbers": [16],
        "duplicate_page_numbers": [], "last_page_has_content": False,
        "unresolved_max_tokens": True, "empty_page_numbers": [16]
    })
    assert allowed is False and len(reasons) == 5
    text = " ".join([
        "120,000円", "10,000円単位", "機関保証", "人的保証", "7か月目",
        "同年10月", "入学時特別増額貸与奨学金", "奨学金理解度チェック"
    ])
    for term in ["120,000円", "10,000円単位", "機関保証", "人的保証", "7か月目",
                 "同年10月", "入学時特別増額貸与奨学金", "奨学金理解度チェック"]:
        assert term in text


def test_sixteen_page_conversion_normalizes_and_reports_complete_metrics():
    ns = _load(
        "split_extracted_pdf_text_by_page", "build_text_markdown_batches",
        "normalize_markdown_page_markers", "_strict_page_marker_matches",
        "analyze_markdown_page_coverage", "validate_markdown_page_coverage",
        "convert_text_markdown_batch", "convert_pdf_text_to_markdown"
    )

    class FakeBedrock:
        def converse(self, **kwargs):
            prompt = kwargs["messages"][0]["content"][0]["text"]
            numbers = [int(value) for value in re.findall(r"(?m)^--- page (\d+) ---$", prompt)]
            output = "\n".join(
                f"\\<!-- page {number} -->\n"
                + ("奨学金理解度チェック" if number == 16 else f"本文 {number}")
                for number in numbers
            )
            return {
                "stopReason": "end_turn",
                "output": {"message": {"content": [{"text": output}]}}
            }

    ns["create_bedrock_runtime_client"] = lambda: FakeBedrock()
    pdf_text = "\n\n".join(
        f"--- page {number} ---\n\n入力本文 {number}" for number in range(1, 17)
    )
    markdown, metrics = ns["convert_pdf_text_to_markdown"](pdf_text, "model")
    assert metrics["page_count"] == 16
    assert metrics["page_marker_count"] == 16
    assert metrics["page_marker_normalization_count"] == 16
    assert metrics["missing_page_numbers"] == []
    assert metrics["duplicate_page_numbers"] == []
    assert metrics["last_page_number"] == 16
    assert metrics["last_page_has_content"] is True
    assert metrics["page_markers_complete"] is True
    assert all(row["stop_reason"] == "end_turn" for row in metrics["batch_metrics"])
    assert "\\<!-- page" not in markdown
    assert markdown.count("<!-- page ") == 16
    assert "奨学金理解度チェック" in markdown
