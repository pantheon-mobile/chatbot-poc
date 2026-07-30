import json

from jasso_exporter import build_outputs, classify_items, metadata_dict, removed_candidates, render_txt
from jasso_models import CrawlResult, JassoFAQ


def faq(qa_id="jasso_1", content_hash="hash", year=2026):
    return JassoFAQ(
        qa_id, "質問ですか。", "回答です。", "https://www.jasso.go.jp/faq/1.html",
        "予約採用", "通知", "予約採用 > 通知", "2026年4月更新", year, 4,
        "2026-07-30T19:45:00+09:00", content_hash,
    )


def test_txt_and_metadata_format():
    item = faq()
    text = render_txt(item)
    assert text.startswith("# 【分類：通知】質問ですか。")
    assert "## 質問" in text and "## 回答" in text and "## 属性・タグ" in text
    attrs = metadata_dict(item)["metadataAttributes"]
    assert {x: attrs[x] for x in ("document_type", "category", "user_type", "qa_id")} == {
        "document_type": "QA", "category": "通知", "user_type": "all", "qa_id": "jasso_1"
    }


def test_diff_statuses_and_removed():
    previous = {"items": {
        "jasso_1": {"qa_id": "jasso_1", "content_hash": "hash",
                    "source_updated_year": 2026, "source_updated_month": 4},
        "jasso_old": {"qa_id": "jasso_old", "content_hash": "old"},
    }}
    assert classify_items([faq()], previous)["jasso_1"] == "unchanged"
    assert classify_items([faq(content_hash="changed")], previous)["jasso_1"] == "updated"
    assert classify_items([faq("jasso_new")], previous)["jasso_new"] == "new"
    assert removed_candidates([faq()], previous)[0]["qa_id"] == "jasso_old"


def test_build_outputs_has_manifest_and_only_pairs_in_zip():
    outputs = build_outputs(CrawlResult("https://www.jasso.go.jp/faq/", [faq()]), None, False)
    manifest = json.loads(outputs["manifest"])
    assert "jasso_1" in manifest["items"]
