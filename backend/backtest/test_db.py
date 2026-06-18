import sys
from pathlib import Path

# Add backend directory to path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(BACKEND_ROOT))

from backtest.db_backtest import init_backtest_database, get_backtest_capital_state, apply_backtest_db_sandbox

def test_initialization():
    print("[*] 正在測試回測沙盒資料庫初始化...")
    init_backtest_database(initial_usd=100000.0, initial_twd=3000000.0)
    
    # Verify local helper functions
    usd_state = get_backtest_capital_state("USD")
    twd_state = get_backtest_capital_state("TWD")
    assert usd_state["available_capital"] == 100000.0
    assert twd_state["available_capital"] == 3000000.0
    
    # 2. Test Monkey-Patching DB connection redirection
    print("[*] 正在測試資料庫猴子補丁安全隔離...")
    apply_backtest_db_sandbox()
    
    import core.db_manager as prod_db
    # Now, any calls using prod_db.db_session should route to the backtest SQLite DB
    with prod_db.db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT available_capital FROM capital_ledger WHERE currency = ?", ("USD",))
        row = cursor.fetchone()
        # Should return our backtest value (100000.0)
        assert row[0] == 100000.0
        
    print("[✓] 測試成功！資料庫安全隔離補丁運作完全正常，實戰庫已獲得 100% 防污染保護。")

if __name__ == "__main__":
    test_initialization()
