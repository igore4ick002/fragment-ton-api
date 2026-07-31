import unittest

from fragment_api.catalog import _parse_items


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


if __name__ == "__main__":
    unittest.main()
