"""
Aegis-MAQS (Aegis Multi-Agent Quantmental System)
Module: core.agents.liquidity_agent
Description:
    Macro Liquidity & Flow Scout Agent (流動性偵察代理人).
    Evaluates global macro liquidity (US Net Liquidity) and regional large capital flows (Taiwan futures/spot).
    Qualitatively audits capital market water levels, assesses systemic liquidity risks,
    and outputs a binding [LIQUIDITY_REGIME: EXPANSION/NEUTRAL/CONTRACTION] directive.
    Designed with high maintainability, clear comments, and standalone single-feature testability.
"""

import sys
from pathlib import Path

# Dynamic path bootstrapping: Add backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import json
from core.agents.base_agent import BaseAgent


# Prompt baseline configuration
FALLBACK_INSTRUCTION = """
你是一位資深的「宏觀資金流與流動性偵察專家 (Macro Liquidity & Flow Scout Agent)」。
你的職責是深入審查全球金融市場的實質資金水位、央行資產負債表動能、大機構避險籌碼動態，並對系統的資金曝險提出剛性的風控指引。

你必須遵循以下審計準則與評級標準：
1. 分析美股淨流動性 (US Net Liquidity) 的 4 週變化率 (ROC)：
   - 若 ROC > +2%，代表美聯儲擴表或逆回購資金釋放，流動性呈加速擴張。
   - 若 ROC 處於 -1% 到 +2% 之間，代表流動性常態中性。
   - 若 ROC < -2%，代表縮表加速或財政部抽離流動性，市場正處於「失水」狀態。

2. 分析台股外資期指動態滾動指標 (以系統計算之過去 60 交易日統計為準)：
   - 若當前部位高於「動態極度看多界線」，代表外資情緒極度樂觀，無避險意圖，市場資金動能強勁。
   - 若當前部位處於「動態極度看多界線」與「動態極度看空界線」之間，代表外資進行常態性對沖避險，市場資金面中性。
   - 若當前部位低於「動態極度看空界線」，代表外資正在建立極端的期貨空單防線，隨時可能發動現貨大出清，流動性收縮與系統性崩盤風險急遽上升。

3. 評估「複合流動性得分 (CLS)」：
   - CLS < 0.35：資金面極其充沛。你必須輸出 `[LIQUIDITY_REGIME: EXPANSION]`，支持系統積極擴張。
   - 0.35 <= CLS < 0.70：資金面中性常態。你必須輸出 `[LIQUIDITY_REGIME: NEUTRAL]`，維持標準常態交易。
   - CLS >= 0.70：資金面嚴重收緊或大資金極端避險。你必須強制輸出 `[LIQUIDITY_REGIME: CONTRACTION]`，啟動防禦熔斷，強制下修持倉上限並增持現金。

【剛性輸出格式約束】：
你的報告必須包含：
- 【全球與台股流動性現狀審計】：簡述客觀數據與動態滾動閾值特徵。
- 【系統性流動性風險評估】：分析可能面臨的資金面威脅與大戶避險意圖。
- 報告的【最後一行】必須精確輸出以下三個標籤之一，嚴格禁止任何附加文字：
  [LIQUIDITY_REGIME: EXPANSION] 或 [LIQUIDITY_REGIME: NEUTRAL] 或 [LIQUIDITY_REGIME: CONTRACTION]
"""

class LiquidityScoutAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="LiquidityScoutAgent",
            role="Macro Liquidity & Flow Scout",
            system_instruction=FALLBACK_INSTRUCTION,
            register_db=True
        )

    def analyze(self, region_name: str, liquidity_state: dict) -> str:
        """
        Runs the qualitative macro liquidity audit based on the gathered quantitative state.
        
        Args:
            region_name (str): The target region (e.g. 'US' or 'Taiwan').
            liquidity_state (dict): Output from core.tools.liquidity_loader.get_liquidity_state.
        """
        # Format the numbers beautifully for the LLM
        us_liq_bil = liquidity_state.get("us_net_liquidity", 0.0)
        us_roc = liquidity_state.get("us_liquidity_roc_4w", 0.0)
        tw_futures = liquidity_state.get("tw_foreign_futures_oi", 0)
        tw_foreign_buy = liquidity_state.get("tw_foreign_net_buy", 0.0)
        tw_dealers_buy = liquidity_state.get("tw_dealers_net_buy", 0.0)
        tw_trust_buy = liquidity_state.get("tw_trust_net_buy", 0.0)
        cls = liquidity_state.get("composite_score", 0.5)
        source = liquidity_state.get("source", "unknown")
        
        # Extract dynamic rolling statistical thresholds (with standard static fallbacks)
        tw_bull_thr = liquidity_state.get("dynamic_bullish_threshold", 10000.0)
        tw_bear_thr = liquidity_state.get("dynamic_bearish_threshold", -30000.0)
        tw_mean = liquidity_state.get("dynamic_futures_mean", -8000.0)
        tw_std = liquidity_state.get("dynamic_futures_std", 5000.0)
        
        prompt = f"""
請針對【{region_name}】市場及全球流動性環境進行深入的資金面審計。

【實時量化資金流動性數據庫截圖】：
* 數據來源模式: {source.upper()}
* 複合流動性得分 (Composite Liquidity Score, CLS): {cls:.4f} (範圍: 0.0=極充沛, 1.0=極緊縮)
* 美股淨流動性規模 (US Net Liquidity): {us_liq_bil:,.2f} 十億美元 (Billions)
* 美股淨流動性 4 週變化率 (ROC): {us_roc*100:+.2f}%

* 台股外資期指未平倉淨部位: {tw_futures:+,} 口 (Contracts)
* 台股外資期指動態滾動統計 (過去 60 交易日):
  - 歷史均值 (Mean, μ): {tw_mean:+,.2f} 口
  - 波動標準差 (StdDev, σ): {tw_std:,.2f} 口
  - 動態極度看多界線 (Mean + 1.5σ): {tw_bull_thr:+,.2f} 口
  - 動態極度看空界線 (Mean - 2.0σ): {tw_bear_thr:+,.2f} 口

* 台股當日三大法人現貨買賣超:
  - 外資現貨買賣超: {tw_foreign_buy/100000000.0:+.2f} 億元 TWD
  - 自營商現貨買賣超: {tw_dealers_buy/100000000.0:+.2f} 億元 TWD
  - 投信現貨買賣超: {tw_trust_buy/100000000.0:+.2f} 億元 TWD

請依據上述數據，進行商業與市場流動性深度分析，評估大資金對沖意圖，並給出你剛性的流動性狀態標籤（[LIQUIDITY_REGIME: ...]）。
"""
        return self.run(prompt)

# --- Standalone Self-Testing Block ---

if __name__ == "__main__":
    print("\033[93m==================================================\033[0m")
    print("\033[93m🧪 單獨功能測試：流動性偵察代理人 (liquidity_agent.py)\033[0m")
    print("\033[93m==================================================\033[0m")
    
    # 1. Load mock/live data using the loader
    from core.tools.liquidity_loader import get_liquidity_state
    from datetime import datetime
    
    test_date = datetime.now().strftime("%Y-%m-%d")
    print(f"[*] 步驟一：調用加載器獲取 ({test_date}) 流動性數據狀態...")
    state = get_liquidity_state(test_date, is_backtest=False)
    
    # 2. Run Agent analysis
    print("\n[*] 步驟二：喚醒 LiquidityScoutAgent 進行大模型推理...")
    agent = LiquidityScoutAgent()
    report = agent.analyze("Taiwan", state)
    
    print("\n\033[96m==================================================\033[0m")
    print("\033[96m📝 大模型產出：流動性審計報告\033[0m")
    print("\033[96m==================================================\033[0m")
    print(report)
    print("\033[96m==================================================\033[0m")
    
    # 3. Verify tag extraction logic
    import re
    regime_match = re.search(r"\[LIQUIDITY_REGIME:\s*(EXPANSION|NEUTRAL|CONTRACTION)\]", report)
    if regime_match:
        print(f"\n[✓] 成功解析流動性狀態標籤: \033[93m{regime_match.group(1)}\033[0m")
    else:
        print("\n[✗] 錯誤：未在大模型報告中找到標準的 [LIQUIDITY_REGIME: ...] 格式標籤。")
        
    print("\n\033[93m==================================================\033[0m")
    print("\033[93m✓ 流動性偵察代理人單獨功能測試完成。\033[0m")
    print("\033[93m==================================================\033[0m")
