import sys
from pathlib import Path

# Add backend directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.agents.budget_agent import BudgetAgent
from core.db_manager import db_session, execute_sql

def run_test():
    print("==================================================")
    print("🔍 啟動：預算代理人整數股分配與餘額扣減測試")
    print("==================================================")
    
    agent = BudgetAgent()
    
    # Backup capital ledger state first
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor, "SELECT * FROM capital_ledger WHERE currency = 'USD'", "SELECT * FROM capital_ledger WHERE currency = 'USD'")
        orig_usd = cursor.fetchone()
        
    print(f"[*] 測試前 USD 原始狀態: {dict(orig_usd) if orig_usd else 'None'}")
    
    # 1. Reset capital_ledger USD to exactly 10,000 for standard testing
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor, 
            "UPDATE capital_ledger SET available_capital = 10000.0, reserved_cash = 2000.0 WHERE currency = 'USD'",
            "UPDATE capital_ledger SET available_capital = 10000.0, reserved_cash = 2000.0 WHERE currency = 'USD'"
        )
    
    print("\n--- 測試案例 1: 預算足夠，購買高價股整數股 (例如 MU @ 923.52，權重 15%) ---")
    # Expected: target budget = 10000 * 0.15 = 1500 USD
    # shares = floor(1500 / 923.52) = 1 share
    # invested_amount = 1 * 923.52 = 923.52 USD
    # remaining_capital = 10000 - 923.52 = 9076.48 USD
    amount, shares = agent.allocate_budget(ticker="MU", region="US", recommend_price=923.52, custom_weight=0.15)
    print(f"[✓] 計算結果 ── 分配金額: {amount:.2f} | 股數: {shares} (應為 1.0) | 實際投入率: {amount/10000.0*100:.2f}%")
    
    state1 = agent.get_capital_state("USD")
    print(f"[✓] 剩餘可用餘額: {state1['available_capital']:.2f} (應為 9076.48)")
    
    print("\n--- 測試案例 2: 購買中價股整數股 (例如 QCOM @ 243.29，權重 10%) ---")
    # Available capital now: 9076.48 USD
    # Expected: target budget = 9076.48 * 0.10 = 907.648 USD
    # shares = floor(907.648 / 243.29) = 3 shares
    # invested_amount = 3 * 243.29 = 729.87 USD
    # remaining_capital = 9076.48 - 729.87 = 8346.61 USD
    amount2, shares2 = agent.allocate_budget(ticker="QCOM", region="US", recommend_price=243.29, custom_weight=0.10)
    print(f"[✓] 計算結果 ── 分配金額: {amount2:.2f} | 股數: {shares2} (應為 3.0)")
    
    state2 = agent.get_capital_state("USD")
    print(f"[✓] 剩餘可用餘額: {state2['available_capital']:.2f} (應為 8346.61)")

    print("\n--- 測試案例 3: 觸發最低 1 股防線 (例如 TSLA @ 220.00，預算只分到 100 USD) ---")
    # Let's set available capital to exactly 500 USD
    with db_session() as conn:
        cursor = conn.cursor()
        execute_sql(cursor, 
            "UPDATE capital_ledger SET available_capital = 500.0 WHERE currency = 'USD'",
            "UPDATE capital_ledger SET available_capital = 500.0 WHERE currency = 'USD'"
        )
    # Target budget = 500 * 0.15 = 75 USD
    # floor(75 / 220) = 0 shares
    # But since available (500) >= price (220), we should force buy 1 share!
    # Expected: shares = 1, invested_amount = 220.00 USD, remaining = 280.00 USD
    amount3, shares3 = agent.allocate_budget(ticker="TSLA", region="US", recommend_price=220.00, custom_weight=0.15)
    print(f"[✓] 計算結果 ── 分配金額: {amount3:.2f} | 股數: {shares3} (應為 1.0)")
    
    state3 = agent.get_capital_state("USD")
    print(f"[✓] 剩餘可用餘額: {state3['available_capital']:.2f} (應為 280.00)")
    
    print("\n--- 測試案例 4: 剩餘可用資金不足以購買 1 股 ---")
    # Available capital now: 280.00 USD
    # Ticker price: 300.00 USD
    # Expected: return 0.0, 0.0
    amount4, shares4 = agent.allocate_budget(ticker="MSFT", region="US", recommend_price=300.00, custom_weight=0.10)
    print(f"[✓] 計算結果 ── 分配金額: {amount4:.2f} | 股數: {shares4} (應為 0.0)")

    # Restore original state
    if orig_usd:
        with db_session() as conn:
            cursor = conn.cursor()
            execute_sql(cursor, 
                "UPDATE capital_ledger SET available_capital = ?, reserved_cash = ? WHERE currency = 'USD'",
                "UPDATE capital_ledger SET available_capital = %s, reserved_cash = %s WHERE currency = 'USD'",
                (orig_usd["available_capital"], orig_usd["reserved_cash"])
            )
        print("\n[✓] 測試完畢，原始 USD 資金餘額已還原！")

if __name__ == "__main__":
    run_test()
