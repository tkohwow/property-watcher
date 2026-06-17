import unittest

from property_watcher.parser import parse_html


class ParserTest(unittest.TestCase):
    def test_extracts_property_overview_and_ignores_page_chrome(self):
        html = """
        <html><head>
          <title>グラーサ中野坂上 7階（2LDK）｜SUUMO</title>
          <meta property="og:title" content="グラーサ中野坂上 7階">
          <meta name="description" content="中古マンションの物件情報です">
        </head><body>
          <header>ログイン お気に入り 全国へ</header>
          <main class="main-detail">
            <h1>グラーサ中野坂上 7階</h1>
            <table>
              <tr><th>価格</th><td>9,500万円</td></tr>
              <tr><th>間取り</th><td>2LDK</td></tr>
              <tr><th>専有面積</th><td>50.1㎡</td></tr>
              <tr><th>所在地</th><td>東京都中野区本町3</td></tr>
              <tr><th>交通</th><td>東京メトロ丸ノ内線「中野坂上」歩3分</td></tr>
              <tr><th>管理費</th><td>1万3590円／月</td></tr>
            </table>
            <h2>特徴・設備</h2><ul><li>角住戸</li><li>浴室乾燥機</li></ul>
          </main>
          <aside class="recommend">おすすめ物件 8,000万円</aside>
          <footer>住宅ローンシミュレーション 利用規約</footer>
        </body></html>
        """

        parsed = parse_html(html)

        self.assertEqual(parsed["price"], 9500)
        self.assertIn("物件名: グラーサ中野坂上 7階", parsed["raw_text"])
        self.assertIn("価格: 9,500万円", parsed["raw_text"])
        self.assertIn("交通: 東京メトロ丸ノ内線「中野坂上」歩3分", parsed["raw_text"])
        self.assertIn("- 角住戸", parsed["raw_text"])
        self.assertNotIn("ログイン", parsed["raw_text"])
        self.assertNotIn("おすすめ物件", parsed["raw_text"])
        self.assertNotIn("住宅ローン", parsed["raw_text"])

    def test_uses_dt_dd_and_og_title_when_title_is_missing(self):
        html = """
        <html><head><meta property="og:title" content="テストマンション"></head><body>
          <dl><dt>築年月</dt><dd>2006年2月</dd><dt>現況</dt><dd>空室</dd></dl>
        </body></html>
        """
        parsed = parse_html(html)
        self.assertEqual(parsed["title"], "テストマンション")
        self.assertIn("物件名: テストマンション", parsed["raw_text"])
        self.assertIn("築年月: 2006年2月", parsed["raw_text"])
        self.assertIn("現況: 空室", parsed["raw_text"])

    def test_json_ld_ignores_breadcrumb_names(self):
        html = """
        <html><head><title>物件A</title>
          <script type="application/ld+json">
          {"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","name":"中古マンション検索"}]}
          </script>
          <script type="application/ld+json">
          {"@type":"Product","name":"物件A","floorSize":{"value":"50.1㎡"},
           "offers":{"@type":"Offer","price":"95000000","priceCurrency":"JPY"}}
          </script>
        </head><body></body></html>
        """
        parsed = parse_html(html)
        self.assertIn("専有面積: 50.1㎡", parsed["raw_text"])
        self.assertEqual(parsed["price"], 9500)
        self.assertNotIn("中古マンション検索", parsed["raw_text"])

    def test_fallback_never_becomes_empty_for_sparse_property_page(self):
        html = """
        <html><head><title>物件詳細</title></head><body>
          <div class="search-guide"><p>価格 3,980万円</p><p>専有面積 60.2㎡</p></div>
        </body></html>
        """
        parsed = parse_html(html)
        self.assertIn("物件名: 物件詳細", parsed["raw_text"])
        self.assertIn("3,980万円", parsed["raw_text"])


if __name__ == "__main__":
    unittest.main()
