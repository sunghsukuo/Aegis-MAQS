import sys
from pathlib import Path
import time

# Add backend root to sys.path
backend_root = str(Path(__file__).resolve().parent.parent)
sys.path.append(backend_root)

import core.tools.yahoo_finance as yf_tool
import core.tools.web_search as search_tool
from core.agents.market_agent import MarketAgent

def dry_run_market_agent():
    print("==================================================")
    print(" 🔍 測試：升級版 MarketAgent 總體量化 + 產業定性推論 Prompt 驗證")
    print("==================================================")
    
    region_code = "Taiwan"
    region_name = "台股"
    
    # 1. 獲取真實定量板塊強度排行
    print("1. 獲取台股真實板塊強度表現排行...")
    sector_rankings = yf_tool.get_sector_rankings(region_code)
    
    # 2. 獲取前 2 強非 Broad Market 板塊之定性產業趨勢新聞
    print("2. 動態檢索最強勢板塊之產業趨勢新聞...")
    sector_news = []
    
    # 過濾寬基 Broad Market，聚焦產業
    c_sectors = [sec for sec in sector_rankings if "Broad Market" not in sec["label"]]
    if not c_sectors:
        c_sectors = sector_rankings
        
    top_2_sectors = c_sectors[:2]
    for sec in top_2_sectors:
        label = sec["label"]
        import re as local_re
        match = local_re.match(r"^([^\(]+)", label)
        sector_name = match.group(1).strip() if match else label
        
        query = f"台灣 {sector_name} 產業 新聞 when:7d"
        print(f"   - 正在抓取板塊【{label}】產業動態: '{query}'")
        news_items = search_tool.search_news(query, max_items=1, language="zh-TW", region="TW")
        sector_news.extend(news_items)
        time.sleep(1) # Cooldown
        
    # 3. 初始化 MarketAgent 並生成分析
    print("3. 初始化 MarketAgent 並生成 Input Prompt...")
    market_agent = MarketAgent()
    
    # We run analyze to populate market_agent.last_prompt
    print("4. 模擬執行分析 (Inference)...")
    try:
        report = market_agent.analyze(region_name, sector_rankings, sector_news)
        print("\n[✓] 分析執行成功！")
        
        # 5. 印出大模型收到的 Full Input Prompt!
        print("\n==================================================")
        print(" 🎯 大模型最終收到的真實 Input Prompt (定性 + 定量結合)：")
        print("==================================================")
        print(market_agent.last_prompt)
        print("==================================================")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    dry_run_market_agent()
