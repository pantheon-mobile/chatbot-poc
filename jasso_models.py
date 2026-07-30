from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class CrawlPage:
    url: str
    category_path: tuple[str, ...] = ()
    parent_url: str = ""
    page_type: str = "category"


@dataclass
class FAQLink:
    url: str
    question: str
    category_path: tuple[str, ...]
    source_updated_text: str = ""
    source_updated_year: int = 0
    source_updated_month: int = 0


@dataclass
class JassoFAQ:
    qa_id: str
    question: str
    answer: str
    source_url: str
    top_category: str
    sub_category: str
    category_path: str
    source_updated_text: str
    source_updated_year: int
    source_updated_month: int
    crawled_at: str
    content_hash: str
    breadcrumb: list[str] = field(default_factory=list)


@dataclass
class CrawlError:
    url: str
    message: str
    category_path: str = ""


@dataclass
class CrawlResult:
    source_root_url: str
    faqs: list[JassoFAQ] = field(default_factory=list)
    errors: list[CrawlError] = field(default_factory=list)


ProgressCallback = Optional[Callable[[dict], None]]
