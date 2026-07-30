from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, Tag

from jasso_models import CrawlError, CrawlPage, CrawlResult, FAQLink, JassoFAQ, ProgressCallback
from jasso_utils import (
    extract_update, is_allowed_jasso_url, make_content_hash, make_qa_id,
    normalize_multiline, normalize_text, normalize_url, now_jst, strip_update,
)

LOGIN_URL = "https://www.jasso.go.jp/tantosha_login.html"
SCHOOL_LINK = "大学・大学院・短大・高専・専修学校 専門課程"
FAQ_LINK = "よくあるご質問"


@dataclass(frozen=True)
class JassoSelectors:
    main_content: tuple[str, ...] = ("main", "article", "[role=main]", "#main", ".main")
    breadcrumb: tuple[str, ...] = (
        "nav[aria-label*=パンくず]", ".breadcrumb", "#breadcrumb", "[class*=topicpath]"
    )
    question_block: tuple[str, ...] = (
        "[itemprop=name]", ".p-faq-q", "[class*=faq-q]",
        ".question", ".faq-question", "[class*=question]", "[id*=question]"
    )
    answer_block: tuple[str, ...] = (
        "[itemprop=acceptedAnswer]", ".p-faq-a", "[class*=faq-a]",
        ".answer", ".faq-answer", "[class*=answer]", "[id*=answer]"
    )


SELECTORS = JassoSelectors()


def _main(soup: BeautifulSoup) -> Tag:
    for selector in SELECTORS.main_content:
        found = soup.select_one(selector)
        if found:
            return found
    return soup.body or soup


def _visible_links(container: Tag, base_url: str) -> list[tuple[str, str]]:
    result = []
    for anchor in container.find_all("a", href=True):
        text = normalize_text(anchor.get_text(" ", strip=True))
        url = normalize_url(anchor.get("href", ""), base_url)
        if text and url:
            result.append((text, url))
    return result


def _find_link(soup: BeautifulSoup, text: str, base_url: str) -> str:
    target = normalize_text(text)
    candidates = _visible_links(_main(soup), base_url) or _visible_links(soup, base_url)
    exact = [url for label, url in candidates if normalize_text(label) == target]
    partial = [url for label, url in candidates if target in normalize_text(label)]
    return (exact or partial or [""])[0]


def _heading_category_path(soup: BeautifulSoup, fallback: tuple[str, ...]) -> tuple[str, ...]:
    path = []
    for selector in SELECTORS.breadcrumb:
        node = soup.select_one(selector)
        if node:
            crumbs = [normalize_text(x.get_text(" ", strip=True)) for x in node.find_all(["a", "span", "li"])]
            path = [x for x in crumbs if x and x not in ("ホーム", SCHOOL_LINK, FAQ_LINK)]
            break
    return tuple(path[-2:]) if len(path) >= 2 else fallback


def parse_faq_links(html: str, page_url: str, category_path: tuple[str, ...]) -> list[FAQLink]:
    soup = BeautifulSoup(html, "lxml")
    output = []
    seen = set()
    for text, url in _visible_links(_main(soup), page_url):
        clean = re.sub(r"^\s*Q[\s:：]*", "", text, flags=re.I)
        updated_text, year, month = extract_update(clean)
        question = strip_update(clean)
        # JASSO FAQ questions are explicitly prefixed Q; href patterns are only a fallback.
        looks_like_q = bool(re.match(r"^\s*Q(?:\s|[:：])", text, re.I))
        path = urlsplit(url).path
        # Current authenticated pages omit the visible "Q" prefix. Their detail
        # pages use a numeric content ID filename; category/list pages are index.html.
        looks_like_detail = bool(
            re.search(r"/\d+_\d+\.html$", path, re.I)
            or re.search(r"/(?:detail|question|qa)[^/]*\.html$", path, re.I)
        )
        if url not in seen and question and (looks_like_q or looks_like_detail):
            seen.add(url)
            output.append(FAQLink(url, question, category_path, updated_text, year, month))
    return output


def parse_faq_json(value: str | dict, page_url: str,
                   category_path: tuple[str, ...]) -> list[FAQLink]:
    payload = json.loads(value) if isinstance(value, str) else value
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    output = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = normalize_url(str(row.get("url", "")), page_url)
        displayed = normalize_text(str(row.get("title", "")))
        if not url or url in seen or not displayed:
            continue
        seen.add(url)
        updated_text, year, month = extract_update(displayed)
        output.append(FAQLink(
            url=url, question=strip_update(displayed), category_path=category_path,
            source_updated_text=updated_text, source_updated_year=year,
            source_updated_month=month,
        ))
    return output


def _node_text(node: Tag, base_url: str) -> str:
    clone = BeautifulSoup(str(node), "lxml")
    for unwanted in clone.select("script,style,noscript,nav,footer,form,button,.breadcrumb,[class*=sidebar]"):
        unwanted.decompose()
    for anchor in clone.find_all("a", href=True):
        label = normalize_text(anchor.get_text(" ", strip=True))
        url = normalize_url(anchor["href"], base_url)
        anchor.replace_with(f"{label}（{url}）" if label and url and not url.startswith(base_url + "#") else label)
    for row in clone.find_all("tr"):
        cells = [normalize_text(x.get_text(" ", strip=True)) for x in row.find_all(["th", "td"])]
        row.replace_with(" | ".join(cells) + "\n")
    for li in clone.find_all("li"):
        li.insert_before("- ")
        li.append("\n")
    for block in clone.find_all(["p", "div", "section", "h1", "h2", "h3", "h4", "br"]):
        block.append("\n")
    return normalize_multiline(clone.get_text("\n"))


def _labelled_block(main: Tag, label: str) -> Tag | None:
    label_re = re.compile(rf"^\s*{re.escape(label)}\s*[：:]?\s*$", re.I)
    marker = main.find(lambda tag: isinstance(tag, Tag) and tag.name in ("h1", "h2", "h3", "h4", "dt", "div", "span", "p")
                       and label_re.match(normalize_text(tag.get_text(" ", strip=True))))
    if not marker:
        return None
    sibling = marker.find_next_sibling()
    return sibling if isinstance(sibling, Tag) else marker.parent


def parse_detail(html: str, url: str, link: FAQLink) -> JassoFAQ:
    soup = BeautifulSoup(html, "lxml")
    main = _main(soup)
    q_node = next((main.select_one(x) for x in SELECTORS.question_block if main.select_one(x)), None)
    a_node = next((main.select_one(x) for x in SELECTORS.answer_block if main.select_one(x)), None)
    q_node = q_node or _labelled_block(main, "Q")
    a_node = a_node or _labelled_block(main, "A")
    question = strip_update(_node_text(q_node, url)) if q_node else link.question
    answer = _node_text(a_node, url) if a_node else ""
    question = re.sub(r"^\s*Q\s*[：:]?\s*", "", question, flags=re.I)
    answer = re.sub(r"^\s*A\s*[：:]?\s*", "", answer, flags=re.I)
    if not question or not answer:
        raise ValueError("Q本文またはA本文を特定できませんでした。")
    category_parts = _heading_category_path(soup, link.category_path)
    # Breadcrumb can include the question as its last item.
    if category_parts and normalize_text(category_parts[-1]) == normalize_text(question):
        category_parts = category_parts[:-1]
    category_parts = category_parts[-2:]
    top = category_parts[0] if category_parts else ""
    sub = category_parts[-1] if category_parts else ""
    normalized = normalize_url(url)
    return JassoFAQ(
        qa_id=make_qa_id(normalized), question=normalize_text(question),
        answer=normalize_multiline(answer), source_url=normalized,
        top_category=top, sub_category=sub, category_path=" > ".join(category_parts),
        source_updated_text=link.source_updated_text,
        source_updated_year=link.source_updated_year,
        source_updated_month=link.source_updated_month, crawled_at=now_jst(),
        content_hash=make_content_hash(question, answer),
        breadcrumb=list(category_parts),
    )


class JassoCrawler:
    def __init__(self, user_id: str, password: str, interval: float = 1.0,
                 timeout: float = 30.0, debug_dir: str | None = None):
        self.user_id, self.password = user_id, password
        self.interval, self.timeout = max(interval, .5), timeout
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ScholarshipFAQCrawler/1.0 (authorized institutional use)"
        self.cache: dict[str, str] = {}
        self._last_request = 0.0
        self._reauthenticated = False

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_error = None
        for attempt in range(3):
            wait = self.interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                self._last_request = time.monotonic()
                if response.status_code in (401, 403):
                    raise PermissionError(f"JASSOセッションが無効です（HTTP {response.status_code}）。")
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt)
                    continue
                response.raise_for_status()
                response.encoding = response.apparent_encoding or response.encoding
                return response
            except PermissionError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"JASSOページの取得に失敗しました: {url}") from last_error

    def login(self) -> tuple[str, str]:
        response = self._request("GET", LOGIN_URL)
        soup = BeautifulSoup(response.text, "lxml")
        # The page also contains a site-search form before the login form.
        # Select by the semantic presence of a password control, not by position.
        form = next(
            (candidate for candidate in soup.find_all("form")
             if candidate.find("input", {"type": lambda value: (value or "").lower() == "password"})),
            None,
        )
        if not form:
            raise RuntimeError("JASSOログインフォームが見つかりませんでした。")
        payload = {x.get("name"): x.get("value", "") for x in form.find_all("input", type="hidden") if x.get("name")}
        password_input = form.find("input", {"type": "password"})
        user_input = form.find("input", {"type": re.compile(r"^(?:text|email)$", re.I)})
        if not user_input:
            user_input = form.find("input", attrs={"name": re.compile(r"(?:user|login|id)", re.I)})
        if not user_input or not password_input or not user_input.get("name") or not password_input.get("name"):
            raise RuntimeError("JASSOログイン入力欄を特定できませんでした。")
        payload[user_input["name"]] = self.user_id
        payload[password_input["name"]] = self.password
        for submit in form.find_all(["input", "button"]):
            submit_type = (submit.get("type") or "").lower()
            if submit_type == "submit" and submit.get("name"):
                payload[submit["name"]] = submit.get("value", "")
        action = urljoin(response.url, form.get("action") or response.url)
        logged_in = self._request((form.get("method") or "post").upper(), action, data=payload)
        login_payload = None
        try:
            login_payload = logged_in.json()
        except (requests.JSONDecodeError, ValueError):
            pass
        if isinstance(login_payload, dict):
            if not login_payload.get("success") or not login_payload.get("url"):
                raise RuntimeError(
                    "JASSOへのログインを確認できませんでした。"
                    "ID、パスワード、ログイン画面の変更を確認してください。"
                )
            landing_url = normalize_url(str(login_payload["url"]), logged_in.url)
            if urlsplit(landing_url).hostname not in ("www.jasso.go.jp", "www2.jasso.go.jp"):
                raise RuntimeError("JASSOログイン後の遷移先ドメインを確認できませんでした。")
            logged_in = self._request("GET", landing_url)
        school_url = _find_link(BeautifulSoup(logged_in.text, "lxml"), SCHOOL_LINK, logged_in.url)
        if not school_url:
            raise RuntimeError("JASSOへのログインを確認できませんでした。ID、パスワード、ログイン画面の変更を確認してください。")
        school = self._request("GET", school_url)
        faq_url = _find_link(BeautifulSoup(school.text, "lxml"), FAQ_LINK, school.url)
        if not faq_url:
            raise RuntimeError("ログイン後ページから「よくあるご質問」を確認できませんでした。")
        return faq_url, school_url

    def connection_test(self) -> str:
        faq_url, _ = self.login()
        return faq_url

    def _get(self, url: str) -> str:
        if url not in self.cache:
            try:
                self.cache[url] = self._request("GET", url).text
            except PermissionError:
                if self._reauthenticated:
                    raise RuntimeError("JASSOセッションを再確立できませんでした。")
                self._reauthenticated = True
                self.login()
                self.cache[url] = self._request("GET", url).text
        return self.cache[url]

    def crawl(self, progress: ProgressCallback = None) -> CrawlResult:
        root_url, _ = self.login()
        root_url = normalize_url(root_url)
        result = CrawlResult(source_root_url=root_url)
        pending = deque([CrawlPage(root_url)])
        visited_pages, detail_urls = set(), set()
        while pending:
            page = pending.popleft()
            url = normalize_url(page.url)
            if url in visited_pages or not is_allowed_jasso_url(url, root_url):
                continue
            visited_pages.add(url)
            if progress:
                progress({"phase": "カテゴリページ取得中",
                          "category": " > ".join(page.category_path), "url": url,
                          "count": len(result.faqs), "errors": len(result.errors)})
            try:
                html = self._get(url)
                soup = BeautifulSoup(html, "lxml")
                path = _heading_category_path(soup, page.category_path)
                faq_links = parse_faq_links(html, url, path)
                # Category result lists are populated by faq_bundle.js from a
                # same-directory JSON endpoint, so requests must fetch it explicitly.
                if soup.select_one("#faq-result"):
                    faq_json_url = normalize_url("faq.json", url)
                    if is_allowed_jasso_url(faq_json_url, root_url):
                        try:
                            faq_links.extend(parse_faq_json(
                                self._get(faq_json_url), url, path
                            ))
                        except (json.JSONDecodeError, ValueError, TypeError) as exc:
                            result.errors.append(CrawlError(
                                faq_json_url, f"FAQ一覧JSONを解析できませんでした: {exc}",
                                " > ".join(path),
                            ))
                # Top-page HTML and faq.json can contain the same detail link.
                faq_links = list({link.url: link for link in faq_links}.values())
                faq_url_set = {x.url for x in faq_links}
                for link in faq_links:
                    if link.url in detail_urls or not is_allowed_jasso_url(link.url, root_url):
                        continue
                    detail_urls.add(link.url)
                    try:
                        result.faqs.append(parse_detail(self._get(link.url), link.url, link))
                        if progress:
                            progress({"phase": "Q&A詳細取得中",
                                      "category": " > ".join(link.category_path),
                                      "url": link.url, "count": len(result.faqs),
                                      "errors": len(result.errors)})
                    except Exception as exc:
                        self._debug_html(link.url, self.cache.get(link.url, ""))
                        result.errors.append(CrawlError(link.url, str(exc), " > ".join(link.category_path)))
                        if progress:
                            progress({"phase": "Q&A解析エラー",
                                      "category": " > ".join(link.category_path),
                                      "url": link.url, "count": len(result.faqs),
                                      "errors": len(result.errors)})
                for label, child_url in _visible_links(_main(soup), url):
                    if child_url in faq_url_set or child_url in visited_pages:
                        continue
                    if is_allowed_jasso_url(child_url, root_url):
                        next_path = path
                        if label not in ("次へ", "前へ") and not label.isdigit() and len(label) <= 100:
                            next_path = (path + (label,))[-2:]
                        pending.append(CrawlPage(child_url, next_path, url))
            except Exception as exc:
                result.errors.append(CrawlError(url, str(exc), " > ".join(page.category_path)))
                if progress:
                    progress({"phase": "カテゴリページ取得エラー",
                              "category": " > ".join(page.category_path), "url": url,
                              "count": len(result.faqs), "errors": len(result.errors)})
                if "401" in str(exc) or "403" in str(exc):
                    break
        return result

    def _debug_html(self, url: str, html: str) -> None:
        if not self.debug_dir or not html:
            return
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        name = make_qa_id(url) + ".html"
        (self.debug_dir / name).write_text(html, encoding="utf-8")
