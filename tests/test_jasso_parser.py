from jasso_crawler import JassoCrawler, parse_detail, parse_faq_links


LIST_HTML = """
<html><main><nav class="breadcrumb"><span>予約採用</span><span>通知</span></nav>
<a href="/faq/detail1.html">Q 質問ですか。（2026年4月更新）</a>
<a href="/faq/detail1.html">Q 質問ですか。（2026年4月更新）</a>
<a href="/faq/category/1214014_2903.html">多子世帯と判定されていないのはなぜですか。（2026年4月更新）</a>
<a href="/faq/category/index.html">カテゴリ一覧</a>
</main></html>
"""
DETAIL_HTML = """
<html><main><nav class="breadcrumb"><span>ホーム</span><span>予約採用</span><span>通知</span></nav>
<h2>Q</h2><div><p>質問ですか。</p></div>
<h2>A</h2><div><p>回答の第1段落。</p><ul><li>項目1</li><li>項目2</li></ul></div>
</main></html>
"""
CURRENT_DETAIL_HTML = """
<html><main>
<section class="p-section p-section--faq">
  <h2 class="p-faq-q">現在の質問ですか。</h2>
  <div class="p-section-content p-faq-a"><p>現在の回答です。</p></div>
</section>
</main></html>
"""


def test_faq_link_update_and_duplicate_deduplication():
    links = parse_faq_links(LIST_HTML, "https://www.jasso.go.jp/faq/list.html", ("予約採用", "通知"))
    assert len(links) == 2
    assert links[0].question == "質問ですか。"
    assert links[0].source_updated_year == 2026
    assert links[1].question == "多子世帯と判定されていないのはなぜですか。"


def test_detail_parser():
    link = parse_faq_links(LIST_HTML, "https://www.jasso.go.jp/faq/list.html", ("予約採用", "通知"))[0]
    item = parse_detail(DETAIL_HTML, link.url, link)
    assert item.question == "質問ですか。"
    assert "回答の第1段落。" in item.answer
    assert "項目1" in item.answer
    assert item.category_path == "予約採用 > 通知"


def test_current_faq_class_detail_parser():
    link = parse_faq_links(LIST_HTML, "https://www.jasso.go.jp/faq/list.html", ("予約採用", "通知"))[0]
    item = parse_detail(CURRENT_DETAIL_HTML, link.url, link)
    assert item.question == "現在の質問ですか。"
    assert item.answer == "現在の回答です。"


def test_login_selects_password_form_after_search_form(monkeypatch):
    login_html = """
    <form action="/search"><input type="search" name="search"></form>
    <form action="/tantosha_login.html" method="post">
      <input type="hidden" name="_token" value="token">
      <input type="text" name="login_id">
      <input type="password" name="login_pass">
      <input type="submit" name="login_submit" value="ログイン">
    </form>
    """
    logged_in_html = '<main><a href="/school/">大学・大学院・短大・高専・専修学校 専門課程</a></main>'
    school_html = '<main><a href="/school/faq/">よくあるご質問</a></main>'
    calls = []

    class Response:
        def __init__(self, url, text, json_data=None):
            self.url, self.text, self.json_data = url, text, json_data

        def json(self):
            if self.json_data is None:
                raise ValueError
            return self.json_data

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if len(calls) == 1:
            return Response("https://www.jasso.go.jp/tantosha_login.html", login_html)
        if len(calls) == 2:
            return Response(
                url, '{"success":true,"url":"https://www2.jasso.go.jp/index.html"}',
                {"success": True, "url": "https://www2.jasso.go.jp/index.html"},
            )
        if len(calls) == 3:
            return Response("https://www2.jasso.go.jp/index.html", logged_in_html)
        return Response(url, school_html)

    crawler = JassoCrawler("user", "secret")
    monkeypatch.setattr(crawler, "_request", fake_request)
    faq_url, _ = crawler.login()
    assert faq_url == "https://www2.jasso.go.jp/school/faq/"
    assert calls[1][2]["data"] == {
        "_token": "token", "login_id": "user",
        "login_pass": "secret", "login_submit": "ログイン",
    }
