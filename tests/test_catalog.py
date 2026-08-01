import unittest

from fragment_api.catalog import _absolute_url, _parse_items


class CatalogParsingTests(unittest.TestCase):
    def test_parse_fixed_price_gift(self):
        html = """
        <a href="/gift/lol-pop-12345" class="tm-grid-item">
          <picture><img src="/file/preview.png"></picture>
          <div class="item-name">Lol Pop #12345</div>
          <div class="tm-grid-item-status avail">For sale</div>
          <div class="tm-grid-item-value">1,234</div>
        </a>
        """

        items = _parse_items(html, "lol-pop", limit=10)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["slug"], "lol-pop-12345")
        self.assertEqual(items[0]["collection"], "lol-pop")
        self.assertEqual(items[0]["number"], 12345)
        self.assertEqual(items[0]["price_ton"], 1234.0)
        self.assertEqual(items[0]["status"], "for_sale")
        self.assertEqual(items[0]["url"], "https://fragment.com/gift/lol-pop-12345")

    def test_skip_non_sale_items(self):
        html = """
        <a href="/gift/lol-pop-12345" class="tm-grid-item">
          <div class="tm-grid-item-status sold">Sold</div>
          <div class="tm-grid-item-value">1</div>
        </a>
        """

        self.assertEqual(_parse_items(html, "lol-pop", limit=10), [])

    def test_limit_stops_parsing_early(self):
        html = "".join(
            f"""
            <a href="/gift/lol-pop-{n}" class="tm-grid-item">
              <div class="item-name">Lol Pop #{n}</div>
              <div class="tm-grid-item-status avail">For sale</div>
              <div class="tm-grid-item-value">{n}</div>
            </a>
            """
            for n in (1, 2, 3)
        )

        items = _parse_items(html, "lol-pop", limit=2)

        self.assertEqual(len(items), 2)
        self.assertEqual([item["number"] for item in items], [1, 2])

    def test_item_without_image_has_none_image_url(self):
        html = """
        <a href="/gift/lol-pop-12345" class="tm-grid-item">
          <div class="item-name">Lol Pop #12345</div>
          <div class="tm-grid-item-status avail">For sale</div>
          <div class="tm-grid-item-value">1</div>
        </a>
        """

        items = _parse_items(html, "lol-pop", limit=10)

        self.assertEqual(items[0]["image_url"], None)


class AbsoluteUrlTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(_absolute_url(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_absolute_url(""))

    def test_relative_path_becomes_absolute(self):
        self.assertEqual(_absolute_url("/file/preview.png"), "https://fragment.com/file/preview.png")

    def test_already_absolute_url_is_returned_unchanged(self):
        self.assertEqual(_absolute_url("https://cdn.example.com/x.png"), "https://cdn.example.com/x.png")


if __name__ == "__main__":
    unittest.main()
