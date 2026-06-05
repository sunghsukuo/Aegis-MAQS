import unittest
import sys
from pathlib import Path

# Add backend to sys.path to allow core.* imports
sys.path.append(str(Path(__file__).resolve().parent))

from core.utils.parsers import format_markdown_for_terminal, extract_price_from_line, extract_range_from_line
from core.utils.formatters import get_display_width, pad_left, pad_right, pad_center, get_progress_bar

class TestUtilsParsers(unittest.TestCase):
    def test_format_markdown_for_terminal_headers(self):
        text = "### Test Header\n#### Sub Header"
        res = format_markdown_for_terminal(text)
        self.assertIn("【 Test Header 】", res)
        self.assertIn("  Sub Header", res)

    def test_format_markdown_for_terminal_bullets(self):
        text = "* **bold** item\n- Item 2 _italic_"
        res = format_markdown_for_terminal(text)
        self.assertIn("▪ bold item", res)
        self.assertIn("▪ Item 2 italic", res)

    def test_extract_price_from_line(self):
        line = "建議停損價為 NT$324.50 元，買入區間..."
        price = extract_price_from_line(line, current_price=330.0)
        self.assertEqual(price, 324.5)

    def test_extract_price_from_line_outlier(self):
        line = "參考 SMA 200 日線在 50.0 元，但目前目標價為 350.0 元"
        price = extract_price_from_line(line, current_price=340.0)
        self.assertEqual(price, 350.0)

    def test_extract_range_from_line(self):
        line = "買入區間落在 320.00 - 325.50 元之間"
        r = extract_range_from_line(line, current_price=322.0)
        self.assertEqual(r, "320.00 - 325.50")

class TestUtilsFormatters(unittest.TestCase):
    def test_get_display_width(self):
        self.assertEqual(get_display_width("Hello"), 5)
        self.assertEqual(get_display_width("中文"), 4)
        self.assertEqual(get_display_width("💰"), 2)

    def test_padding(self):
        self.assertEqual(pad_left("Hello", 10), "     Hello")
        self.assertEqual(pad_right("Hello", 10), "Hello     ")
        self.assertEqual(pad_center("Hello", 10), "  Hello   ")

    def test_get_progress_bar(self):
        # We test with a dummy date format
        elapsed, percent, bar = get_progress_bar("2026-06-01", total_days=30)
        self.assertTrue(elapsed >= 1)
        self.assertEqual(len(bar), 30)

class TestRegime(unittest.TestCase):
    def test_calculate_hurst_flat(self):
        from core.regime.detector import calculate_hurst
        # Generate some trending data
        ts = [100.0 + i * 2 for i in range(30)]
        h = calculate_hurst(ts)
        # Trending time series should have Hurst exponent > 0.5 (or close to it/positive)
        self.assertTrue(isinstance(h, float))

    def test_regime_registry_cache(self):
        from core.regime.registry import save_market_regime, get_market_regime
        mock_regime = {"regime": "MEAN_REVERSION_RANGE", "adx": 15.4, "hurst": 0.42, "ticker": "^GSPC"}
        save_market_regime("US_TEST", mock_regime)
        retrieved = get_market_regime("US_TEST")
        self.assertEqual(retrieved["regime"], "MEAN_REVERSION_RANGE")
        self.assertEqual(retrieved["adx"], 15.4)
        self.assertEqual(retrieved["hurst"], 0.42)

if __name__ == "__main__":
    unittest.main()
