import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
from core.regime.multi_factor import get_vix_scale, detect_meso_regime

class TestMultiFactorRegime(unittest.TestCase):
    
    def setUp(self):
        from core.config import CACHE_DIR
        self.cache_path = CACHE_DIR / "meso_regime.json"
        if self.cache_path.exists():
            try:
                self.cache_path.unlink()
            except Exception:
                pass

    def tearDown(self):
        if hasattr(self, 'cache_path') and self.cache_path.exists():
            try:
                self.cache_path.unlink()
            except Exception:
                pass
                
    def test_vix_scale_calculation(self):
        # Base VIX is 15.0
        self.assertAlmostEqual(get_vix_scale(15.0), 1.0)
        self.assertAlmostEqual(get_vix_scale(30.0), 0.5)
        # Check lower bound clamping (0.3)
        self.assertAlmostEqual(get_vix_scale(60.0), 0.3)
        # Check upper bound clamping (1.2)
        self.assertAlmostEqual(get_vix_scale(10.0), 1.2)
        # Edge cases
        self.assertAlmostEqual(get_vix_scale(0.0), 1.0)
        self.assertAlmostEqual(get_vix_scale(-5.0), 1.0)

    @patch("core.regime.multi_factor.fetch_multi_index_data")
    def test_regime_classification_volatile_panic(self, mock_fetch):
        # Mocking data with VIX > 25.0
        dates = pd.date_range(end="2026-06-06", periods=30)
        mock_data = {
            "GSPC": pd.DataFrame({"Close": [5000] * 30}, index=dates),
            "IXIC": pd.DataFrame({"Close": [16000] * 30}, index=dates),
            "RUT": pd.DataFrame({"Close": [2000] * 30}, index=dates),
            "VIX": pd.DataFrame({"Close": [28.0] * 30}, index=dates)  # VIX > 25
        }
        mock_fetch.return_value = mock_data
        
        result = detect_meso_regime()
        self.assertEqual(result["regime"], "VOLATILE_PANIC")
        self.assertAlmostEqual(result["vix_scale"], 15.0 / 28.0)

    @patch("core.regime.multi_factor.fetch_multi_index_data")
    def test_regime_classification_bear_risk_off(self, mock_fetch):
        # Mocking data with GSPC in downtrend (latest Close < MA_50) and VIX > 20
        dates = pd.date_range(end="2026-06-06", periods=30)
        # GSPC Close starts at 5000 and falls to 4000 (below its MA)
        gspc_prices = np.linspace(5000, 4000, 30)
        mock_data = {
            "GSPC": pd.DataFrame({"Close": gspc_prices}, index=dates),
            "IXIC": pd.DataFrame({"Close": [16000] * 30}, index=dates),
            "RUT": pd.DataFrame({"Close": [2000] * 30}, index=dates),
            "VIX": pd.DataFrame({"Close": [22.0] * 30}, index=dates)  # VIX > 20
        }
        mock_fetch.return_value = mock_data
        
        result = detect_meso_regime()
        self.assertEqual(result["regime"], "BEAR_RISK_OFF")

    @patch("core.regime.multi_factor.fetch_multi_index_data")
    def test_regime_classification_bull_growth_on(self, mock_fetch):
        # Mocking data with GSPC uptrend, low VIX, and Growth Ratio rising
        dates = pd.date_range(end="2026-06-06", periods=30)
        # GSPC rising
        gspc_prices = np.linspace(4000, 4500, 30)
        # IXIC rising faster than GSPC (Growth Ratio going up)
        ixic_prices = np.linspace(14000, 17000, 30)
        mock_data = {
            "GSPC": pd.DataFrame({"Close": gspc_prices}, index=dates),
            "IXIC": pd.DataFrame({"Close": ixic_prices}, index=dates),
            "RUT": pd.DataFrame({"Close": [2000] * 30}, index=dates),
            "VIX": pd.DataFrame({"Close": [14.0] * 30}, index=dates)
        }
        mock_fetch.return_value = mock_data
        
        result = detect_meso_regime()
        self.assertEqual(result["regime"], "BULL_GROWTH_ON")

    @patch("core.regime.multi_factor.fetch_multi_index_data")
    def test_regime_classification_bull_value_on(self, mock_fetch):
        # Mocking data with GSPC uptrend, low VIX, and Growth Ratio falling
        dates = pd.date_range(end="2026-06-06", periods=30)
        # GSPC rising
        gspc_prices = np.linspace(4000, 4500, 30)
        # IXIC rising slower/falling compared to GSPC (Growth Ratio going down)
        ixic_prices = np.linspace(16000, 15000, 30)
        mock_data = {
            "GSPC": pd.DataFrame({"Close": gspc_prices}, index=dates),
            "IXIC": pd.DataFrame({"Close": ixic_prices}, index=dates),
            "RUT": pd.DataFrame({"Close": [2000] * 30}, index=dates),
            "VIX": pd.DataFrame({"Close": [14.0] * 30}, index=dates)
        }
        mock_fetch.return_value = mock_data
        
        result = detect_meso_regime()
        self.assertEqual(result["regime"], "BULL_VALUE_ON")

if __name__ == "__main__":
    unittest.main()
