import ast
import json
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from web_crawler import (
    WebCrawler,
    WebCrawlTarget,
    build_web_crawl_manifest,
    build_web_crawl_reports,
    compare_web_crawl_manifests,
    extract_web_content,
    make_web_page_id,
    normalize_web_url,
)


class FakeResponse:
    def __init__(self, url, text, status=200, content_type="text/html; charset=utf-8"):
        self.url = url
        self.text = text
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=20):
        self.calls.append(url)
        if url not in self.pages:
            return FakeResponse(url, "not found", 404)
        value = self.pages[url]
        if isinstance(value, tuple):
            return FakeResponse(url, value[0], content_type=value[1])
        return FakeResponse(url, value)


def _html(title, body):
    return (
        f"<html><head><title>{title}</title></head><body>"
        "<header><a href='/noise'>noise</a></header>"
        f"<main><ul><li class='nav-item'><a href='/local-nav'>local nav</a></li></ul>{body}</main>"
        "</body></html>"
    )


def test_normalize_url_removes_fragment_and_tracking_but_keeps_semantic_query():
    normalized = normalize_web_url(
        "/faq/?b=2&utm_source=x&a=1#top", "https://Example.COM/root/index.html"
    )
    assert normalized == "https://example.com/faq/?a=1&b=2"
    assert make_web_page_id(normalized) == make_web_page_id(normalized + "#ignored")


def test_extract_content_preserves_table_and_only_returns_main_links():
    html = _html(
        "奨学金",
        "<h1>制度案内</h1><p>本文です。<a href='/detail'>詳細</a></p>"
        "<table><tr><th>区分</th><th>金額</th></tr><tr><td>第Ⅰ</td><td>75,800円</td></tr></table>"
    )
    text, markdown, title, links = extract_web_content(html, "https://example.com/index.html")
    assert title == "奨学金"
    assert "75,800円" in text
    assert "| 区分 | 金額 |" in markdown
    assert links == ["https://example.com/detail"]
    assert "noise" not in text
    assert "local nav" not in text


def test_crawler_follows_same_host_main_links_with_depth_and_extension_guards():
    pages = {
        "https://example.com/index.html": _html(
            "root", "<p>起点ページ本文です。</p>"
            "<a href='/child'>child</a><a href='https://other.example/x'>external</a>"
            "<a href='/file.pdf'>pdf</a>"
        ),
        "https://example.com/child": _html(
            "child", "<p>子ページの本文です。</p><a href='/grandchild'>grandchild</a>"
        ),
        "https://example.com/grandchild": _html("grandchild", "<p>孫ページの本文です。</p>"),
    }
    session = FakeSession(pages)
    crawler = WebCrawler(interval=0.5, respect_robots=False, session=session)
    # テストでは待機を発生させない。
    crawler.interval = 0
    result = crawler.crawl([WebCrawlTarget("https://example.com/index.html", 1, 10)])

    assert [page.source_url for page in result.pages] == [
        "https://example.com/index.html", "https://example.com/child"
    ]
    reasons = {row.reason for row in result.skipped}
    assert "different_host" in reasons
    assert "unsupported_extension" in reasons
    assert "max_depth" in reasons
    assert "https://example.com/noise" not in session.calls


def test_manifest_detects_new_updated_unchanged_and_removed():
    pages = {
        "https://example.com/index.html": _html("root", "<p>起点ページに掲載されている十分な長さの本文です。</p><a href='/child'>child</a>"),
        "https://example.com/child": _html("child", "<p>子ページに掲載されている十分な長さの本文です。</p>"),
    }
    crawler = WebCrawler(interval=0.5, respect_robots=False, session=FakeSession(pages))
    crawler.interval = 0
    result = crawler.crawl([WebCrawlTarget("https://example.com/index.html", 1, 10)])
    current = build_web_crawl_manifest(result)
    ids = list(current["items"])
    previous = {"items": {
        ids[0]: {**current["items"][ids[0]]},
        ids[1]: {**current["items"][ids[1]], "content_hash": "old"},
        "web_removed": {"source_url": "https://example.com/old", "content_hash": "x"},
    }}
    statuses, removed = compare_web_crawl_manifests(current, previous)

    assert statuses[ids[0]] == "unchanged"
    assert statuses[ids[1]] == "updated"
    assert removed[0]["page_id"] == "web_removed"
    reports = build_web_crawl_reports(result, previous)
    assert reports["report"].startswith(b"\xef\xbb\xbf")
    assert b"web_removed" in reports["deleted"]


def _load_app_functions(*names):
    source = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "json": json,
        "datetime": datetime,
        "time": time,
        "urlparse": __import__("urllib.parse", fromlist=["urlparse"]).urlparse,
        "INGESTION_TEST_KB_PREFIXES": {
            "WEB_TXT": "documents/ingestion-test/kb-source/web-txt/",
            "WEB_MARKDOWN": "documents/ingestion-test/kb-source/web-markdown/",
        },
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


def test_web_artifacts_use_stable_page_keys_and_jasso_high_authority():
    ns = _load_app_functions(
        "remove_empty_metadata_attributes", "build_ingestion_metadata",
        "build_web_crawl_artifacts"
    )
    page = SimpleNamespace(
        page_id="web_fixed", source_url="https://www.jasso.go.jp/faq/detail.html",
        root_url="https://www.jasso.go.jp/index.html", parent_url="https://www.jasso.go.jp/faq/",
        depth=2, text="本文", markdown="# 本文", title="FAQ", content_hash="hash",
        crawled_at="2026-08-29T10:00:00+09:00"
    )
    reports = {"manifest_data": {"crawler_version": "web-crawler-v1"}, "manifest": b"{}",
               "report": b"", "errors": b"", "skipped": b"", "deleted": b""}
    artifacts, metadata = ns["build_web_crawl_artifacts"](
        "DS_RUN", [page], {"priority": "medium"}, ("WEB_TXT", "WEB_MARKDOWN"), reports
    )
    kb_keys = [row["key"] for row in artifacts if row["role"] == "KB同期用コピー"]
    assert "documents/ingestion-test/kb-source/web-txt/web_fixed.txt" in kb_keys
    assert "documents/ingestion-test/kb-source/web-markdown/web_fixed.md" in kb_keys
    attrs = metadata["web_fixed"]["WEB_TXT"]["metadataAttributes"]
    assert attrs["source_url"] == page.source_url
    assert attrs["crawl_depth"] == 2
    assert attrs["source_authority"] == "high"
    assert attrs["priority"] == "high"


def test_web_upload_updates_stable_keys_and_continues_after_failure():
    ns = _load_app_functions("upload_web_crawl_artifacts_to_s3")

    class FakeS3:
        def __init__(self):
            self.calls = []

        def put_object(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["Key"].endswith("failed.txt"):
                raise RuntimeError("simulated failure")

    fake = FakeS3()
    ns["create_aws_client"] = lambda service: fake
    artifacts = [
        {"datasource_id": "DS", "format": "WEB_TXT", "role": "KB同期用コピー",
         "key": "documents/ingestion-test/kb-source/web-txt/failed.txt",
         "body": b"bad", "content_type": "text/plain"},
        {"datasource_id": "DS", "format": "WEB_TXT", "role": "KB同期用コピー",
         "key": "documents/ingestion-test/kb-source/web-txt/good.txt",
         "body": b"good", "content_type": "text/plain"},
    ]
    rows = ns["upload_web_crawl_artifacts_to_s3"](artifacts, "bucket")

    assert len(fake.calls) == 2
    assert rows[0]["アップロード結果"] == "失敗"
    assert rows[1]["アップロード結果"] == "成功"
    assert "IfNoneMatch" not in fake.calls[1]
