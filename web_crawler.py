from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


WEB_CRAWLER_VERSION = "web-crawler-v2"
USER_AGENT = "ScholarshipWebCrawler/1.0 (authorized institutional use)"
SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "data:")
SKIP_EXTENSIONS = re.compile(
    r"\.(?:pdf|docx?|xlsx?|xls|pptx?|jpe?g|png|gif|svg|webp|zip|rar|7z|mp3|mp4|mov|avi)(?:$|\?)",
    re.IGNORECASE,
)
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "ref", "referrer",
}
NOISE_SELECTORS = (
    "header", "footer", "nav", "menu", "aside", "script", "style", "form", "iframe",
    "[role='navigation']", "[role='banner']", "[role='contentinfo']",
    "[aria-label*='breadcrumb' i]", ".breadcrumb", ".breadcrumbs", ".cookie",
    ".cookie-banner", ".sidebar", ".side-bar", ".advertisement", ".ads",
    ".social", ".share", ".nav-item", ".local-nav", ".sub-nav", ".side-nav",
    "#cookie", "#sidebar",
)


@dataclass(frozen=True)
class WebCrawlTarget:
    root_url: str
    max_depth: int = 3
    max_pages: int = 100
    allowed_path_prefix: str = ""


@dataclass
class WebCrawlPage:
    page_id: str
    root_url: str
    source_url: str
    parent_url: str
    depth: int
    title: str
    text: str
    markdown: str
    content_hash: str
    crawled_at: str
    http_status: int = 200
    content_type: str = "text/html"
    elapsed_ms: float = 0.0


@dataclass
class WebCrawlLog:
    event: str
    url: str
    root_url: str
    depth: int
    reason: str = ""
    parent_url: str = ""


@dataclass
class WebCrawlResult:
    pages: list[WebCrawlPage] = field(default_factory=list)
    errors: list[WebCrawlLog] = field(default_factory=list)
    skipped: list[WebCrawlLog] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    crawler_version: str = WEB_CRAWLER_VERSION


ProgressCallback = Callable[[dict], None]


def normalize_web_url(url: str, base_url: str = "") -> str:
    raw = (url or "").strip()
    if not raw or raw.lower().startswith(SKIP_SCHEMES) or raw.startswith("#"):
        return ""
    absolute = urljoin(base_url, raw)
    parts = urlsplit(absolute)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    query = urlencode(sorted(
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
    ))
    return urlunsplit((parts.scheme.lower(), host + port, path, query, ""))


def make_web_page_id(url: str) -> str:
    return "web_" + hashlib.sha256(normalize_web_url(url).encode("utf-8")).hexdigest()[:20]


def _table_to_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [
            re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("|", "\\|")
            for cell in tr.find_all(["th", "td"])
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return "\n".join([
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
        *("| " + " | ".join(row) + " |" for row in rows[1:]),
    ])


def _element_to_markdown(element: Tag, base_url: str) -> str:
    name = element.name.lower()
    if re.fullmatch(r"h[1-6]", name):
        return f"{'#' * int(name[1])} {element.get_text(' ', strip=True)}"
    if name == "p":
        pieces: list[str] = []
        for child in element.descendants:
            if not isinstance(child, NavigableString) or child.parent.name in {"script", "style"}:
                continue
            if child.parent.name == "a" and child.parent.get("href"):
                if child is next(iter(child.parent.children), None):
                    label = child.parent.get_text(" ", strip=True)
                    href = normalize_web_url(child.parent["href"], base_url)
                    pieces.append(f"[{label}]({href})" if href else label)
            elif child.find_parent("a") is None:
                pieces.append(str(child))
        return re.sub(r"\s+", " ", "".join(pieces)).strip()
    if name in {"ul", "ol"}:
        lines = []
        for index, li in enumerate(element.find_all("li", recursive=False), start=1):
            prefix = f"{index}." if name == "ol" else "-"
            lines.append(f"{prefix} {li.get_text(' ', strip=True)}")
        return "\n".join(lines)
    if name == "table":
        return _table_to_markdown(element)
    return ""


def extract_web_content(html: str, url: str) -> tuple[str, str, str, list[str]]:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for selector in NOISE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    root = soup.find("main") or soup.find("article") or soup.body
    if not root:
        raise ValueError("HTMLから本文領域を特定できませんでした。")
    h1 = root.find("h1")
    original_title = title or (h1.get_text(" ", strip=True) if h1 else "")
    plain_text = root.get_text("\n", strip=True)
    if len(plain_text) < 20:
        raise ValueError("Webページから本文を抽出できませんでした。")

    blocks = []
    if original_title:
        blocks.append(f"# {original_title}")
    blocks.append(f"元URL: {url}")
    for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table"]):
        if element.find_parent(["ul", "ol", "table"]):
            continue
        block = _element_to_markdown(element, url)
        if block:
            blocks.append(block)
    markdown = "\n\n".join(blocks).strip()
    text = f"元URL: {url}\n\n{plain_text}"

    links = []
    seen = set()
    for anchor in root.find_all("a", href=True):
        child = normalize_web_url(anchor.get("href", ""), url)
        if child and child not in seen:
            seen.add(child)
            links.append(child)
    return text, markdown, original_title, links


def _same_host(url: str, root_url: str) -> bool:
    return urlsplit(url).hostname == urlsplit(root_url).hostname


def resolve_allowed_path_prefix(root_url: str, configured_prefix: str = "") -> str:
    """起点URLから、同一ホスト内で追跡してよいパス範囲を決定する。"""
    configured = (configured_prefix or "").strip()
    if configured:
        path = urlsplit(normalize_web_url(configured, root_url)).path
    else:
        path = urlsplit(root_url).path or "/"
        if not path.endswith("/"):
            last_segment = path.rsplit("/", 1)[-1]
            if "." in last_segment:
                path = path.rsplit("/", 1)[0] + "/"
    path = re.sub(r"/{2,}", "/", path or "/")
    return path if path == "/" or path.endswith("/") else path + "/"


def _within_path_scope(url: str, allowed_path_prefix: str) -> bool:
    path = urlsplit(url).path or "/"
    if allowed_path_prefix == "/":
        return True
    scope_root = allowed_path_prefix.rstrip("/")
    return path == scope_root or path.startswith(allowed_path_prefix)


class WebCrawler:
    def __init__(self, interval: float = 1.0, timeout: float = 20.0,
                 respect_robots: bool = True, session: requests.Session | None = None):
        self.interval = max(float(interval), 0.5)
        self.timeout = float(timeout)
        self.respect_robots = respect_robots
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0
        self._robots: dict[str, RobotFileParser | None] = {}

    def _request(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            wait = self.interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.get(url, timeout=self.timeout)
                self._last_request = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After", "")
                    time.sleep(float(retry_after) if retry_after.isdigit() else 2 ** attempt)
                    continue
                response.raise_for_status()
                response.encoding = response.apparent_encoding or response.encoding
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Webページの取得に失敗しました: {url}") from last_error

    def _robot_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            parser.set_url(origin + "/robots.txt")
            try:
                parser.read()
                self._robots[origin] = parser
            except Exception:
                # robots.txtが取得不能でも通常ページ取得を妨げず、サーバー側のHTTP応答に従う。
                self._robots[origin] = None
        parser = self._robots[origin]
        return parser.can_fetch(USER_AGENT, url) if parser else True

    def crawl(self, targets: Iterable[WebCrawlTarget], progress: ProgressCallback = None) -> WebCrawlResult:
        result = WebCrawlResult(started_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        globally_visited: set[str] = set()
        for raw_target in targets:
            root_url = normalize_web_url(raw_target.root_url)
            if not root_url:
                result.errors.append(WebCrawlLog("invalid_root", raw_target.root_url, "", 0, "無効な起点URL"))
                continue
            allowed_path_prefix = resolve_allowed_path_prefix(
                root_url, raw_target.allowed_path_prefix
            )
            pending = deque([(root_url, "", 0)])
            seen_candidates: set[str] = set()
            root_count = 0
            while pending and root_count < raw_target.max_pages:
                url, parent_url, depth = pending.popleft()
                if url in seen_candidates:
                    continue
                seen_candidates.add(url)
                if not _same_host(url, root_url):
                    result.skipped.append(WebCrawlLog("skipped", url, root_url, depth, "different_host", parent_url))
                    continue
                if not _within_path_scope(url, allowed_path_prefix):
                    result.skipped.append(WebCrawlLog(
                        "skipped", url, root_url, depth, "outside_path_scope", parent_url
                    ))
                    continue
                if SKIP_EXTENSIONS.search(urlsplit(url).path):
                    result.skipped.append(WebCrawlLog("skipped", url, root_url, depth, "unsupported_extension", parent_url))
                    continue
                if depth > raw_target.max_depth:
                    result.skipped.append(WebCrawlLog("skipped", url, root_url, depth, "max_depth", parent_url))
                    continue
                if not self._robot_allowed(url):
                    result.skipped.append(WebCrawlLog("skipped", url, root_url, depth, "robots_disallowed", parent_url))
                    continue
                if url in globally_visited:
                    continue
                globally_visited.add(url)
                if progress:
                    progress({"phase": "Webページ取得中", "root_url": root_url, "url": url,
                              "depth": depth, "count": len(result.pages), "errors": len(result.errors)})
                started = time.perf_counter()
                try:
                    response = self._request(url)
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "html" not in content_type:
                        result.skipped.append(WebCrawlLog("skipped", url, root_url, depth, "non_html", parent_url))
                        continue
                    text, markdown, title, links = extract_web_content(response.text, url)
                    content_hash = hashlib.sha256((text + "\n" + markdown).encode("utf-8")).hexdigest()
                    result.pages.append(WebCrawlPage(
                        page_id=make_web_page_id(url), root_url=root_url, source_url=url,
                        parent_url=parent_url, depth=depth, title=title, text=text,
                        markdown=markdown, content_hash=content_hash,
                        crawled_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                        http_status=response.status_code, content_type=content_type,
                        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                    ))
                    root_count += 1
                    for child_url in links:
                        if child_url not in globally_visited:
                            pending.append((child_url, url, depth + 1))
                except Exception as exc:
                    result.errors.append(WebCrawlLog("error", url, root_url, depth, str(exc), parent_url))
                    if progress:
                        progress({"phase": "Webページ取得エラー", "root_url": root_url, "url": url,
                                  "depth": depth, "count": len(result.pages), "errors": len(result.errors)})
            remaining_in_scope = any(
                candidate_url not in globally_visited
                and _same_host(candidate_url, root_url)
                and _within_path_scope(candidate_url, allowed_path_prefix)
                and not SKIP_EXTENSIONS.search(urlsplit(candidate_url).path)
                and candidate_depth <= raw_target.max_depth
                for candidate_url, _, candidate_depth in pending
            )
            if remaining_in_scope and root_count >= raw_target.max_pages:
                result.skipped.append(WebCrawlLog(
                    "limit_reached", root_url, root_url, 0,
                    f"max_pages_reached:{raw_target.max_pages}", ""
                ))
        result.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return result


def build_web_crawl_manifest(result: WebCrawlResult) -> dict:
    return {
        "schema_version": "1.0", "crawler_version": result.crawler_version,
        "started_at": result.started_at, "finished_at": result.finished_at,
        "items": {
            page.page_id: {
                "source_url": page.source_url, "root_url": page.root_url,
                "content_hash": page.content_hash, "title": page.title,
                "depth": page.depth, "crawled_at": page.crawled_at,
            }
            for page in result.pages
        },
    }


def compare_web_crawl_manifests(current: dict, previous: dict | None) -> tuple[dict[str, str], list[dict]]:
    current_items = current.get("items", {})
    previous_items = (previous or {}).get("items", {})
    statuses = {}
    for page_id, item in current_items.items():
        old = previous_items.get(page_id)
        statuses[page_id] = "new" if old is None else (
            "unchanged" if old.get("content_hash") == item.get("content_hash") else "updated"
        )
    removed = [
        {"page_id": page_id, **item}
        for page_id, item in previous_items.items() if page_id not in current_items
    ]
    return statuses, removed


def _csv_bytes(rows: list[dict], fieldnames: list[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def build_web_crawl_reports(result: WebCrawlResult, previous_manifest: dict | None = None) -> dict:
    manifest = build_web_crawl_manifest(result)
    statuses, removed = compare_web_crawl_manifests(manifest, previous_manifest)
    report_rows = [
        {
            "page_id": page.page_id, "status": statuses[page.page_id],
            "root_url": page.root_url, "source_url": page.source_url,
            "parent_url": page.parent_url, "depth": page.depth, "title": page.title,
            "text_characters": len(page.text), "markdown_characters": len(page.markdown),
            "content_hash": page.content_hash, "http_status": page.http_status,
            "elapsed_ms": page.elapsed_ms, "crawled_at": page.crawled_at,
        }
        for page in result.pages
    ]
    log_fields = ["event", "url", "root_url", "parent_url", "depth", "reason"]
    return {
        "manifest": json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        "manifest_data": manifest, "statuses": statuses, "removed": removed,
        "report": _csv_bytes(report_rows, [
            "page_id", "status", "root_url", "source_url", "parent_url", "depth",
            "title", "text_characters", "markdown_characters", "content_hash",
            "http_status", "elapsed_ms", "crawled_at",
        ]),
        "errors": _csv_bytes([asdict(row) for row in result.errors], log_fields),
        "skipped": _csv_bytes([asdict(row) for row in result.skipped], log_fields),
        "deleted": _csv_bytes(removed, ["page_id", "source_url", "root_url", "content_hash", "title", "depth", "crawled_at"]),
    }
