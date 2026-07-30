from jasso_crawler import parse_detail, parse_faq_links


LIST_HTML = """
<html><main><nav class="breadcrumb"><span>予約採用</span><span>通知</span></nav>
<a href="/faq/detail1.html">Q 質問ですか。（2026年4月更新）</a>
<a href="/faq/detail1.html">Q 質問ですか。（2026年4月更新）</a>
</main></html>
"""
DETAIL_HTML = """
<html><main><nav class="breadcrumb"><span>ホーム</span><span>予約採用</span><span>通知</span></nav>
<h2>Q</h2><div><p>質問ですか。</p></div>
<h2>A</h2><div><p>回答の第1段落。</p><ul><li>項目1</li><li>項目2</li></ul></div>
</main></html>
"""


def test_faq_link_update_and_duplicate_deduplication():
    links = parse_faq_links(LIST_HTML, "https://www.jasso.go.jp/faq/list.html", ("予約採用", "通知"))
    assert len(links) == 1
    assert links[0].question == "質問ですか。"
    assert links[0].source_updated_year == 2026


def test_detail_parser():
    link = parse_faq_links(LIST_HTML, "https://www.jasso.go.jp/faq/list.html", ("予約採用", "通知"))[0]
    item = parse_detail(DETAIL_HTML, link.url, link)
    assert item.question == "質問ですか。"
    assert "回答の第1段落。" in item.answer
    assert "項目1" in item.answer
    assert item.category_path == "予約採用 > 通知"
