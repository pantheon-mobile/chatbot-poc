from jasso_utils import (
    extract_update, is_allowed_jasso_url, make_content_hash, make_qa_id, normalize_text,
    normalize_url, strip_update,
)


def test_normalize_japanese_whitespace():
    assert normalize_text("  大学\u3000大学院\n 短大  ") == "大学 大学院 短大"


def test_normalize_url_and_stable_id():
    assert normalize_url("../faq/a.html#part", "https://www.jasso.go.jp/x/y/") == (
        "https://www.jasso.go.jp/x/faq/a.html"
    )
    assert normalize_url("mailto:test@example.com") == ""
    assert make_qa_id("https://www.jasso.go.jp/faq/a.html#x") == make_qa_id(
        "https://www.jasso.go.jp/faq/a.html"
    )


def test_update_variants_and_strip():
    assert extract_update("質問（2026年4月更新）") == ("2026年4月更新", 2026, 4)
    assert extract_update("質問 (2025年 3月 更新)") == ("2025年3月更新", 2025, 3)
    assert extract_update("質問") == ("", 0, 0)
    assert strip_update("質問です。（2026年4月更新）") == "質問です。"


def test_content_hash_is_normalized_and_stable():
    assert make_content_hash(" 質問 ", "回答\nです") == make_content_hash("質問", "回答\nです")


def test_authenticated_host_is_limited_to_root_host():
    root = "https://www2.jasso.go.jp/daigaku/faq/index.html"
    assert is_allowed_jasso_url("https://www2.jasso.go.jp/daigaku/faq/a.html", root)
    assert not is_allowed_jasso_url("https://www.jasso.go.jp/daigaku/faq/a.html", root)
