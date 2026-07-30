from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime

from jasso_models import CrawlResult, JassoFAQ


def render_txt(faq: JassoFAQ) -> str:
    category = faq.sub_category or faq.top_category or "未分類"
    tags = ", ".join(x for x in ["JASSO", faq.top_category, faq.sub_category] if x)
    return (
        f"# 【分類：{category}】{faq.question.strip()}\n\n"
        f"## 質問\n{faq.question.strip()}\n\n"
        f"## 回答\n{faq.answer.strip()}\n\n"
        f"## 属性・タグ\n- タグ: {tags}\n- 対象者: all\n"
    )


def metadata_dict(faq: JassoFAQ) -> dict:
    return {"metadataAttributes": {
        "document_type": "QA", "category": faq.sub_category or faq.top_category or "未分類",
        "user_type": "all", "qa_id": faq.qa_id, "source": "JASSO",
        "source_url": faq.source_url, "category_path": faq.category_path,
        "source_updated_text": faq.source_updated_text,
        "source_updated_year": faq.source_updated_year,
        "source_updated_month": faq.source_updated_month,
        "crawled_at": faq.crawled_at, "content_hash": faq.content_hash,
    }}


def classify_items(faqs: list[JassoFAQ], previous: dict | None) -> dict[str, str]:
    old = (previous or {}).get("items", {})
    statuses = {}
    for faq in faqs:
        prior = old.get(faq.qa_id)
        if not prior:
            statuses[faq.qa_id] = "new"
        elif prior.get("content_hash") != faq.content_hash:
            statuses[faq.qa_id] = "updated"
        elif (faq.source_updated_year, faq.source_updated_month) > (
            int(prior.get("source_updated_year", 0)), int(prior.get("source_updated_month", 0))
        ):
            statuses[faq.qa_id] = "updated"
        else:
            statuses[faq.qa_id] = "unchanged"
    return statuses


def removed_candidates(faqs: list[JassoFAQ], previous: dict | None) -> list[dict]:
    current = {x.qa_id for x in faqs}
    return [item for key, item in (previous or {}).get("items", {}).items() if key not in current]


def build_outputs(result: CrawlResult, previous: dict | None, diff_only: bool) -> dict:
    statuses = classify_items(result.faqs, previous)
    removed = removed_candidates(result.faqs, previous)
    generated_at = result.faqs[0].crawled_at if result.faqs else datetime.now().astimezone().replace(microsecond=0).isoformat()
    items = {}
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for faq in result.faqs:
            txt_name = f"qa_{faq.qa_id}.txt"
            meta_name = f"{txt_name}.metadata.json"
            if not diff_only or statuses[faq.qa_id] in ("new", "updated"):
                archive.writestr(txt_name, render_txt(faq).encode("utf-8"))
                archive.writestr(meta_name, json.dumps(metadata_dict(faq), ensure_ascii=False, indent=2).encode("utf-8"))
            items[faq.qa_id] = {
                "qa_id": faq.qa_id, "source_url": faq.source_url,
                "category": faq.sub_category or faq.top_category, "category_path": faq.category_path,
                "source_updated_text": faq.source_updated_text,
                "source_updated_year": faq.source_updated_year,
                "source_updated_month": faq.source_updated_month,
                "content_hash": faq.content_hash, "txt_file": txt_name,
                "metadata_file": meta_name, "last_crawled_at": faq.crawled_at,
            }
    manifest = {"generated_at": generated_at, "source": "JASSO",
                "source_root_url": result.source_root_url, "items": items}
    report_rows = [{
        "status": statuses[x.qa_id], "qa_id": x.qa_id, "question": x.question,
        "category": x.sub_category or x.top_category, "category_path": x.category_path,
        "source_url": x.source_url, "source_updated_text": x.source_updated_text,
        "content_hash": x.content_hash, "message": "",
    } for x in result.faqs]
    report_rows += [{"status": "error", "qa_id": "", "question": "", "category": "",
                     "category_path": e.category_path, "source_url": e.url,
                     "source_updated_text": "", "content_hash": "", "message": e.message}
                    for e in result.errors]
    report_rows += [{"status": "removed_candidate", "qa_id": x.get("qa_id", ""),
                     "question": "", "category": x.get("category", ""),
                     "category_path": x.get("category_path", ""), "source_url": x.get("source_url", ""),
                     "source_updated_text": x.get("source_updated_text", ""),
                     "content_hash": x.get("content_hash", ""), "message": "前回存在したURLが今回見つかりませんでした。"}
                    for x in removed]
    return {
        "zip": zip_buffer.getvalue(), "manifest": json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
        "report": _csv(report_rows), "deleted": _csv([{
            "qa_id": x.get("qa_id", ""), "source_url": x.get("source_url", ""),
            "category": x.get("category", ""), "category_path": x.get("category_path", ""),
            "previous_content_hash": x.get("content_hash", ""),
            "previous_crawled_at": x.get("last_crawled_at", "")} for x in removed]),
        "errors": _csv([{"url": e.url, "category_path": e.category_path, "message": e.message}
                        for e in result.errors]), "statuses": statuses, "removed": removed,
    }


def _csv(rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")
