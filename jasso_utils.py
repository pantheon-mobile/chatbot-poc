from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo


UPDATED_RE = re.compile(r"[（(]\s*(\d{4})年\s*(\d{1,2})月\s*更新\s*[）)]")
SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "data:")


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").replace("\u3000", " ").split()).strip()


def normalize_multiline(value: str | None) -> str:
    lines = [normalize_text(line) for line in (value or "").splitlines()]
    output: list[str] = []
    for line in lines:
        if line:
            output.append(line)
        elif output and output[-1]:
            output.append("")
    return "\n".join(output).strip()


def normalize_url(url: str, base_url: str = "") -> str:
    raw = (url or "").strip()
    if not raw or raw.lower().startswith(SKIP_SCHEMES) or raw.startswith("#"):
        return ""
    absolute = urljoin(base_url, raw)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), host + port, path, query, ""))


def is_allowed_jasso_url(url: str, root_url: str = "") -> bool:
    parts = urlsplit(url)
    if parts.hostname != "www.jasso.go.jp":
        return False
    if re.search(r"\.(?:pdf|docx?|xlsx?|xls|jpe?g|png|gif|zip)(?:$|\?)", parts.path, re.I):
        return False
    if root_url:
        root_path = urlsplit(root_url).path
        root_dir = root_path if root_path.endswith("/") else root_path.rsplit("/", 1)[0] + "/"
        return parts.path == root_path or parts.path.startswith(root_dir)
    return True


def extract_update(value: str) -> tuple[str, int, int]:
    match = UPDATED_RE.search(value or "")
    if not match:
        return "", 0, 0
    year, month = int(match.group(1)), int(match.group(2))
    return f"{year}年{month}月更新", year, month


def strip_update(value: str) -> str:
    return normalize_text(UPDATED_RE.sub("", value or ""))


def make_qa_id(source_url: str) -> str:
    digest = hashlib.sha256(normalize_url(source_url).encode("utf-8")).hexdigest()[:16]
    return f"jasso_{digest}"


def make_content_hash(question: str, answer: str) -> str:
    source = normalize_text(question) + "\n" + normalize_multiline(answer)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def now_jst() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).replace(microsecond=0).isoformat()
